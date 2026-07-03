"""Dev helper: delete landing + clean data for one date range so it can be
re-scraped from scratch. Other ranges are left untouched.

Usage:  uv run python wipe_range.py START END      (YYYY-MM-DD, end exclusive)
Example: uv run python wipe_range.py 2024-01-01 2024-02-01
"""

import sys

from legal_scraper.config import get_settings
from legal_scraper.storage.minio_store import MinioStore
from legal_scraper.storage.mongo import MongoStore


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: python wipe_range.py START END  (YYYY-MM-DD, end exclusive)")
    start, end = sys.argv[1], sys.argv[2]
    config = get_settings()
    mongo = MongoStore(config.mongo_uri, config.mongo_database)
    minio = MinioStore(
        config.minio_endpoint, config.minio_access_key, config.minio_secret_key, config.minio_region
    )
    query = {"partition_date": {"$gte": start, "$lt": end}}

    for collection, bucket in (
        (config.mongo_landing_collection, config.minio_landing_bucket),
        (config.mongo_clean_collection, config.minio_clean_bucket),
    ):
        keys = [
            r["file_path"]
            for r in mongo.db[collection].find(query, {"file_path": 1})
            if r.get("file_path")
        ]
        if keys:
            minio.client.delete_objects(Bucket=bucket, Delete={"Objects": [{"Key": k} for k in keys]})
        removed = mongo.db[collection].delete_many(query).deleted_count
        print(f"{collection}: removed {removed} records and {len(keys)} files from {bucket}")
    mongo.close()


if __name__ == "__main__":
    main()
