"""Unit tests for time and duration formatting utilities."""

from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

from pricewatch.utils.time_utils import (
    format_duration,
    format_ist_datetime,
    format_relative_time,
    to_ist,
)


def test_to_ist_conversion():
    utc_dt = datetime(2026, 10, 26, 10, 53, 0, tzinfo=timezone.utc)
    ist_dt = to_ist(utc_dt)
    assert ist_dt.hour == 16
    assert ist_dt.minute == 23


def test_format_ist_datetime():
    dt = datetime(2026, 10, 26, 10, 53, 0, tzinfo=timezone.utc)
    formatted = format_ist_datetime(dt)
    assert formatted == "26-10-2026, 04:23 PM"


def test_format_relative_time():
    now = datetime(2026, 10, 26, 12, 0, 0, tzinfo=timezone.utc)
    
    sec_ago = now - timedelta(seconds=20)
    assert format_relative_time(sec_ago, base_dt=now) == "a few seconds ago"

    min_ago = now - timedelta(seconds=70)
    assert format_relative_time(min_ago, base_dt=now) == "a minute ago"

    mins_ago = now - timedelta(minutes=5)
    assert format_relative_time(mins_ago, base_dt=now) == "5 minutes ago"

    hour_ago = now - timedelta(hours=1, minutes=10)
    assert format_relative_time(hour_ago, base_dt=now) == "an hour ago"

    hours_ago = now - timedelta(hours=3)
    assert format_relative_time(hours_ago, base_dt=now) == "3 hours ago"

    day_ago = now - timedelta(days=1)
    assert format_relative_time(day_ago, base_dt=now) == "a day ago"

    days_ago = now - timedelta(days=2)
    assert format_relative_time(days_ago, base_dt=now) == "2 days ago"


def test_format_duration():
    start = datetime(2026, 10, 25, 0, 0, 0, tzinfo=timezone.utc)
    end_day = datetime(2026, 10, 26, 0, 0, 0, tzinfo=timezone.utc)
    assert format_duration(start, end_day) == "a day"

    end_mins = datetime(2026, 10, 25, 0, 45, 0, tzinfo=timezone.utc)
    assert format_duration(start, end_mins) == "45 minutes"

    end_hrs = datetime(2026, 10, 25, 2, 0, 0, tzinfo=timezone.utc)
    assert format_duration(start, end_hrs) == "2 hours"
