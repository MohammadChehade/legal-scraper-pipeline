"""Tests for the date-partition iterator.

This is pure date logic with no network, so we can pin down every edge: window
counts, the half-open end boundary, month-end clamping, and the guard clauses.
Each test prints what it proved (visible because pytest runs with -s).
"""

from datetime import date, timedelta

import pytest

from legal_scraper.partitions import Partition, _add_months, iter_partitions


def test_full_year_monthly_gives_twelve_windows():
    windows = iter_partitions(date(2024, 1, 1), date(2025, 1, 1), 1)
    assert len(windows) == 12
    assert windows[0].start == date(2024, 1, 1)
    assert windows[0].end == date(2024, 1, 31)
    assert windows[-1].start == date(2024, 12, 1)
    assert windows[-1].end == date(2024, 12, 31)
    print(
        f"\n  -> 2024 split into {len(windows)} monthly windows; "
        f"first {windows[0].from_param}-{windows[0].to_param}, "
        f"last {windows[-1].from_param}-{windows[-1].to_param}"
    )


def test_full_year_quarterly_gives_four_windows():
    windows = iter_partitions(date(2024, 1, 1), date(2025, 1, 1), 3)
    assert len(windows) == 4
    assert windows[0].end == date(2024, 3, 31)
    assert windows[-1].end == date(2024, 12, 31)
    print(f"\n  -> quarterly gives {len(windows)} windows ending {[w.to_param for w in windows]}")


def test_windows_never_overlap():
    # Each window must start the day after the previous one ends.
    windows = iter_partitions(date(2024, 1, 1), date(2025, 1, 1), 1)
    for earlier, later in zip(windows, windows[1:]):
        assert later.start == earlier.end + timedelta(days=1)
    print(f"\n  -> checked {len(windows)} windows: each starts the day after the previous ends")


def test_end_is_exclusive():
    # end = 31 Jan means the last scraped day is 30 Jan, not 31 Jan.
    windows = iter_partitions(date(2024, 1, 1), date(2024, 1, 31), 1)
    assert len(windows) == 1
    assert windows[0].end == date(2024, 1, 30)
    print(f"\n  -> end=31/01 is exclusive, last day scraped is {windows[0].to_param} (31st dropped)")


def test_end_one_day_later_includes_the_last_day():
    # end = 1 Feb is how you ask for all of January.
    windows = iter_partitions(date(2024, 1, 1), date(2024, 2, 1), 1)
    assert windows[0].end == date(2024, 1, 31)
    print(f"\n  -> end=01/02 includes the 31st, last day scraped is {windows[0].to_param}")


def test_leap_year_month_end_clamps_to_29_feb():
    # 31 Jan + 1 month has no 31 Feb, so it clamps to the real month end.
    result = _add_months(date(2024, 1, 31), 1)
    assert result == date(2024, 2, 29)
    print(f"\n  -> 31 Jan 2024 + 1 month clamps to {result} (leap year)")


def test_non_leap_year_month_end_clamps_to_28_feb():
    result = _add_months(date(2023, 1, 31), 1)
    assert result == date(2023, 2, 28)
    print(f"\n  -> 31 Jan 2023 + 1 month clamps to {result} (non-leap year)")


def test_partition_formats_for_the_url_and_record():
    part = Partition(start=date(2024, 1, 1), end=date(2024, 1, 31))
    assert part.from_param == "01/01/2024"
    assert part.to_param == "31/01/2024"
    assert part.partition_date == "2024-01-01"
    print(
        f"\n  -> formatting: from={part.from_param} to={part.to_param} "
        f"partition_date={part.partition_date}"
    )


def test_zero_months_is_rejected():
    with pytest.raises(ValueError) as exc:
        iter_partitions(date(2024, 1, 1), date(2025, 1, 1), 0)
    print(f"\n  -> zero months rejected: {exc.value}")


def test_start_not_before_end_is_rejected():
    with pytest.raises(ValueError) as exc:
        iter_partitions(date(2025, 1, 1), date(2024, 1, 1), 1)
    print(f"\n  -> start not before end rejected: {exc.value}")
