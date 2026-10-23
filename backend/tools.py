"""ORION storage: validated CRUD for tasks and the daily schedule, persisted to
JSON files with atomic writes."""

import json
import os
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

# Set ORION_DATA_DIR to a persistent disk when deploying (otherwise data
# resets whenever the host recreates its filesystem).
DATA_DIR = Path(
    os.environ.get("ORION_DATA_DIR")
    or Path(__file__).resolve().parent.parent / "data"
)
TASKS_FILE = DATA_DIR / "tasks.json"
SCHEDULE_FILE = DATA_DIR / "schedule.json"

MAX_TITLE = 200
MAX_DEADLINE = 100
MAX_EVENT_NAME = 100
MAX_EVENTS = 50
MIN_EVENT_MINUTES, MAX_EVENT_MINUTES = 5, 480
VALID_PRIORITIES = ("High", "Medium", "Low")

DEFAULT_TASKS = [
    {"id": 1, "title": "DBMS Assignment", "deadline": "Tomorrow",
     "priority": "High", "completed": False},
    {"id": 2, "title": "AI Presentation", "deadline": "Friday",
     "priority": "Medium", "completed": False},
    {"id": 3, "title": "DSA Practice", "deadline": "This Week",
     "priority": "Medium", "completed": False},
]

# Starter timetable; edit it from the UI or with the add_event / remove_event
# MCP tools. Durations are in minutes.
DEFAULT_SCHEDULE = [
    {"id": 1, "time": "10:00 AM", "event": "DBMS Class", "duration": 60},
    {"id": 2, "time": "2:00 PM", "event": "AI Lab", "duration": 60},
]


# =========================
# PERSISTENCE
# =========================

