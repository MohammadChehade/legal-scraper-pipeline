"""Spider for the WRC Decisions and Determinations search.

It walks each tribunal (body) across monthly partitions of a date range, reads
the search listing pages, and yields one DecisionItem per record.
"""

import math
import re
from collections import defaultdict
from datetime import datetime
from urllib.parse import urlencode, urlparse

import scrapy
import structlog

from legal_scraper.config import get_settings
from legal_scraper.items import DecisionItem
from legal_scraper.logging_config import configure_json_logging
from legal_scraper.partitions import iter_partitions
from legal_scraper.storage.mongo import MongoStore


class DecisionsSpider(scrapy.Spider):
    name = "decisions"

    # Site body id -> its corresponding name.
    BODIES = {
        "1": "Equality Tribunal",
        "2": "Employment Appeals Tribunal",
        "3": "Labour Court",
        "15376": "Workplace Relations Commission",
    }

    def __init__(self, start=None, end=None, bodies=None, refresh=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.config = get_settings()
        self.start_date = self._parse_date(start, "start")
        self.end_date = self._parse_date(end, "end")
        # -a refresh=true re-scrapes everything, bypassing the already-stored skip.
        self.refresh = str(refresh).lower() in ("1", "true", "yes")
        # Optional -a bodies=15376,3 restricts the run to specific tribunals.
        if bodies:
            wanted = {b.strip() for b in bodies.split(",")}
            self.body_ids = [b for b in self.BODIES if b in wanted]
        else:
            self.body_ids = list(self.BODIES)

        # Read-side Mongo handle for the idempotency check. Optional, so a Mongo
        # outage doesn't stop the crawl.
        try:
            self.store = MongoStore(self.config.mongo_uri, self.config.mongo_database)
        except Exception:
            self.store = None
            self.logger.warning("Mongo unreachable; the re-download skip is disabled")

        # JSON logging and per-partition counters for the run's accounting.
        configure_json_logging()
        self.log = structlog.get_logger()
        self.counts = defaultdict(lambda: {"found": 0, "scraped": 0, "failed": 0, "skipped": 0})

    @staticmethod
    def _parse_date(value, name):
        # Dates arrive as spider arguments, so validate them up front and fail
        # loudly rather than letting a bad value reach the site.
        if not value:
            raise ValueError(f"missing spider argument: {name} (use -a {name}=YYYY-MM-DD)")
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError as exc:
            raise ValueError(f"{name} must be YYYY-MM-DD, got {value!r}") from exc

    def _build_url(self, body_id, partition, page):
        # One search URL for a given body, partition window, and page number.
        params = {
            "decisions": 1,
            "from": partition.from_param,
            "to": partition.to_param,
            "body": body_id,
            "pageNumber": page,
        }
        # safe="/" keeps the dd/mm/yyyy slashes literal, as the site expects.
        return f"{self.config.wrc_search_url}?{urlencode(params, safe='/')}"

    async def start(self):
        # Fan out: every body, every partition, starting at page 1.
        partitions = iter_partitions(self.start_date, self.end_date, self.config.partition_months)
        # Log the real span actually being scraped, so an off-by-one in the date
        # range is visible at a glance rather than silently dropping a day.
        self.logger.info(
            "scraping %s to %s as %d window(s) of %d month(s) across %d body/bodies",
            partitions[0].from_param, partitions[-1].to_param,
            len(partitions), self.config.partition_months, len(self.body_ids),
        )
        for body_id in self.body_ids:
            for partition in partitions:
                yield scrapy.Request(
                    self._build_url(body_id, partition, 1),
                    callback=self.parse,
                    errback=self.on_download_error,
                    cb_kwargs={"body_id": body_id, "partition": partition, "page": 1},
                )

    def parse(self, response, body_id, partition, page):
        body_name = self.BODIES[body_id]
        cards = response.css("li.each-item")

        # On the first page only, read the total and fan out the remaining pages.
        if page == 1:
            total = self._extract_total(response)
            page_size = len(cards) or 10
            self.logger.info(
                "found %s records | body=%s partition=%s",
                total if total is not None else "?", body_name, partition.partition_date,
            )
            self.counts[self._key(partition, body_name)]["found"] = total or 0
            if total:
                last_page = math.ceil(total / page_size)
                for next_page in range(2, last_page + 1):
                    yield scrapy.Request(
                        self._build_url(body_id, partition, next_page),
                        callback=self.parse,
                        errback=self.on_download_error,
                        cb_kwargs={"body_id": body_id, "partition": partition, "page": next_page},
                    )

        for card in cards:
            item = self._parse_card(card, response, body_name, partition)
            if self._already_stored(item["identifier"]):
                self.counts[self._key(partition, body_name)]["skipped"] += 1
                continue  # already stored on a previous run: don't re-download
            if item["doc_url"]:
                # Follow the record's document link so the pipeline can store the
                # file. parse_document attaches the raw bytes and emits the item.
                yield scrapy.Request(
                    item["doc_url"],
                    callback=self.parse_document,
                    errback=self.on_download_error,
                    cb_kwargs={"item": item},
                )
            else:
                yield item

    def parse_document(self, response, item):
        # The document link has been fetched. Keep its raw bytes on the item for
        # the pipeline to hash and upload: for an HTML detail page these bytes are
        # the page itself (stored as .html); for a pdf/doc link they are the binary.
        item["content"] = response.body
        yield item

    def _already_stored(self, identifier):
        # True if a previous run already saved this record.
        if self.refresh or not self.store or not identifier:
            return False
        return self.store.find_by_identifier(self.config.mongo_landing_collection, identifier) is not None

    @staticmethod
    def _key(partition, body_name):
        # Counter key: one bucket per partition window and body.
        return f"{partition.partition_date}|{body_name}"

    @staticmethod
    def _item_key(item):
        return f"{item['partition_date']}|{item['body']}"

    def on_download_error(self, failure):
        # A request failed after retries. Log it with its URL and HTTP status,
        # and count a document failure so the record is accounted for.
        request = failure.request
        response = getattr(failure.value, "response", None)
        status = getattr(response, "status", None)
        item = request.cb_kwargs.get("item")
        if item is not None:
            self.counts[self._item_key(item)]["failed"] += 1
            self.log.warning(
                "download_failed", url=request.url, status=status,
                error=str(failure.value), identifier=item.get("identifier"),
            )
        else:
            self.log.warning("listing_failed", url=request.url, status=status, error=str(failure.value))

    def count_scraped(self, item):
        self.counts[self._item_key(item)]["scraped"] += 1

    def count_failed(self, item):
        self.counts[self._item_key(item)]["failed"] += 1

    def closed(self, reason):
        # Scrapy calls this when the crawl ends. Emit a JSON summary per partition
        # and one for the whole run, flagging any records we couldn't account for.
        totals = {"found": 0, "scraped": 0, "failed": 0, "skipped": 0}
        for key, counts in self.counts.items():
            partition, body = key.split("|", 1)
            missing = max(0, counts["found"] - counts["scraped"] - counts["failed"] - counts["skipped"])
            self.log.info("partition_summary", partition=partition, body=body, missing=missing, **counts)
            if missing:
                self.log.warning("records_unaccounted", partition=partition, body=body, missing=missing)
            for name in totals:
                totals[name] += counts[name]
        total_missing = max(0, totals["found"] - totals["scraped"] - totals["failed"] - totals["skipped"])
        self.log.info("run_summary", reason=reason, missing=total_missing, **totals)
        if self.store:
            self.store.close()

    def _parse_card(self, card, response, body_name, partition):
        href = card.css("h2.title a::attr(href)").get()
        identifier = card.css("h2.title a::text").get() or card.css(".refNO::text").get()
        doc_url = response.urljoin(href) if href else None

        item = DecisionItem()
        item["body"] = body_name
        item["identifier"] = identifier.strip() if identifier else None
        item["description"] = card.css("p.description::text").get(default="").strip()
        item["published_date"] = card.css("span.date::text").get(default="").strip()
        item["partition_date"] = partition.partition_date
        item["doc_url"] = doc_url
        item["doc_type"] = self._doc_type(doc_url)
        return item

    @staticmethod
    def _extract_total(response):
        # regex to find the total number of results in the search page text.
        match = re.search(r"of\s+(\d+)\s+results", response.text, re.IGNORECASE)
        return int(match.group(1)) if match else None

    @staticmethod
    def _doc_type(url):
        # Decide how the file will be handled later from its extension.
        if not url:
            return None
        path = urlparse(url).path.lower()
        if path.endswith(".pdf"):
            return "pdf"
        if path.endswith((".doc", ".docx")):
            return "doc"
        return "html"
