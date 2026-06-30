"""Spider for the WRC Decisions and Determinations search.

It walks each tribunal (body) across monthly partitions of a date range, reads
the search listing pages, and yields one DecisionItem per record.
"""

import math
import re
from datetime import datetime
from urllib.parse import urlencode, urlparse

import scrapy

from legal_scraper.config import get_settings
from legal_scraper.items import DecisionItem
from legal_scraper.partitions import iter_partitions


class DecisionsSpider(scrapy.Spider):
    name = "decisions"

    # Site body id -> its corresponding name.
    BODIES = {
        "1": "Equality Tribunal",
        "2": "Employment Appeals Tribunal",
        "3": "Labour Court",
        "15376": "Workplace Relations Commission",
    }

    def __init__(self, start=None, end=None, bodies=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.config = get_settings()
        self.start_date = self._parse_date(start, "start")
        self.end_date = self._parse_date(end, "end")
        # Optional -a bodies=15376,3 restricts the run to specific tribunals.
        if bodies:
            wanted = {b.strip() for b in bodies.split(",")}
            self.body_ids = [b for b in self.BODIES if b in wanted]
        else:
            self.body_ids = list(self.BODIES)

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
            if total:
                last_page = math.ceil(total / page_size)
                for next_page in range(2, last_page + 1):
                    yield scrapy.Request(
                        self._build_url(body_id, partition, next_page),
                        callback=self.parse,
                        cb_kwargs={"body_id": body_id, "partition": partition, "page": next_page},
                    )

        for card in cards:
            yield self._parse_card(card, response, body_name, partition)

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
        # The listing says "...of 233 results"; whitespace varies, so be lenient.
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
