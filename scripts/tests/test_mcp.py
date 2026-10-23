"""Protocol-level tests: talk to ORION's MCP server through a real MCP client
session (in memory, no network)."""

import asyncio
import json

from mcp.shared.memory import create_connected_server_and_client_session

from mcp_server import mcp


def run(coro_fn):
    async def wrapper():
        async with create_connected_server_and_client_session(mcp._mcp_server) as client:
            return await coro_fn(client)
    return asyncio.run(wrapper())


def texts(result):
    return [json.loads(b.text) for b in result.content if b.type == "text"]


def test_tools_are_listed_with_safety_annotations():
    async def go(client):
        return {t.name: t for t in (await client.list_tools()).tools}
    tools = run(go)

    expected = {"get_system_status", "get_tasks", "get_schedule", "create_study_plan",
                "get_daily_briefing", "what_should_i_do_now", "create_task",
                "update_task", "complete_task", "reopen_task", "remove_task"}
    assert expected <= set(tools)
    assert tools["get_tasks"].annotations.readOnlyHint is True
    assert tools["remove_task"].annotations.destructiveHint is True
    assert tools["create_task"].annotations.readOnlyHint is False


def test_create_then_complete_then_list():
    async def go(client):
        created = await client.call_tool(
            "create_task", {"title": "MCP test", "deadline": "Friday", "priority": "High"})
        task_id = texts(created)[0]["task"]["id"]
        await client.call_tool("complete_task", {"task_id": task_id})
        pending = texts(await client.call_tool("get_tasks", {"status": "pending"}))
        done = texts(await client.call_tool("get_tasks", {"status": "completed"}))
        return task_id, pending, done
    task_id, pending, done = run(go)
    assert task_id not in [t["id"] for t in pending]
    assert task_id in [t["id"] for t in done]


def test_study_plan_and_voice_tools():
    async def go(client):
        plan = texts(await client.call_tool("create_study_plan", {"available_minutes": 90}))
        now = texts(await client.call_tool("what_should_i_do_now", {"available_minutes": 45}))
        brief = texts(await client.call_tool("get_daily_briefing", {}))
        return plan, now[0], brief[0]
    plan, now, brief = run(go)
    assert sum(b["time"] for b in plan) == 90
    assert now["spoken"] and "plan" in now
    assert brief["spoken"].startswith("Good ")


def test_invalid_input_is_reported_not_raised():
    async def go(client):
        return texts(await client.call_tool(
            "create_task", {"title": "", "deadline": "x", "priority": "High"}))
    assert run(go)[0]["success"] is False


def test_resources_and_prompts():
    async def go(client):
        resources = {str(r.uri) for r in (await client.list_resources()).resources}
        data = await client.read_resource("orion://tasks")
        prompts = {p.name for p in (await client.list_prompts()).prompts}
        return resources, json.loads(data.contents[0].text), prompts
    resources, tasks, prompts = run(go)
    assert {"orion://tasks", "orion://schedule", "orion://briefing"} <= resources
    assert isinstance(tasks, list) and tasks
    assert {"plan_my_evening", "weekly_review"} <= prompts
