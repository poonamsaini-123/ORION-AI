"""Spoken-style summaries for voice assistants such as Alexa+.

`build_briefing` and `spoken_plan` are deterministic. `polish_for_voice`
optionally rewrites the text with Amazon Bedrock when ORION_BEDROCK_MODEL_ID is
set; any failure falls back to the original text, so ORION never depends on AWS.
"""

import os
import re
from datetime import datetime

import clock
from agent import (
    PRIORITY_RANK,
    days_until,
    parse_schedule_minutes,
    urgency_bucket,
)


def _greeting(now: datetime) -> str:
    if now.hour < 12:
        return "morning"
    if now.hour < 17:
        return "afternoon"
    return "evening"


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def build_briefing(task_list, schedule_data, now: datetime | None = None) -> dict:
    now = now or clock.now()
    today = now.date()

    pending = [t for t in task_list if not t.get("completed", False)]
    completed = len(task_list) - len(pending)
    dated = [(t, days_until(t.get("deadline"), today)) for t in pending]

    overdue = [t["title"] for t, d in dated if d is not None and d < 0]
    due_today = [t["title"] for t, d in dated if d == 0]
    due_soon = [t["title"] for t, d in dated if d is not None and 1 <= d <= 2]

    ranked = sorted(
        dated,
        key=lambda pair: (urgency_bucket(pair[1]),
                          PRIORITY_RANK.get(pair[0].get("priority"), 3)),
    )
    top = ranked[0][0] if ranked else None

    minute_now = now.hour * 60 + now.minute
    next_event = None
    for event in schedule_data or []:
        if "free time" in str(event.get("event", "")).lower():
            continue
        start = parse_schedule_minutes(event.get("time", ""))
        if start is not None and start >= minute_now:
            if next_event is None or start < next_event[0]:
                next_event = (start, {"event": event["event"], "time": event["time"]})

    parts = [f"Good {_greeting(now)}."]
    if not pending:
        parts.append("You have no pending tasks.")
        if completed:
            parts.append(f"You've completed {_plural(completed, 'task')}.")
    else:
        parts.append(f"You have {_plural(len(pending), 'pending task')}.")
        if overdue:
            parts.append(f"Overdue: {', '.join(overdue)}.")
        if due_today:
            parts.append(f"Due today: {', '.join(due_today)}.")
        if due_soon:
            parts.append(f"Coming up soon: {', '.join(due_soon)}.")
        if top:
            parts.append(
                f"Your top priority is {top['title']}, due "
                f"{top.get('deadline', 'soon')}, "
                f"{str(top.get('priority', 'medium')).lower()} priority."
            )
    if next_event:
        parts.append(f"Next on your schedule: {next_event[1]['event']} "
                     f"at {next_event[1]['time']}.")

    total = len(task_list)
    return {
        "spoken": " ".join(parts),
        "pending": len(pending),
        "completed": completed,
        "progress_percent": round(100 * completed / total) if total else 0,
        "overdue": overdue,
        "due_today": due_today,
        "due_soon": due_soon,
        "top_task": top,
        "next_event": next_event[1] if next_event else None,
    }


def spoken_plan(plan: list, has_pending: bool = False) -> str:
    if not plan:
        if has_pending:
            return ("There is no free time left in that window to schedule your "
                    "tasks. Try a different start time or a longer window.")
        return "You have nothing pending, so there is no plan to build."

    total = sum(item["time"] for item in plan)
    sentences = [f"Here is your plan. {_plural(len(plan), 'block')}, "
                 f"{total} minutes in total."]
    for index, item in enumerate(plan):
        lead = "First" if index == 0 else "Then"
        sentences.append(
            f"{lead}, {item['task']}, from {item['start_time']} to {item['end_time']}."
        )
    return " ".join(sentences)


_POLISH_PROMPT = (
    "Rewrite the message below as a short, friendly spoken reply for a voice "
    "assistant (at most 3 sentences). Keep every task name, number and time "
    "exactly as written and add no new facts.\n\nMessage:\n{text}"
)


def polish_for_voice(text: str) -> tuple[str, bool]:
    """Return (text, polished). Uses Amazon Bedrock only if configured."""
    model_id = os.environ.get("ORION_BEDROCK_MODEL_ID")
    if not model_id:
        return text, False

    try:
        import boto3  # optional dependency

        client = boto3.client(
            "bedrock-runtime",
            region_name=os.environ.get("AWS_REGION")
            or os.environ.get("AWS_DEFAULT_REGION")
            or "us-east-1",
        )
        response = client.converse(
            modelId=model_id,
            messages=[{"role": "user",
                       "content": [{"text": _POLISH_PROMPT.format(text=text)}]}],
            inferenceConfig={"maxTokens": 250, "temperature": 0.4},
        )
        polished = response["output"]["message"]["content"][0]["text"].strip()

        # Guard: the rewrite must keep every number from the original.
        if polished and set(re.findall(r"\d+", text)) <= set(re.findall(r"\d+", polished)):
            return polished, True
    except Exception as error:  # never let AWS problems break ORION
        print(f"Bedrock polish skipped: {error}")

    return text, False
