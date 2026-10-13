"""
Google's daily quota resets at midnight Pacific time (America/Los_Angeles).

On Windows Python has no time-zone database of its own: it comes from the
``tzdata`` package. If that is missing (an old or broken install), the US
daylight-saving rule is applied by hand, so the reset time stays right all
year instead of failing.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone, tzinfo

_PST = timezone(timedelta(hours=-8), "PST")
_PDT = timezone(timedelta(hours=-7), "PDT")


def _nth_sunday(year: int, month: int, n: int) -> datetime:
    first = datetime(year, month, 1)
    to_sunday = (6 - first.weekday()) % 7
    return first + timedelta(days=to_sunday + 7 * (n - 1))


def _manual_offset(now_utc: datetime) -> timezone:
    """US rule since 2007: DST from the 2nd Sunday of March, 02:00 local
    (10:00 UTC), to the 1st Sunday of November, 02:00 local (09:00 UTC)."""
    year = now_utc.year
    start = _nth_sunday(year, 3, 2).replace(hour=10, tzinfo=UTC)
    end = _nth_sunday(year, 11, 1).replace(hour=9, tzinfo=UTC)
    return _PDT if start <= now_utc < end else _PST


def pacific_zone() -> tzinfo | None:
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo("America/Los_Angeles")
    except Exception:
        return None


def to_pacific(now_utc: datetime | None = None) -> datetime:
    now = (now_utc or datetime.now(UTC)).astimezone(UTC)
    zone = pacific_zone()
    return now.astimezone(zone if zone is not None else _manual_offset(now))
