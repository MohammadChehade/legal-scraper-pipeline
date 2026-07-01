"""Scrapy framework settings.

These are the knobs Scrapy itself reads. We pull it from the typed config so there is a single source .
"""

from legal_scraper.config import get_settings

config = get_settings()

BOT_NAME = "legal_scraper"

SPIDER_MODULES = ["legal_scraper.spiders"]
NEWSPIDER_MODULE = "legal_scraper.spiders"

# Identify the crawler and respect the site's robots rules.
USER_AGENT = config.user_agent
ROBOTSTXT_OBEY = True

CONCURRENT_REQUESTS = config.concurrent_requests
DOWNLOAD_DELAY = config.download_delay

RETRY_ENABLED = True
RETRY_TIMES = config.retry_times

# AutoThrottle adapts the delay to the server's responsiveness.
AUTOTHROTTLE_ENABLED = config.autothrottle_enabled

# Use the asyncio-based reactor
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"

FEED_EXPORT_ENCODING = "utf-8"

# Send every scraped item through the storage pipeline (file to MinIO, metadata to Mongo).
ITEM_PIPELINES = {
    "legal_scraper.pipelines.StoragePipeline": 300,
}
