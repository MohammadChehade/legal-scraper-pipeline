"""Tests for the spider's pure helper methods.

These are the parts of the spider that need no network: argument validation,
file-type routing, and reading the result count out of a listing page.
Each test prints what it proved (visible because pytest runs with -s).
"""

from types import SimpleNamespace

import pytest
from scrapy.http import HtmlResponse

from legal_scraper.spiders.decisions import DecisionsSpider


def _page(body: str) -> HtmlResponse:
    return HtmlResponse("https://x.ie/en/cases/p.html", body=body.encode(), encoding="utf-8")


def test_doc_type_from_extension():
    assert DecisionsSpider._doc_type("https://x.ie/a/b.pdf") == "pdf"
    assert DecisionsSpider._doc_type("https://x.ie/a/b.doc") == "doc"
    assert DecisionsSpider._doc_type("https://x.ie/a/b.docx") == "doc"
    assert DecisionsSpider._doc_type("https://x.ie/en/cases/2024/january/adj-1.html") == "html"
    assert DecisionsSpider._doc_type(None) is None
    print("\n  -> .pdf->pdf, .doc/.docx->doc, .html->html, None->None")


def test_doc_type_ignores_query_string_and_case():
    # Uppercase extensions and trailing query params still resolve correctly.
    result = DecisionsSpider._doc_type("https://x.ie/a/B.PDF?v=2")
    assert result == "pdf"
    assert DecisionsSpider._doc_type("https://x.ie/a/b.html") == "html"
    print(f"\n  -> 'B.PDF?v=2' routed as {result} (case and query string ignored)")


def test_parse_date_accepts_iso():
    from datetime import date

    result = DecisionsSpider._parse_date("2024-01-01", "start")
    assert result == date(2024, 1, 1)
    print(f"\n  -> '2024-01-01' parsed to {result!r}")


def test_parse_date_rejects_bad_format():
    with pytest.raises(ValueError) as exc:
        DecisionsSpider._parse_date("01/01/2024", "start")
    print(f"\n  -> bad format rejected: {exc.value}")


def test_parse_date_rejects_missing_value():
    with pytest.raises(ValueError) as exc:
        DecisionsSpider._parse_date(None, "end")
    print(f"\n  -> missing value rejected: {exc.value}")


def test_extract_total_reads_the_count():
    response = SimpleNamespace(text="blah Shows 1 to 10 of  233  results blah")
    result = DecisionsSpider._extract_total(response)
    assert result == 233
    print(f"\n  -> pulled {result} out of messy 'of  233  results' whitespace")


def test_extract_total_returns_none_when_absent():
    response = SimpleNamespace(text="no count here")
    result = DecisionsSpider._extract_total(response)
    assert result is None
    print(f"\n  -> no count in page returns {result}")


def test_attachment_url_found_on_shell_page():
    # Legacy EAT shape: empty content div, decision attached as a pdf.
    page = _page(
        '<div class="content"></div>'
        '<div class="related-items related-file">'
        '<a class="download" href="/en/eat_import/2012/06/abc.pdf">Download</a></div>'
    )
    result = DecisionsSpider._attachment_url(page)
    assert result == "/en/eat_import/2012/06/abc.pdf"
    print(f"\n  -> shell page with pdf attachment returns {result}")


def test_attachment_url_ignored_when_page_has_content():
    # A normal decision page must never be rerouted, even if a file is attached.
    page = _page(
        '<div class="content"><p>The decision text.</p></div>'
        '<div class="related-file"><a class="download" href="/x.pdf">Download</a></div>'
    )
    assert DecisionsSpider._attachment_url(page) is None
    print("\n  -> page with real content returns None (attachment ignored)")


def test_attachment_url_none_without_usable_attachment():
    # Shell with no attachment, and shell whose link is not a pdf/doc.
    assert DecisionsSpider._attachment_url(_page('<div class="content"></div>')) is None
    page = _page(
        '<div class="content"></div>'
        '<div class="related-file"><a class="download" href="/other.html">x</a></div>'
    )
    assert DecisionsSpider._attachment_url(page) is None
    print("\n  -> shell without a pdf/doc attachment falls back to storing the page")
