"""ORION's MCP server: tools, resources and prompts for agents such as Alexa+.

Transport: Streamable HTTP (mounted at /mcp by server.py).
"""

import json
import os

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations

import clock
import tools
from agent import MAX_AVAILABLE_MINUTES, create_plan
from briefing import build_briefing, polish_for_voice, spoken_plan
from tools import schedule, tasks

HOST = os.environ.get("HOST", "127.0.0.1")

# DNS-rebinding protection rejects unknown Host headers. When deployed, list
# your public hostname(s), e.g. ORION_ALLOWED_HOSTS=orion.onrender.com
_allowed_hosts = [h.strip() for h in os.environ.get("ORION_ALLOWED_HOSTS", "").split(",")
                  if h.strip()]
if os.environ.get("RENDER_EXTERNAL_HOSTNAME"):  # set automatically on Render
    _allowed_hosts.append(os.environ["RENDER_EXTERNAL_HOSTNAME"])
_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=_allowed_hosts + ["127.0.0.1:*", "localhost:*"],
    allowed_origins=[f"https://{h}" for h in _allowed_hosts]
    + ["http://127.0.0.1:*", "http://localhost:*"],
) if _allowed_hosts else None

mcp = FastMCP(
    "ORION",
    instructions=(
        "ORION manages a student's tasks and builds deadline-aware study plans "
        "around their schedule. For voice replies prefer get_daily_briefing and "
        "what_should_i_do_now, which return a ready-to-speak 'spoken' field."
    ),
    host=HOST,
    streamable_http_path="/",
    transport_security=_security,
)

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                            idempotentHint=True, openWorldHint=False)
WRITES = ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                         idempotentHint=False, openWorldHint=False)
IDEMPOTENT_WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                   idempotentHint=True, openWorldHint=False)
DESTRUCTIVE = ToolAnnotations(readOnlyHint=False, destructiveHint=True,
                              idempotentHint=True, openWorldHint=False)


# =========================
# READ-ONLY TOOLS
# =========================

@mcp.tool(annotations=READ_ONLY)
def get_system_status() -> dict:
    """Return ORION's health and task counts."""
    pending = sum(1 for t in tasks if not t.get("completed", False))
    return {"status": "online", "tasks": len(tasks), "pending": pending}


@mcp.tool(annotations=READ_ONLY)
def get_tasks(status: str = "all") -> list:
    """List tasks. status: 'all' (default), 'pending' or 'completed'."""
    status = status.strip().lower()
    if status == "pending":
        return [t for t in tasks if not t.get("completed", False)]
    if status == "completed":
        return [t for t in tasks if t.get("completed", False)]
    return list(tasks)


@mcp.tool(annotations=READ_ONLY)
def get_schedule() -> list:
    """Return today's fixed events (classes, labs) in time order."""
    return list(schedule)


@mcp.tool(annotations=READ_ONLY)
def create_study_plan(available_minutes: int, start_hour: int = 9,
                      start_minute: int = 0) -> list:
    """Build a study plan: pending tasks ordered by deadline urgency then
    priority, in blocks of up to 60 minutes that avoid scheduled events.
    start_hour is 0-23 (default 9)."""
    minutes = max(1, min(int(available_minutes), MAX_AVAILABLE_MINUTES))
    start = max(0, min(int(start_hour), 23)) * 60 + max(0, min(int(start_minute), 59))
    return create_plan(minutes, schedule_data=schedule, start_minute=start)


@mcp.tool(annotations=READ_ONLY)
def get_daily_briefing(voice_polish: bool = False) -> dict:
    """Summarise what is overdue, due today and next on the schedule. The
    'spoken' field is ready to read aloud. voice_polish=True asks Amazon
    Bedrock (when configured) to make it sound more natural."""
    briefing = build_briefing(tasks, schedule)
    if voice_polish:
        briefing["spoken"], briefing["polished"] = polish_for_voice(briefing["spoken"])
    return briefing


@mcp.tool(annotations=READ_ONLY)
def what_should_i_do_now(available_minutes: int = 60,
                         voice_polish: bool = False) -> dict:
    """Voice-friendly: plan the time the user has *starting now*. Returns the
    plan plus a 'spoken' summary."""
    minutes = max(1, min(int(available_minutes), MAX_AVAILABLE_MINUTES))
    now = clock.now()
    start = min(((now.hour * 60 + now.minute + 4) // 5) * 5, 24 * 60 - 1)

    plan = create_plan(minutes, schedule_data=schedule, start_minute=start)
    spoken = spoken_plan(plan, has_pending=any(not t.get("completed") for t in tasks))
    result = {"plan": plan, "spoken": spoken}
    if voice_polish:
        result["spoken"], result["polished"] = polish_for_voice(spoken)
    return result


# =========================
# WRITE TOOLS
# =========================

@mcp.tool(annotations=WRITES)
def create_task(title: str, deadline: str = "Not specified",
                priority: str = "Medium") -> dict:
    """Create a task. priority: High, Medium or Low. deadline is free text such
    as 'Tomorrow', 'Friday' or '2026-10-20'."""
    return tools.add_task(title, deadline, priority)


@mcp.tool(annotations=IDEMPOTENT_WRITE)
def update_task(task_id: int, title: str, deadline: str, priority: str) -> dict:
    """Replace a task's title, deadline and priority."""
    return tools.edit_task(task_id, title, deadline, priority)


@mcp.tool(annotations=IDEMPOTENT_WRITE)
def complete_task(task_id: int) -> dict:
    """Mark a task as completed."""
    return tools.mark_task_completed(task_id)


@mcp.tool(annotations=IDEMPOTENT_WRITE)
def reopen_task(task_id: int) -> dict:
    """Mark a completed task as pending again."""
    return tools.reopen_task(task_id)


@mcp.tool(annotations=DESTRUCTIVE)
def remove_task(task_id: int) -> dict:
    """Permanently delete a task."""
    return tools.delete_task(task_id)


@mcp.tool(annotations=WRITES)
def add_event(time: str, name: str, duration_minutes: int = 60) -> dict:
    """Add a fixed event (class, lab, appointment) that study plans will avoid.
    time accepts '2:30 PM', '2pm' or '14:30'; duration is 5-480 minutes."""
    return tools.add_event(time, name, duration_minutes)


@mcp.tool(annotations=DESTRUCTIVE)
def remove_event(event_id: int) -> dict:
    """Remove an event from today's schedule."""
    return tools.delete_event(event_id)


# =========================
# RESOURCES
# =========================

@mcp.resource("orion://tasks", mime_type="application/json")
def tasks_resource() -> str:
    """All tasks as JSON."""
    return json.dumps(tasks, indent=2)


@mcp.resource("orion://schedule", mime_type="application/json")
def schedule_resource() -> str:
    """Today's fixed events as JSON."""
    return json.dumps(schedule, indent=2)


@mcp.resource("orion://briefing", mime_type="application/json")
def briefing_resource() -> str:
    """The current daily briefing as JSON."""
    return json.dumps(build_briefing(tasks, schedule), indent=2)


# =========================
# PROMPTS
# =========================

@mcp.prompt()
def plan_my_evening(hours: str = "2") -> str:
    """Ask the assistant to plan a free evening."""
    return (
        f"I have {hours} hours free this evening. Use ORION to check my tasks "
        "and schedule, build a study plan, and read it back briefly and "
        "encouragingly."
    )


@mcp.prompt()
def weekly_review() -> str:
    """Ask the assistant for a short progress review."""
    return (
        "Use ORION to review my tasks: what is done, what is overdue and what "
        "should I tackle first? Keep it under four sentences."
    )
