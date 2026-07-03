# Legal Scraper Pipeline

A Scrapy pipeline that scrapes legal decisions and metadata from Ireland's
[Workplace Relations Commission](https://www.workplacerelations.ie/) decisions database,
stores the raw documents and metadata (the landing zone), and transforms them into a
cleaned copy (the clean zone). Orchestrated with Dagster.

## What it does

1. Scrapes the four decision bodies (Workplace Relations Commission, Labour Court,
   Equality Tribunal, Employment Appeals Tribunal) over a date range, one monthly
   partition at a time, stamping every record with its `partition_date`.
2. Stores each record's metadata in MongoDB and its document file in MinIO, with the file
   path and a SHA-256 hash on every metadata record.
3. Transforms the landing data into a clean zone: HTML pages are stripped to the decision
   body, files are renamed to `identifier.ext`, and everything is written to a new bucket
   and collection. The landing zone is never modified.

Re-runs are idempotent: the same date range never creates duplicate records or
re-downloads files it already has.

## Prerequisites

- Docker and Docker Compose (for MongoDB and MinIO)
- [uv](https://docs.astral.sh/uv/)
- Python 3.12+

## Setup

```bash
cp .env.example .env          # copy the config template (adjust if needed)
uv sync                       # install dependencies
docker compose up -d          # start MongoDB + MinIO
```

Optional web UI for Mongo:

```bash
docker compose --profile tools up -d mongo-express
```

## Running the pipeline

### With Dagster (recommended)

```bash
uv run dagster dev
```

Open http://localhost:3000, go to Assets, and click "Materialize all" to run scrape then
transform for the default date range. To use a different range, open the launchpad, click
"Scaffold missing config", and edit `start` / `end`.

### From the command line

```bash
# Scrape into the landing zone (all four bodies)
uv run scrapy crawl decisions -a start=2024-01-01 -a end=2024-02-01

# Optionally restrict to specific bodies (ids: WRC 15376, Labour Court 3, Equality 1, EAT 2)
uv run scrapy crawl decisions -a start=2024-01-01 -a end=2024-02-01 -a bodies=15376,3

# Transform the landing data into the clean zone
uv run python -m legal_scraper.transform --start 2024-01-01 --end 2024-02-01
```

Dates are `YYYY-MM-DD`. `start` is inclusive, `end` is exclusive, so a full year is
`2024-01-01` to `2025-01-01`.

## Seeing the data

- Mongo (metadata): http://localhost:8081 (mongo-express) - `landing_metadata` and
  `clean_metadata`
- MinIO (files): http://localhost:9001 - `landing-zone` and `clean-zone` buckets
- Dagster (runs and logs): http://localhost:3000

## Configuration

All connection strings, bucket and collection names, the target search URL, the partition
size (`PARTITION_MONTHS`), and the scraping parameters (concurrency, delay, retries) come
from environment variables (see `.env.example`). Nothing is hardcoded in the logic.

## Tests

```bash
uv run pytest                 # fast offline tests
uv run pytest --integration   # also runs the live scrape/transform tests (needs Docker + internet)
```

## The four bodies

WRC and Labour Court issue decisions today; the Equality Tribunal and EAT were wound down
around 2015, so they only have older data. No single month has all four. To demonstrate
all four, run two ranges:

- Older (Equality Tribunal + EAT + Labour Court): `2012-06-01` to `2012-07-01`
- Recent (WRC + Labour Court): `2024-01-01` to `2024-02-01`
