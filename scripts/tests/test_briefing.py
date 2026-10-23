import sys
import types
from datetime import datetime

import briefing
from agent import create_plan

NOW = datetime(2026, 10, 21, 9, 0)  # Wednesday morning
SCHEDULE = [{"time": "10:00 AM", "event": "DBMS Class"},
            {"time": "5:00 PM", "event": "Free Time"}]


def test_briefing_summarises_urgent_work():
    tasks = [
        {"id": 1, "title": "Overdue lab", "deadline": "yesterday", "priority": "Low", "completed": False},
        {"id": 2, "title": "Essay", "deadline": "today", "priority": "High", "completed": False},
        {"id": 3, "title": "Old", "deadline": "today", "priority": "High", "completed": True},
    ]
    result = briefing.build_briefing(tasks, SCHEDULE, now=NOW)
    assert result["pending"] == 2 and result["completed"] == 1
    assert result["progress_percent"] == 33
    assert result["overdue"] == ["Overdue lab"] and result["due_today"] == ["Essay"]
    assert result["top_task"]["title"] == "Overdue lab"
    assert result["next_event"] == {"event": "DBMS Class", "time": "10:00 AM"}
    assert result["spoken"].startswith("Good morning.")
    assert "Free Time" not in result["spoken"]


def test_briefing_with_nothing_pending():
    result = briefing.build_briefing([], [], now=NOW)
    assert "no pending tasks" in result["spoken"]
    assert result["progress_percent"] == 0


def test_spoken_plan():
    tasks = [{"id": 1, "title": "Essay", "deadline": "today", "priority": "High", "completed": False}]
    text = briefing.spoken_plan(create_plan(60, task_list=tasks, start_minute=16 * 60))
    assert "First, Essay, from 4:00 PM to 5:00 PM." in text
    assert "no plan" in briefing.spoken_plan([])


def _fake_boto3(reply):
    class Client:
        def converse(self, **kwargs):
            return {"output": {"message": {"content": [{"text": reply}]}}}
    module = types.ModuleType("boto3")
    module.client = lambda *a, **k: Client()
    return module


def test_polish_is_a_noop_without_bedrock_config(monkeypatch):
    monkeypatch.delenv("ORION_BEDROCK_MODEL_ID", raising=False)
    assert briefing.polish_for_voice("Hello 3") == ("Hello 3", False)


def test_polish_uses_bedrock_when_configured_and_numbers_preserved(monkeypatch):
    monkeypatch.setenv("ORION_BEDROCK_MODEL_ID", "some-model")
    monkeypatch.setitem(sys.modules, "boto3", _fake_boto3("Hey! You have 3 tasks."))
    assert briefing.polish_for_voice("You have 3 pending tasks.") == ("Hey! You have 3 tasks.", True)


def test_polish_rejects_rewrites_that_drop_numbers(monkeypatch):
    monkeypatch.setenv("ORION_BEDROCK_MODEL_ID", "some-model")
    monkeypatch.setitem(sys.modules, "boto3", _fake_boto3("Lots of work ahead!"))
    assert briefing.polish_for_voice("You have 3 pending tasks.") == ("You have 3 pending tasks.", False)
