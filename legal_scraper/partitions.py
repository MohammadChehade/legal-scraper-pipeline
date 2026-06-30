"""Split a date range into partition windows.

This module turns a range into a list of windows; the
spider then issues one set of requests per window.

The range is treated as half-open, [start, end): start is included, end is not.
That matches the brief's example of monthly partitions "between 01-01-2024 and
01-01-2025" meaning the twelve months of 2024, with 01-01-2025 as the boundary.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class Partition:
    start: date  # first day of the window, inclusive
    end: date    # last day of the window, inclusive

    @property
    def partition_date(self) -> str:
        # Stored on every record so we know which window produced it.
        return self.start.isoformat()

    @property
    def from_param(self) -> str:
        # The site's `from` query value, dd/mm/yyyy.
        return self.start.strftime("%d/%m/%Y")

    @property
    def to_param(self) -> str:
        # The site's `to` query value, dd/mm/yyyy. Inclusive on the site.
        return self.end.strftime("%d/%m/%Y")


def _add_months(d: date, months: int) -> date:
    # Shift a date forward by whole months, clamping the day to the target
    # month's length so 31 Jan + 1 month lands on 28/29 Feb instead of erroring.
    total = d.month - 1 + months
    year = d.year + total // 12
    month = total % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def iter_partitions(start: date, end: date, months: int) -> list[Partition]:
    # Build back-to-back, non-overlapping windows covering [start, end).
    if months < 1:
        raise ValueError("partition months must be at least 1")
    if start >= end:
        raise ValueError("start date must be before end date")

    windows: list[Partition] = []
    window_start = start
    while window_start < end:
        next_start = min(_add_months(window_start, months), end)
        # The site's `to` filter is inclusive, so this window's last day is the
        # day before the next window starts. That stops windows from overlapping
        # and re-scraping boundary records.
        window_end = next_start - timedelta(days=1)
        windows.append(Partition(start=window_start, end=window_end))
        window_start = next_start
    return windows
