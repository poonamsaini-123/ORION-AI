"""ORION planning logic.

Parses natural-language requests ("I have 1.5 hours from 4:30 pm") and builds a
deadline-aware plan that fits around scheduled (busy) events.
"""

import re
from datetime import date, datetime, timedelta

import clock
from tools import tasks

DEFAULT_MINUTES = 120
DEFAULT_START_MINUTE = 9 * 60      # 9:00 AM
MAX_AVAILABLE_MINUTES = 16 * 60
MAX_BLOCK = 60                     # longest single study block
MIN_BLOCK = 15                     # don't schedule slivers shorter than this
DAY_END = 24 * 60
DEFAULT_EVENT_MINUTES = 60         # scheduled events last 1 hour unless stated

PRIORITY_RANK = {"High": 1, "Medium": 2, "Low": 3}
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday",
            "friday", "saturday", "sunday"]

_NUMBER_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3,
                 "four": 4, "five": 5, "six": 6}
_NUM = r"(\d+(?:\.\d+)?|an|a|one|two|three|four|five|six)"
_HALF_HOUR = re.compile(r"\bhalf\s+(?:an?\s+)?hour\b")
_AND_A_HALF = re.compile(r"\b(?:hours?|hrs?)\s+and\s+a\s+half\b")
_HOURS = re.compile(rf"\b{_NUM}\s*(?:hours?|hrs?|h)\b")
_MINUTES = re.compile(rf"\b{_NUM}\s*(?:minutes?|mins?)\b")


def _number(token: str) -> float:
    return float(_NUMBER_WORDS.get(token, token))


# =========================
# PARSING THE REQUEST
# =========================

def extract_time(prompt: str) -> int:
    """Minutes available. Understands '2 hours', '1.5 hours', '2 hours 30
    minutes', 'half an hour', 'an hour and a half'. Defaults to 120."""
    text = prompt.lower()
    total = 0.0

    text, halves = _HALF_HOUR.subn(" ", text)
    total += 30 * halves
    if _AND_A_HALF.search(text):
        total += 30

    total += sum(_number(m.group(1)) * 60 for m in _HOURS.finditer(text))
    total += sum(_number(m.group(1)) for m in _MINUTES.finditer(text))

    if total <= 0:
        return DEFAULT_MINUTES
    return min(int(round(total)), MAX_AVAILABLE_MINUTES)


_START_12H = re.compile(r"(\d{1,2})(?::([0-5]\d))?\s*(am|pm)\b")
_START_24H = re.compile(
    r"\b(?:from|starting at|start at|at|after)\s*([01]?\d|2[0-3]):([0-5]\d)\b"
)


def extract_start_time(prompt: str) -> int:
    """Start time as minutes after midnight ('4:30 pm', 'at 16:30').
    Defaults to 9:00 AM."""
    text = prompt.lower()

    match = _START_12H.search(text)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2) or 0)
        if 1 <= hour <= 12:
            if match.group(3) == "am":
                hour = 0 if hour == 12 else hour
            else:
                hour = 12 if hour == 12 else hour + 12
            return hour * 60 + minute

    match = _START_24H.search(text)
    if match:
        return int(match.group(1)) * 60 + int(match.group(2))

    return DEFAULT_START_MINUTE


# =========================
# DEADLINES
# =========================

def days_until(deadline, today: date | None = None):
    """Days until a free-text deadline, or None if it can't be understood.
    Negative means overdue."""
    today = today or clock.today()
    text = str(deadline or "").lower().strip()

    if not text or "not specified" in text:
        return None
    if any(word in text for word in ("overdue", "yesterday", "past due")):
        return -1
    if "today" in text or "tonight" in text:
        return 0
    if "tomorrow" in text:
        return 1

    iso = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", text)
    if iso:
        try:
            return (date(*map(int, iso.groups())) - today).days
        except ValueError:
            return None

    dmy = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b", text)
    if dmy:
        day, month = int(dmy.group(1)), int(dmy.group(2))
        year = int(dmy.group(3)) if dmy.group(3) else today.year
        if year < 100:
            year += 2000
        try:
            return (date(year, month, day) - today).days
        except ValueError:
            return None

    for index, name in enumerate(WEEKDAYS):
        if re.search(rf"\b{name}\b|\b{name[:3]}\b", text):
            delta = (index - today.weekday()) % 7
            return delta + 7 if "next" in text else delta

    if "next week" in text:
        return 7 + (6 - today.weekday())
    if "this week" in text:
        return max(2, 6 - today.weekday())

    return None


