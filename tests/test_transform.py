"""Tests for the landing -> clean transformation."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from legal_scraper.config import get_settings
from legal_scraper.storage.minio_store import MinioStore
from legal_scraper.storage.mongo import MongoStore
from legal_scraper.transform import clean_html

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEST_DB = "legal_scraper_test"
TEST_LANDING_BUCKET = "test-landing-zone"
TEST_CLEAN_BUCKET = "test-clean-zone"

SAMPLE_PAGE = b"""
<html><head><style>.x{color:red}</style></head><body>
<header>WRC site header</header>
<nav>Return to Search</nav>
<div class="content">
  <h1>ADJUDICATION OFFICER DECISION</h1>
  <p>ADJ-00099999 the decision body text</p>
  <script>tracking()</script>
</div>
<footer>site footer links</footer>
</body></html>
"""


def test_clean_html_keeps_content_drops_chrome():
    cleaned = clean_html(SAMPLE_PAGE).decode()
    # content kept
    assert "ADJUDICATION OFFICER DECISION" in cleaned
    assert "the decision body text" in cleaned
    # chrome and scripts dropped
    assert "site header" not in cleaned
    assert "Return to Search" not in cleaned
    assert "site footer" not in cleaned
    assert "tracking()" not in cleaned
    print(f"\n  -> cleaned to {len(cleaned)} chars; content kept, chrome/script removed")


def _reset_test_stores():
    config = get_settings()
    mongo = MongoStore(config.mongo_uri, TEST_DB)
    mongo.db[config.mongo_landing_collection].delete_many({})
    mongo.db[config.mongo_clean_collection].delete_many({})
    mongo.close()
    minio = MinioStore(
        config.minio_endpoint, config.minio_access_key, config.minio_secret_key, config.minio_region
    )
    for bucket in (TEST_LANDING_BUCKET, TEST_CLEAN_BUCKET):
        minio.ensure_bucket(bucket)
        objects = minio.client.list_objects_v2(Bucket=bucket).get("Contents", [])
        if objects:
            minio.client.delete_objects(
                Bucket=bucket, Delete={"Objects": [{"Key": o["Key"]} for o in objects]}
            )


def _bucket_totals(minio, bucket):
    objects = minio.client.list_objects_v2(Bucket=bucket).get("Contents", [])
    return len(objects), sum(o["Size"] for o in objects)


@pytest.mark.integration
def test_transform_end_to_end(tmp_path):
    _reset_test_stores()
    env = {
        **os.environ,
        "MONGO_DATABASE": TEST_DB,
        "MINIO_LANDING_BUCKET": TEST_LANDING_BUCKET,
        "MINIO_CLEAN_BUCKET": TEST_CLEAN_BUCKET,
    }

    scrape = subprocess.run(
        [sys.executable, "-m", "scrapy", "crawl", "decisions",
         "-a", "start=2024-01-01", "-a", "end=2024-01-08", "-a", "bodies=15376",
         "-O", str(tmp_path / "week.json")],
        cwd=PROJECT_ROOT, env=env, capture_output=True, text=True, timeout=180,
    )
    assert scrape.returncode == 0, scrape.stderr[-3000:]

    result = subprocess.run(
        [sys.executable, "-m", "legal_scraper.transform", "--start", "2024-01-01", "--end", "2024-01-08"],
        cwd=PROJECT_ROOT, env=env, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr[-3000:]

    config = get_settings()
    mongo = MongoStore(config.mongo_uri, TEST_DB)
    landing_n = mongo.db[config.mongo_landing_collection].count_documents({})
    clean_n = mongo.db[config.mongo_clean_collection].count_documents({})
    mongo.close()
    minio = MinioStore(
        config.minio_endpoint, config.minio_access_key, config.minio_secret_key, config.minio_region
    )
    landing_count, landing_bytes = _bucket_totals(minio, TEST_LANDING_BUCKET)
    clean_count, clean_bytes = _bucket_totals(minio, TEST_CLEAN_BUCKET)

    assert landing_n > 0, "expected records in landing"
    assert clean_n == landing_n, "every landing record should get a clean record"
    assert clean_count == landing_count, "every landing file should get a clean file"
    assert clean_bytes < landing_bytes, "cleaning should shrink the HTML (chrome removed)"
    print(
        f"\n  -> transformed {clean_n} records; "
        f"landing {landing_bytes} bytes -> clean {clean_bytes} bytes"
    )
