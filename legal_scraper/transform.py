"""Transform landing-zone data into a cleaned copy in the clean zone.

Reads landing metadata for a date range, cleans each HTML page down to the
decision body, leaves PDFs/DOCs as they are, renames files to identifier.ext,
and writes everything to a new bucket and collection. Landing is only read.
"""

import argparse
from datetime import datetime, timezone

import structlog
from bs4 import BeautifulSoup

from legal_scraper.config import get_settings
from legal_scraper.logging_config import configure_json_logging
from legal_scraper.storage.minio_store import MinioStore, compute_hash
from legal_scraper.storage.mongo import MongoStore

CONTENT_TYPES = {
    "html": "text/html",
    "pdf": "application/pdf",
    "doc": "application/msword",
}


def clean_html(raw: bytes) -> bytes:
    # Keep the decision body from div.content. Older EAT pages have no usable
    # content container, so fall back to the full page body rather than drop the
    # document. Either way, strip scripts and styles.
    soup = BeautifulSoup(raw, "lxml")
    content = soup.select_one("div.content")
    if not content or not content.get_text(strip=True):
        content = soup.body or soup
    for tag in content.find_all(["script", "style"]):
        tag.decompose()
    return str(content).encode("utf-8")


def _clean_key(record):
    # identifier.ext, kept under the same body/partition prefix. Spaces in the
    # rare malformed identifier are stripped so the object key stays clean.
    body_slug = record["body"].lower().replace(" ", "-")
    identifier = record["identifier"].replace(" ", "")
    ext = record.get("doc_type") or "html"
    return f"{body_slug}/{record['partition_date']}/{identifier}.{ext}"


def transform(start: str, end: str) -> dict:
    config = get_settings()
    log = structlog.get_logger()

    mongo = MongoStore(config.mongo_uri, config.mongo_database)
    mongo.ensure_identifier_index(config.mongo_clean_collection)
    minio = MinioStore(
        config.minio_endpoint, config.minio_access_key, config.minio_secret_key, config.minio_region
    )
    minio.ensure_bucket(config.minio_clean_bucket)

    stats = {"read": 0, "transformed": 0, "failed": 0}
    query = {"partition_date": {"$gte": start, "$lt": end}}
    for record in mongo.find(config.mongo_landing_collection, query):
        stats["read"] += 1
        identifier = record.get("identifier")
        try:
            raw = minio.download(config.minio_landing_bucket, record["file_path"])
            # HTML gets cleaned; pdf/doc are copied through untouched.
            data = clean_html(raw) if record.get("doc_type") == "html" else raw

            clean_key = _clean_key(record)
            content_type = CONTENT_TYPES.get(record.get("doc_type"), "application/octet-stream")
            minio.upload(config.minio_clean_bucket, clean_key, data, content_type)

            clean_doc = {k: v for k, v in record.items() if k != "_id"}
            clean_doc["file_path"] = clean_key
            clean_doc["file_hash"] = compute_hash(data)
            clean_doc["transformed_at"] = datetime.now(timezone.utc).isoformat()
            mongo.upsert(config.mongo_clean_collection, identifier, clean_doc)
            stats["transformed"] += 1
        except Exception as exc:
            stats["failed"] += 1
            log.warning("transform_failed", identifier=identifier, error=str(exc))

    log.info("transform_summary", start=start, end=end, **stats)
    mongo.close()
    return stats


def _iso_date(value):
    datetime.strptime(value, "%Y-%m-%d")  # raise on a bad format
    return value


def main():
    configure_json_logging()
    parser = argparse.ArgumentParser(description="Transform landing-zone data into the clean zone.")
    parser.add_argument("--start", required=True, type=_iso_date, help="start date YYYY-MM-DD (inclusive)")
    parser.add_argument("--end", required=True, type=_iso_date, help="end date YYYY-MM-DD (exclusive)")
    args = parser.parse_args()
    transform(args.start, args.end)


if __name__ == "__main__":
    main()
