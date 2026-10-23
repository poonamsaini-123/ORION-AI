from datetime import date

import pytest

from agent import (
    create_plan, days_until, extract_start_time, extract_time,
    format_minutes, urgency_bucket,
)

WED = date(2026, 10, 21)  # a Wednesday


@pytest.mark.parametrize("text,expected", [
    ("I have 2 hours", 120),
    ("I have 1.5 hours", 90),
    ("2 hours 30 minutes please", 150),
    ("half an hour", 30),
    ("an hour and a half", 90),
    ("I only have 90 minutes now", 90),
    ("six hours", 360),
    ("no duration given", 120),
    ("100 hours", 16 * 60),
])
def test_extract_time(text, expected):
    assert extract_time(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("2 hours from 4:30 pm", 16 * 60 + 30),
    ("starting at 9 am", 9 * 60),
    ("at 12 am", 0),
    ("at 12 pm", 12 * 60),
    ("from 16:30", 16 * 60 + 30),
    ("just 2 hours", 9 * 60),
])
def test_extract_start_time(text, expected):
    assert extract_start_time(text) == expected


@pytest.mark.parametrize("deadline,expected", [
    ("Today", 0), ("tomorrow", 1), ("Friday", 2), ("Monday", 5),
    ("next Monday", 12), ("2026-10-25", 4), ("25/10", 4),
    ("yesterday", -1), ("Not specified", None), ("someday", None),
])
def test_days_until(deadline, expected):
    assert days_until(deadline, WED) == expected


def test_urgency_buckets():
    assert [urgency_bucket(d) for d in (-1, 0, 1, 2, 7, 8, None)] == [0, 1, 1, 2, 2, 3, 3]


def test_format_minutes_has_no_leading_zero():
    assert format_minutes(13 * 60 + 30) == "1:30 PM"
    assert format_minutes(0) == "12:00 AM"


def _task(i, title, deadline, priority, done=False):
    return {"id": i, "title": title, "deadline": deadline,
            "priority": priority, "completed": done}


def test_plan_orders_by_urgency_then_priority_and_skips_completed():
    tasks = [
        _task(1, "later high", "2026-12-01", "High"),
        _task(2, "overdue low", "yesterday", "Low"),
        _task(3, "done", "today", "High", done=True),
        _task(4, "tomorrow medium", "tomorrow", "Medium"),
    ]
    plan = create_plan(240, task_list=tasks, today=WED)
    assert [p["task"] for p in plan] == ["overdue low", "tomorrow medium", "later high"]


def test_plan_never_overlaps_scheduled_events():
    tasks = [_task(i, f"t{i}", "tomorrow", "High") for i in range(1, 6)]
    schedule = [{"time": "10:00 AM", "event": "Class"},
                {"time": "2:00 PM", "event": "Lab", "duration": 90}]
    plan = create_plan(300, task_list=tasks, schedule_data=schedule,
                       start_minute=9 * 60 + 30, today=WED)
    busy = [(600, 660), (840, 930)]

    def minutes(text):
        from agent import parse_schedule_minutes
        return parse_schedule_minutes(text)

    for block in plan:
        start, end = minutes(block["start_time"]), minutes(block["end_time"])
        assert end - start == block["time"]
        assert all(end <= b0 or start >= b1 for b0, b1 in busy), block
    assert sum(b["time"] for b in plan) <= 300
    assert plan[0]["time"] == 30 and "shortened" in plan[0]["reason"]


def test_plan_respects_available_minutes_and_end_of_day():
    tasks = [_task(i, f"t{i}", "tomorrow", "High") for i in range(1, 4)]
    assert sum(b["time"] for b in create_plan(45, task_list=tasks, today=WED)) == 45
    late = create_plan(120, task_list=tasks, start_minute=23 * 60 + 30, today=WED)
    assert sum(b["time"] for b in late) == 30  # cannot run past midnight


def test_plan_with_no_pending_tasks_is_empty():
    assert create_plan(60, task_list=[_task(1, "x", "today", "High", done=True)]) == []
