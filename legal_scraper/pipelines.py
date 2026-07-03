"""Store each record: the file goes to MinIO, the metadata to Mongo."""

from datetime import datetime, timezone

import structlog
from scrapy.exceptions import DropItem

from legal_scraper.config import get_settings
from legal_scraper.storage.minio_store import MinioStore, compute_hash
from legal_scraper.storage.mongo import MongoStore

# doc_type -> the Content-Type we tag the stored object with.
CONTENT_TYPES = {
    "html": "text/html",
    "pdf": "application/pdf",
    "doc": "application/msword",
}


class StoragePipeline:
    def open_spider(self, spider):
        config = get_settings()
        self.collection = config.mongo_landing_collection
        self.bucket = config.minio_landing_bucket
        self.mongo = MongoStore(config.mongo_uri, config.mongo_database)
        self.mongo.ensure_identifier_index(self.collection)
        self.minio = MinioStore(
            config.minio_endpoint,
            config.minio_access_key,
            config.minio_secret_key,
            config.minio_region,
        )
        self.minio.ensure_bucket(self.bucket)

    def close_spider(self, spider):
        self.mongo.close()

    def process_item(self, item, spider):
        try:
            content = item.get("content")
            if content is not None:
                ext = item.get("doc_type") or "html"
                key = self._file_key(item, ext)
                item["file_hash"] = compute_hash(content)
                item["file_path"] = key
                item["scraped_at"] = datetime.now(timezone.utc).isoformat()
                # Hash comparison detects changes between runs: skip the upload
                # when the stored record already has these bytes, overwrite otherwise.
                existing = self.mongo.find_by_identifier(self.collection, item["identifier"])
                if not existing or existing.get("file_hash") != item["file_hash"]:
                    content_type = CONTENT_TYPES.get(ext, "application/octet-stream")
                    self.minio.upload(self.bucket, key, content, content_type)

            # Write metadata keyed on identifier, minus the raw bytes.
            document = {k: v for k, v in item.items() if k != "content"}
            self.mongo.upsert(self.collection, item["identifier"], document)
        except Exception as exc:
            structlog.get_logger().error(
                "store_failed", identifier=item.get("identifier"), error=str(exc)
            )
            spider.count_failed(item)
            raise DropItem(f"store failed for {item.get('identifier')}") from exc
        finally:
            if "content" in item:
                del item["content"]

        spider.count_scraped(item)
        return item

    @staticmethod
    def _file_key(item, ext):
        # e.g.:workplace-relations-commission/2024-01-01/ADJ-....html
        body_slug = item["body"].lower().replace(" ", "-")
        return f"{body_slug}/{item['partition_date']}/{item['identifier']}.{ext}"
