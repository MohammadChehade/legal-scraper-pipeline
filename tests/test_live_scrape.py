"""End-to-end scrape against the live site, over a small date window.

This actually hits workplacerelations.ie, so it is marked as an integration test
and is skipped by default. Run it on demand with:

    uv run pytest --integration tests/test_live_scrape.py

It runs the real spider via the command line for one week of WRC decisions and
checks the output has the shape we expect: records exist, every one has an
identifier, there are no duplicates, links are absolute, and the partition stamp
is correct. On success it prints a summary of what came back.
"""

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _scrapy_line(stderr, needle):
    # Pull a single informative line out of the spider's log for the summary.
    for line in stderr.splitlines():
        if needle in line:
            return line.split("] ", 1)[-1].strip()
    return None


def test_live_scrape_one_week(tmp_path):
    out = tmp_path / "week.json"
    result = subprocess.run(
        [
            sys.executable, "-m", "scrapy", "crawl", "decisions",
            "-a", "start=2024-01-01",
            "-a", "end=2024-01-08",  # exclusive end, so this is the week of the 1st to the 7th
            "-a", "bodies=15376",
            "-O", str(out),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stderr[-3000:]

    data = json.loads(out.read_text(encoding="utf-8"))
    ids = [d["identifier"] for d in data]

    assert len(data) > 0, "expected at least one record for the week"
    assert all(ids), "every record must have an identifier"
    assert len(set(ids)) == len(ids), "no duplicate identifiers"
    assert all(d["doc_url"].startswith("http") for d in data), "links must be absolute"
    assert all(d["partition_date"] == "2024-01-01" for d in data), "wrong partition stamp"

    types = Counter(d["doc_type"] for d in data)
    print("\n  === live scrape summary: WRC, 01-07 Jan 2024 ===")
    print(f"  records:        {len(data)} ({len(set(ids))} unique)")
    print(f"  doc_types:      {dict(types)}")
    print(f"  partition_date: {sorted(set(d['partition_date'] for d in data))}")
    found = _scrapy_line(result.stderr, "found ")
    if found:
        print(f"  spider log:     {found}")
    print("  sample records:")
    for d in data[:3]:
        print(f"    - {d['identifier']:<18} {d['published_date']}  {d['description'][:45]}")
