"""Tests for the spider's pure helper methods.

These are the parts of the spider that need no network: argument validation,
file-type routing, and reading the result count out of a listing page.
Each test prints what it proved (visible because pytest runs with -s).
"""

from types import SimpleNamespace

import pytest

from legal_scraper.spiders.decisions import DecisionsSpider


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
