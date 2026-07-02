"""End-to-end scrapes against the live site, over a small date window.

These hit workplacerelations.ie, so they are integration tests, skipped by
default. Run them with:  uv run pytest --integration

They write to a throwaway db and bucket so they never touch the real landing
zone. One test checks the scraped fields; the other checks idempotency.
"""

import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

from legal_scraper.config import get_settings
from legal_scraper.storage.minio_store import MinioStore
from legal_scraper.storage.mongo import MongoStore

pytestmark = pytest.mark.integration

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEST_DB = "legal_scraper_test"
TEST_BUCKET = "test-landing-zone"


def _reset_test_stores():
    # Clear the isolated test db and bucket so a run starts clean.
    config = get_settings()
    mongo = MongoStore(config.mongo_uri, TEST_DB)
    mongo.db[config.mongo_landing_collection].delete_many({})
    mongo.close()
    minio = MinioStore(
        config.minio_endpoint, config.minio_access_key, config.minio_secret_key, config.minio_region
    )
    minio.ensure_bucket(TEST_BUCKET)
    objects = minio.client.list_objects_v2(Bucket=TEST_BUCKET).get("Contents", [])
    if objects:
        minio.client.delete_objects(
            Bucket=TEST_BUCKET, Delete={"Objects": [{"Key": o["Key"]} for o in objects]}
        )


def _landing_count():
    config = get_settings()
    mongo = MongoStore(config.mongo_uri, TEST_DB)
    count = mongo.db[config.mongo_landing_collection].count_documents({})
    mongo.close()
    return count


def _run_crawl(out_path):
    # Run the real spider for one week of WRC into the isolated stores, also
    # writing the scraped items to a feed file we can assert on.
    return subprocess.run(
        [
            sys.executable, "-m", "scrapy", "crawl", "decisions",
            "-a", "start=2024-01-01",
            "-a", "end=2024-01-08",
            "-a", "bodies=15376",
            "-O", str(out_path),
        ],
        cwd=PROJECT_ROOT,
        env={
            **os.environ,
            "MONGO_DATABASE": TEST_DB,
            "MINIO_LANDING_BUCKET": TEST_BUCKET,
        },
        capture_output=True,
        text=True,
        timeout=180,
    )


def _feed(path):
    # Read a Scrapy JSON feed, tolerating an empty file (a run that scraped nothing).
    text = path.read_text(encoding="utf-8").strip()
    return json.loads(text) if text else []


def test_live_scrape_fields(tmp_path):
    _reset_test_stores()
    out = tmp_path / "week.json"
    result = _run_crawl(out)
    assert result.returncode == 0, result.stderr[-3000:]

    data = _feed(out)
    ids = [d["identifier"] for d in data]
    assert len(data) > 0, "expected at least one record for the week"
    assert all(ids), "every record must have an identifier"
    assert len(set(ids)) == len(ids), "no duplicate identifiers"
    assert all(d["doc_url"].startswith("http") for d in data), "links must be absolute"
    assert all(d["partition_date"] == "2024-01-01" for d in data), "wrong partition stamp"

    types = Counter(d["doc_type"] for d in data)
    print(f"\n  -> scraped {len(data)} records; doc_types {dict(types)}; sample {ids[0]}")


def test_scrape_is_idempotent(tmp_path):
    _reset_test_stores()

    first = _run_crawl(tmp_path / "run1.json")
    assert first.returncode == 0, first.stderr[-3000:]
    scraped_first = len(_feed(tmp_path / "run1.json"))
    count_first = _landing_count()
    assert scraped_first > 0, "first run should scrape records"
    assert count_first == scraped_first, "stored count should match what was scraped"

    # Second run over the same range, WITHOUT resetting in between.
    second = _run_crawl(tmp_path / "run2.json")
    assert second.returncode == 0, second.stderr[-3000:]
    scraped_second = len(_feed(tmp_path / "run2.json"))
    count_second = _landing_count()

    assert scraped_second == 0, "second run re-scraped instead of skipping already-stored records"
    assert count_second == count_first, "second run created duplicate records"
    print(
        f"\n  -> idempotent: run1 stored {count_first}, "
        f"run2 scraped {scraped_second}, total still {count_second}"
    )
