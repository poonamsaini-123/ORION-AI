import json

import pytest

import clock
import tools


@pytest.mark.parametrize("text,expected", [
    ("2pm", "2:00 PM"), ("2:30 pm", "2:30 PM"), ("14:30", "2:30 PM"),
    ("9", "9:00 AM"), ("12 am", "12:00 AM"), ("12:15 PM", "12:15 PM"),
    ("0:30", "12:30 AM"),
])
def test_normalize_time_accepts_common_forms(text, expected):
    assert tools.normalize_time(text) == expected


@pytest.mark.parametrize("text", ["", "noon", "25:00", "13 pm", "0 am", "2:75", None])
def test_normalize_time_rejects_garbage(text):
    assert tools.normalize_time(text) is None


def test_add_event_keeps_schedule_sorted_and_persisted():
    assert tools.add_event("8am", "Gym", 45)["success"]
    assert [e["time"] for e in tools.schedule] == ["8:00 AM", "10:00 AM", "2:00 PM"]
    saved = json.loads(tools.SCHEDULE_FILE.read_text())
    assert [e["event"] for e in saved] == ["Gym", "DBMS Class", "AI Lab"]
    assert tools.load_schedule()[0]["event"] == "Gym"


def test_add_event_validation():
    assert not tools.add_event("lunchtime", "x")["success"]
    assert not tools.add_event("1pm", "  ")["success"]
    assert not tools.add_event("1pm", "x" * 101)["success"]
    assert not tools.add_event("1pm", "x", 4)["success"]
    assert not tools.add_event("1pm", "x", 481)["success"]
    assert not tools.add_event("1pm", "x", "soon")["success"]


def test_delete_event():
    assert tools.delete_event(1)["success"]
    assert [e["event"] for e in tools.schedule] == ["AI Lab"]
    assert not tools.delete_event(1)["success"]


def test_event_limit():
    for i in range(tools.MAX_EVENTS - len(tools.schedule)):
        assert tools.add_event("3pm", f"e{i}")["success"]
    assert not tools.add_event("3pm", "one too many")["success"]


def test_clock_follows_orion_tz(monkeypatch):
    monkeypatch.setenv("ORION_TZ", "Asia/Kolkata")
    kolkata = clock.now()
    monkeypatch.setenv("ORION_TZ", "UTC")
    utc = clock.now()
    delta = (kolkata - utc).total_seconds()
    assert 5.4 * 3600 < delta < 5.6 * 3600      # IST = UTC+5:30


def test_clock_falls_back_on_unknown_zone(monkeypatch):
    monkeypatch.setenv("ORION_TZ", "Not/AZone")
    assert clock.now() is not None
