"""Dagster orchestration: ingest then transform, as two dependent assets."""

import subprocess
import sys
from pathlib import Path

from dagster import Config, Definitions, asset

from legal_scraper.transform import transform

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class DateRange(Config):
    # Default is June 2012: Equality Tribunal + EAT + Labour Court (3 bodies).
    # WRC only exists from ~2016, so no single month has all four. For WRC, run a
    # recent range instead, e.g. start=2024-01-01 end=2024-02-01 (WRC + Labour Court).
    start: str = "2012-06-01"
    end: str = "2012-07-01"


@asset
def landing_data(context, config: DateRange) -> dict:
    # Ingest: run the scraper for the date range into the landing zone.
    # Its output is forwarded line by line into Dagster's event log, so the
    # run is followable in the UI (stdout capture is unreliable on Windows).
    context.log.info(f"scraping {config.start} to {config.end}")
    command = [
        sys.executable, "-m", "scrapy", "crawl", "decisions",
        "-a", f"start={config.start}",
        "-a", f"end={config.end}",
    ]
    process = subprocess.Popen(
        command, cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
    for line in process.stdout:
        if line.strip():
            context.log.info(line.rstrip())
    if process.wait() != 0:
        raise subprocess.CalledProcessError(process.returncode, command)
    return {"start": config.start, "end": config.end}


@asset
def clean_data(context, landing_data: dict) -> dict:
    # Transform: clean the landing data into the clean zone. Depends on
    # landing_data, so Dagster only runs this after the ingest succeeds.
    stats = transform(landing_data["start"], landing_data["end"])
    context.add_output_metadata(stats)
    context.log.info(f"transformed {stats}")
    return stats


defs = Definitions(assets=[landing_data, clean_data])
