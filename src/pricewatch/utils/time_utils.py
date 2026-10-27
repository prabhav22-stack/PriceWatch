"""Time and duration formatting utilities for PriceWatch and Amul stock history.

Matches the formatting and timezone conventions of upstream amul-notify (Asia/Kolkata / IST).
"""

from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

IST_TZ = ZoneInfo("Asia/Kolkata")


def to_ist(dt: datetime) -> datetime:
    """Ensure datetime has timezone and convert to Asia/Kolkata."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST_TZ)


def format_ist_datetime(dt: datetime) -> str:
    """
    Format datetime into 'DD-MM-YYYY, hh:mm A' in Asia/Kolkata (IST).
    Example: '26-10-2026, 04:23 PM'
    """
    return to_ist(dt).strftime("%d-%m-%Y, %I:%M %p")


def format_relative_time(dt: datetime, base_dt: Optional[datetime] = None) -> str:
    """
    Format relative time like dayjs().fromNow(), e.g. 'a few seconds ago', '2 minutes ago',
    '3 hours ago', 'yesterday', '2 days ago', 'a month ago'.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if not base_dt:
        base_dt = datetime.now(timezone.utc)
    elif base_dt.tzinfo is None:
        base_dt = base_dt.replace(tzinfo=timezone.utc)

    diff = base_dt - dt
    total_seconds = int(diff.total_seconds())
    if total_seconds < 0:
        total_seconds = 0

    if total_seconds < 45:
        return "a few seconds ago"
    elif total_seconds < 90:
        return "a minute ago"
    elif total_seconds <= 45 * 60:
        mins = max(1, round(total_seconds / 60))
        return f"{mins} minutes ago"
    elif total_seconds < 90 * 60:
        return "an hour ago"
    elif total_seconds < 22 * 3600:
        hrs = max(1, round(total_seconds / 3600))
        return f"{hrs} hours ago"
    elif total_seconds < 36 * 3600:
        return "a day ago"
    elif total_seconds < 25 * 86400:
        days = max(1, round(total_seconds / 86400))
        return f"{days} days ago"
    elif total_seconds < 45 * 86400:
        return "a month ago"
    elif total_seconds < 345 * 86400:
        months = max(1, round(total_seconds / (30 * 86400)))
        return f"{months} months ago"
    else:
        years = max(1, round(total_seconds / (365 * 86400)))
        return f"{years} years ago" if years > 1 else "a year ago"


def format_duration(start_dt: datetime, end_dt: datetime) -> str:
    """
    Format time difference between two dates without 'ago' suffix,
    matching dayjs(start).from(end, true), e.g. 'a day', '45 minutes', '2 hours'.
    """
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=timezone.utc)
    if end_dt.tzinfo is None:
        end_dt = end_dt.replace(tzinfo=timezone.utc)

    diff = abs(end_dt - start_dt)
    total_seconds = int(diff.total_seconds())

    if total_seconds < 45:
        return "a few seconds"
    elif total_seconds < 90:
        return "a minute"
    elif total_seconds <= 45 * 60:
        mins = max(1, round(total_seconds / 60))
        return f"{mins} minutes"
    elif total_seconds < 90 * 60:
        return "an hour"
    elif total_seconds < 22 * 3600:
        hrs = max(1, round(total_seconds / 3600))
        return f"{hrs} hours"
    elif total_seconds < 36 * 3600:
        return "a day"
    elif total_seconds < 25 * 86400:
        days = max(1, round(total_seconds / 86400))
        return f"{days} days"
    elif total_seconds < 45 * 86400:
        return "a month"
    elif total_seconds < 345 * 86400:
        months = max(1, round(total_seconds / (30 * 86400)))
        return f"{months} months"
    else:
        years = max(1, round(total_seconds / (365 * 86400)))
        return f"{years} years" if years > 1 else "a year"
