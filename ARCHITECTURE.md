# Architecture

Two stages: **scrape** raw decisions into a landing zone (MongoDB metadata + MinIO files),
then **transform** them into a cleaned clean zone. The landing zone is immutable; the
transform only reads it. Dagster orchestrates the two stages as dependent tasks
(`landing_data` then `clean_data`).

The scraper talks to the site's plain GET search endpoint (found by reverse-engineering
the ASP.NET search form), so requests are stateless and need no browser rendering, which
is the fastest and least block-prone way to crawl the site.

## Date partition size

Monthly. The scraper walks a date range one month at a time and tags every record with its
`partition_date`. Monthly is a deliberate balance: small enough that a transient failure
re-runs one month rather than a whole year and that any single search stays within a few
hundred records; large enough that per-request overhead does not dominate. It is
configurable via `PARTITION_MONTHS`, so quarterly or weekly is one env var away.

## Retries and rate limiting

Scrapy's `AutoThrottle` adapts the request delay to the server's responsiveness, on top of
a fixed `DOWNLOAD_DELAY`. Failed requests are retried (`RETRY_TIMES`) by Scrapy's retry
middleware, and `robots.txt` is obeyed. Because results come from a stateless GET endpoint,
the total result count on page one tells us how many pages exist, so pages are fetched in
parallel rather than one after another, fast without hammering the server.

## Deduplication

Three layers, keyed on the record `identifier`:

1. **No duplicate records.** Metadata is upserted into MongoDB against a unique index on
   `identifier`, so a re-run updates in place instead of inserting again.
2. **No re-downloading.** Before fetching a document, the spider checks whether that
   identifier is already stored and skips it if so.
3. **File hash.** Every file's SHA-256 is stored. When a document is re-fetched, its new
   hash is compared with the stored one: unchanged bytes are not re-uploaded, changed
   bytes overwrite the stored copy.

An integration test runs the same range twice and asserts the second run scrapes nothing
new and creates no duplicates.

## Scaling to 50+ sources

Today this is one source (one site) with four bodies that share a page template. For many
different source sites I would change:

- **Per-source adapters/config.** Each source becomes a config entry (base URL, selectors,
  date format) or a small adapter, instead of one spider. The four bodies here share a
  template so one spider suffices; separate sites would not.
- **Orchestration at scale.** Dagster partitions over (source x month) with a distributed
  executor (e.g. Kubernetes), so each cell is an independent, retryable task.
- **Async storage clients.** Move the Mongo/MinIO writes off Scrapy's reactor once write
  volume becomes the bottleneck.
- **Storage sharding.** The MinIO key is already `{source}/{date}/{identifier}`, so it
  shards cleanly by source and date; Mongo would shard by source at high volume.

## Notes

- **Legacy pages.** EAT's pre-2016 pages have no clean content container, so the transform
  keeps the full page body rather than dropping the document. Modern bodies clean to
  `div.content`.
- **PDF/DOC.** The pipeline stores PDF/DOC links as-is and HTML pages as `.html`. Every
  record observed on this source is HTML, so the binary branch is implemented but not
  exercised here.