def urgency_bucket(days) -> int:
    """0 overdue, 1 due today/tomorrow, 2 due within a week, 3 later/unknown."""
    if days is None:
        return 3
    if days < 0:
        return 0
    if days <= 1:
        return 1
    if days <= 7:
        return 2
    return 3


# =========================
# SCHEDULE
# =========================

def parse_schedule_minutes(time_text: str):
    """'2:00 PM' -> minutes after midnight, or None."""
    try:
        parsed = datetime.strptime(str(time_text).strip(), "%I:%M %p")
        return parsed.hour * 60 + parsed.minute
    except ValueError:
        return None


def busy_intervals(schedule_data) -> list:
    intervals = []
    for event in schedule_data or []:
        if "free time" in str(event.get("event", "")).lower():
            continue
        start = parse_schedule_minutes(event.get("time", ""))
        if start is None:
            continue
        try:
            length = int(event.get("duration", DEFAULT_EVENT_MINUTES))
        except (TypeError, ValueError):
            length = DEFAULT_EVENT_MINUTES
        intervals.append((start, start + max(length, 1)))
    return sorted(intervals)


def _skip_busy(minute: int, busy: list) -> int:
    moved = True
    while moved:
        moved = False
        for start, end in busy:
            if start <= minute < end:
                minute = end
                moved = True
    return minute


def format_minutes(minute: int) -> str:
    return (datetime(2000, 1, 1) + timedelta(minutes=minute)).strftime("%I:%M %p").lstrip("0")


# =========================
# PLANNER
# =========================

def create_plan(
    available_minutes: int,
    task_list=None,
    schedule_data=None,
    start_minute: int = DEFAULT_START_MINUTE,
    today: date | None = None,
) -> list:
    """Order pending tasks by deadline urgency, then priority, and lay them out
    in blocks of up to 60 minutes that never overlap a scheduled event."""

    task_list = tasks if task_list is None else task_list
    busy = busy_intervals(schedule_data)
    today = today or clock.today()

    def sort_key(task):
        days = days_until(task.get("deadline"), today)
        return (
            urgency_bucket(days),
            PRIORITY_RANK.get(task.get("priority"), 3),
            days if days is not None else 10_000,
        )

    pending = sorted(
        (t for t in task_list if not t.get("completed", False)),
        key=sort_key,
    )

    plan = []
    remaining = max(0, int(available_minutes))
    current = min(max(int(start_minute), 0), DAY_END)

    while pending and remaining > 0:
        current = _skip_busy(current, busy)
        if current >= DAY_END:
            break

        next_busy = min((s for s, _ in busy if s >= current), default=DAY_END)
        window = next_busy - current
        if window < MIN_BLOCK:
            current = next_busy
            continue

        block = min(MAX_BLOCK, remaining, window)
        task = pending.pop(0)
        shortened = block < min(MAX_BLOCK, remaining)

        reason = (
            f'{task.get("priority", "Low")} priority - '
            f'deadline {task.get("deadline", "Not specified")}'
        )
        if shortened:
            reason += " (shortened to fit before a scheduled event)"

        plan.append({
            "task": task["title"],
            "id": task.get("id"),
            "priority": task.get("priority", "Low"),
            "start_time": format_minutes(current),
            "time": block,
            "end_time": format_minutes(current + block),
            "reason": reason,
        })

        remaining -= block
        current += block

    return plan
