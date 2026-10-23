import json

import tools


def test_add_task_validates_input():
    assert not tools.add_task("", "Today", "High")["success"]
    assert not tools.add_task("x" * 201, "Today", "High")["success"]
    assert not tools.add_task("ok", "d" * 101, "High")["success"]
    assert not tools.add_task("ok", "Today", "Urgent")["success"]
    result = tools.add_task("  Write essay ", "", "high")
    assert result["success"]
    assert result["task"]["title"] == "Write essay"
    assert result["task"]["priority"] == "High"
    assert result["task"]["deadline"] == "Not specified"


def test_ids_increase_and_persist():
    first = tools.add_task("A", "Today", "Low")["task"]["id"]
    second = tools.add_task("B", "Today", "Low")["task"]["id"]
    assert second == first + 1
    assert [t["title"] for t in tools.load_tasks()][-2:] == ["A", "B"]


def test_complete_reopen_cycle():
    assert tools.mark_task_completed(1)["message"].endswith("marked as completed.")
    assert tools.mark_task_completed(1)["message"].endswith("already completed.")
    assert tools.reopen_task(1)["message"].endswith("reopened.")
    assert tools.reopen_task(1)["message"].endswith("already pending.")
    assert not tools.mark_task_completed(999)["success"]


def test_edit_and_delete():
    assert tools.edit_task(1, "New title", "Friday", "Low")["task"]["title"] == "New title"
    assert not tools.edit_task(999, "x", "y", "Low")["success"]
    assert not tools.edit_task(1, "", "y", "Low")["success"]
    assert tools.delete_task(1)["success"]
    assert not tools.delete_task(1)["success"]


def test_corrupt_file_is_backed_up_not_lost():
    tools.TASKS_FILE.write_text("{ not json", encoding="utf-8")
    loaded = tools.load_tasks()
    assert [t["id"] for t in loaded] == [1, 2, 3]
    assert tools.TASKS_FILE.with_suffix(".json.corrupt").read_text() == "{ not json"


def test_atomic_save_leaves_no_temp_files():
    tools.add_task("A", "Today", "Low")
    assert not list(tools.DATA_DIR.glob("*.tmp"))
    assert isinstance(json.loads(tools.TASKS_FILE.read_text()), list)
