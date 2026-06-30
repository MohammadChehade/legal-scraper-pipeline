import scrapy


class DecisionItem(scrapy.Item):
    # Which tribunal this record came from.
    body = scrapy.Field()

    # The case reference shown on the site used as the identifier.
    identifier = scrapy.Field()

    # Free-text parties/title, e.g. "Muzammal Abbas v Royal Thai Cuisine Limited".
    description = scrapy.Field()

    published_date = scrapy.Field()

    # Start of the monthly window this record was scraped under.
    partition_date = scrapy.Field()

    # URL of the document or HTML detail page for this record.
    doc_url = scrapy.Field()

    # "html", "pdf", or "doc", decided from the doc_url extension.
    doc_type = scrapy.Field()

    # Storage fields, populated by the pipeline.
    file_path = scrapy.Field()
    file_hash = scrapy.Field()
    scraped_at = scrapy.Field()