def _write_json(path: Path, data) -> None:
    """Write atomically so a crash can never leave a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=4)
        os.replace(tmp_path, path)
    except BaseException:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def _load_list(path: Path, defaults: list, keep) -> list:
    """Load a JSON list. A corrupt file is backed up (never silently
    overwritten) before falling back to the defaults."""
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(saved, list):
                return [item for item in saved if isinstance(item, dict) and keep(item)]
        except (json.JSONDecodeError, OSError):
            pass
        try:
            shutil.copy(path, path.with_suffix(".json.corrupt"))
            print(f"Warning: {path.name} unreadable; backed up as .corrupt")
        except OSError:
            pass

    initial = [item.copy() for item in defaults]
    _write_json(path, initial)
    return initial


def save_tasks():
    _write_json(TASKS_FILE, tasks)


def save_schedule():
    _write_json(SCHEDULE_FILE, schedule)


def load_tasks() -> list:
    loaded = _load_list(TASKS_FILE, DEFAULT_TASKS,
                        lambda t: "id" in t and "title" in t)
    for item in loaded:
        item.setdefault("deadline", "Not specified")
        item.setdefault("priority", "Medium")
        item.setdefault("completed", False)
    return loaded


def load_schedule() -> list:
    loaded = _load_list(SCHEDULE_FILE, DEFAULT_SCHEDULE,
                        lambda e: "id" in e and "time" in e and "event" in e)
    for item in loaded:
        item.setdefault("duration", 60)
    return sorted(loaded, key=_event_minutes)


tasks = []
schedule = []


def _event_minutes(event: dict) -> int:
    try:
        parsed = datetime.strptime(str(event.get("time")), "%I:%M %p")
        return parsed.hour * 60 + parsed.minute
    except ValueError:
        return 24 * 60


tasks[:] = load_tasks()
schedule[:] = load_schedule()


# =========================
# TASKS
# =========================

def _clean_fields(title, deadline, priority):
    """Return (error_dict, None) or (None, (title, deadline, priority))."""
    title = str(title or "").strip()
    deadline = str(deadline or "").strip() or "Not specified"
    priority = str(priority or "").strip().capitalize()

    if not title:
        return {"success": False, "message": "Task title cannot be empty."}, None
    if len(title) > MAX_TITLE:
        return {"success": False,
                "message": f"Title must be {MAX_TITLE} characters or fewer."}, None
    if len(deadline) > MAX_DEADLINE:
        return {"success": False,
                "message": f"Deadline must be {MAX_DEADLINE} characters or fewer."}, None
    if priority not in VALID_PRIORITIES:
        return {"success": False,
                "message": "Priority must be High, Medium, or Low."}, None
    return None, (title, deadline, priority)


def _find(task_id: int):
    for task in tasks:
        if task.get("id") == task_id:
            return task
    return None


def add_task(title: str, deadline: str, priority: str) -> dict:
    error, fields = _clean_fields(title, deadline, priority)
    if error:
        return error
    title, deadline, priority = fields

    new_task = {
        "id": max((t.get("id", 0) for t in tasks), default=0) + 1,
        "title": title,
        "deadline": deadline,
        "priority": priority,
        "completed": False,
    }
    tasks.append(new_task)

    try:
        save_tasks()
    except OSError as err:
        tasks.remove(new_task)
        return {"success": False, "message": f"Could not save task: {err}"}

    return {"success": True,
            "message": f"Task '{title}' added successfully.",
            "task": new_task.copy()}


def edit_task(task_id: int, title: str, deadline: str, priority: str) -> dict:
    error, fields = _clean_fields(title, deadline, priority)
    if error:
        return error
    title, deadline, priority = fields

    task = _find(task_id)
    if task is None:
        return {"success": False, "message": "Task not found."}

    old = {k: task[k] for k in ("title", "deadline", "priority")}
    task.update(title=title, deadline=deadline, priority=priority)

    try:
        save_tasks()
    except OSError as err:
        task.update(old)
        return {"success": False, "message": f"Could not save changes: {err}"}

    return {"success": True,
            "message": f"Task '{title}' updated successfully.",
            "task": task.copy()}


def _set_completed(task_id: int, completed: bool) -> dict:
    task = _find(task_id)
    if task is None:
        return {"success": False, "message": "Task not found."}

    if task.get("completed", False) == completed:
        state = "completed" if completed else "pending"
        return {"success": True, "message": f'{task["title"]} is already {state}.'}

    task["completed"] = completed
    try:
        save_tasks()
    except OSError as err:
        task["completed"] = not completed
        return {"success": False, "message": f"Could not save task: {err}"}

    message = (f'{task["title"]} marked as completed.' if completed
               else f'{task["title"]} reopened.')
    return {"success": True, "message": message}


def mark_task_completed(task_id: int) -> dict:
    return _set_completed(task_id, True)


def reopen_task(task_id: int) -> dict:
    return _set_completed(task_id, False)


def delete_task(task_id: int) -> dict:
    for index, task in enumerate(tasks):
        if task.get("id") == task_id:
            removed = tasks.pop(index)
            try:
                save_tasks()
            except OSError as err:
                tasks.insert(index, removed)
                return {"success": False, "message": f"Could not delete task: {err}"}
            return {"success": True,
                    "message": f"Task '{removed['title']}' deleted successfully."}
    return {"success": False, "message": "Task not found."}


# =========================
# SCHEDULE
# =========================

_TIME_RE = re.compile(r"^\s*(\d{1,2})(?::([0-5]\d))?\s*(am|pm)?\s*$", re.IGNORECASE)


def normalize_time(text):
    """'2pm', '2:30 pm', '14:30' -> '2:30 PM'. Returns None if invalid."""
    match = _TIME_RE.match(str(text or ""))
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2) or 0)
    meridiem = (match.group(3) or "").upper()
    if meridiem:
        if not 1 <= hour <= 12:
            return None
    else:  # 24-hour clock
        if hour > 23:
            return None
        meridiem = "PM" if hour >= 12 else "AM"
        hour = hour % 12 or 12
    return f"{hour}:{minute:02d} {meridiem}"


def add_event(time: str, name: str, duration: int = 60) -> dict:
    """Add a fixed event (class, lab, appointment) that plans must avoid."""
    normalized = normalize_time(time)
    name = str(name or "").strip()

    if normalized is None:
        return {"success": False,
                "message": "Time must look like '2:30 PM', '2pm' or '14:30'."}
    if not name:
        return {"success": False, "message": "Event name cannot be empty."}
    if len(name) > MAX_EVENT_NAME:
        return {"success": False,
                "message": f"Event name must be {MAX_EVENT_NAME} characters or fewer."}
    try:
        duration = int(duration)
    except (TypeError, ValueError):
        return {"success": False, "message": "Duration must be a number of minutes."}
    if not MIN_EVENT_MINUTES <= duration <= MAX_EVENT_MINUTES:
        return {"success": False,
                "message": f"Duration must be {MIN_EVENT_MINUTES}-{MAX_EVENT_MINUTES} minutes."}
    if len(schedule) >= MAX_EVENTS:
        return {"success": False, "message": f"At most {MAX_EVENTS} events are allowed."}

    event = {
        "id": max((e.get("id", 0) for e in schedule), default=0) + 1,
        "time": normalized,
        "event": name,
        "duration": duration,
    }
    snapshot = list(schedule)
    schedule.append(event)
    schedule.sort(key=_event_minutes)

    try:
        save_schedule()
    except OSError as err:
        schedule[:] = snapshot
        return {"success": False, "message": f"Could not save event: {err}"}

    return {"success": True,
            "message": f"Added {name} at {normalized} for {duration} minutes.",
            "event": event.copy()}


def delete_event(event_id: int) -> dict:
    for index, event in enumerate(schedule):
        if event.get("id") == event_id:
            removed = schedule.pop(index)
            try:
                save_schedule()
            except OSError as err:
                schedule.insert(index, removed)
                return {"success": False, "message": f"Could not delete event: {err}"}
            return {"success": True,
                    "message": f"Removed {removed['event']} at {removed['time']}."}
    return {"success": False, "message": "Event not found."}
