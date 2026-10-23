"""Time source. Servers usually run in UTC, so set ORION_TZ (an IANA name such
as 'Asia/Kolkata') to make greetings, 'now' and deadlines follow the user's day."""

import os
from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def now() -> datetime:
    """Current local time as a naive datetime in ORION_TZ (or the system zone)."""
    name = os.environ.get("ORION_TZ", "").strip()
    if name:
        try:
            return datetime.now(ZoneInfo(name)).replace(tzinfo=None)
        except (ZoneInfoNotFoundError, ValueError):
            print(f"Warning: unknown ORION_TZ '{name}', using system time.")
    return datetime.now()


def today() -> date:
    return now().date()
