"""Scripted MCP client for recording ORION's demo video.

Connects to ORION over Streamable HTTP exactly as an agent such as Alexa+ would,
lists the tools, then makes real tool calls. It cleans up after itself, so you
can run it as many times as you like.

    python demo/mcp_demo.py                              # local server
    python demo/mcp_demo.py https://your-app.onrender.com/mcp
"""

import asyncio
import json
import sys

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000/mcp"

BOLD, DIM, CYAN, GREEN, YELLOW, RED, RESET = (
    "\033[1m", "\033[2m", "\033[36m", "\033[32m", "\033[33m", "\033[31m", "\033[0m")


def title(text):
    print(f"\n{BOLD}{CYAN}== {text}{RESET}")


def data(result):
    """Decode a tool result into Python objects (one JSON block per item)."""
    items = []
    for block in result.content:
        if block.type == "text":
            try:
                items.append(json.loads(block.text))
            except json.JSONDecodeError:
                items.append(block.text)
    return items


async def call(session, tool_name, **arguments):
    shown = ", ".join(f"{k}={v!r}" for k, v in arguments.items())
    print(f"{DIM}-> tools/call {tool_name}({shown}){RESET}")
    return data(await session.call_tool(tool_name, arguments=arguments))


def root_cause(error):
    """Unwrap ExceptionGroups so the user sees the real problem."""
    while getattr(error, "exceptions", None):
        error = error.exceptions[0]
    return error


async def main():
    async with streamablehttp_client(URL) as (read, write, _):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            title("Connected")
            print(f"server   : {init.serverInfo.name}")
            print(f"protocol : {init.protocolVersion}   (Streamable HTTP)")
            print(f"url      : {URL}")

            title("Tools the agent can use")
            for tool in (await session.list_tools()).tools:
                ann = tool.annotations
                if ann and ann.destructiveHint:
                    badge = f"{RED}destructive{RESET}"
                elif ann and ann.readOnlyHint:
                    badge = f"{GREEN}read-only  {RESET}"
                else:
                    badge = f"{YELLOW}writes      {RESET}"
                print(f"  {badge} {tool.name}")

            resources = (await session.list_resources()).resources
            prompts = (await session.list_prompts()).prompts
            print(f"\n  resources: {', '.join(str(r.uri) for r in resources)}")
            print(f"  prompts  : {', '.join(p.name for p in prompts)}")

            title('"Good morning, what is going on today?"')
            briefing = (await call(session, "get_daily_briefing"))[0]
            print(f"{BOLD}spoken:{RESET} {briefing['spoken']}")

            title('"I have 45 minutes right now. What should I do?"')
            now = (await call(session, "what_should_i_do_now", available_minutes=45))[0]
            print(f"{BOLD}spoken:{RESET} {now['spoken']}")

            title('"I have a physics lab at 9 am for two hours, plan an hour from 9."')
            added = (await call(session, "add_event", time="9am",
                                name="Physics Lab", duration_minutes=120))[0]
            print(f"{GREEN}{added['message']}{RESET}")
            plan = await call(session, "create_study_plan",
                              available_minutes=60, start_hour=9)
            for block in plan:
                print(f"  {block['start_time']} -> {block['end_time']}  {block['task']}"
                      f"  {DIM}({block['reason']}){RESET}")
            print(f"{DIM}  (nothing before 11:00 AM: the plan avoids the lab){RESET}")

            title('"Remind me to submit the lab report, high priority, Friday."')
            task = (await call(session, "create_task", title="Submit lab report",
                               deadline="Friday", priority="High"))[0]
            print(f"{GREEN}{task['message']}{RESET}")
            pending = await call(session, "get_tasks", status="pending")
            print(f"  pending tasks: {', '.join(t['title'] for t in pending)}")

            title("Cleaning up the demo data")
            print(f"  {(await call(session, 'remove_event', event_id=added['event']['id']))[0]['message']}")
            print(f"  {(await call(session, 'remove_task', task_id=task['task']['id']))[0]['message']}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as error:  # connection refused, wrong URL, ...
        print(f"\n{RED}Could not talk to ORION at {URL}: {root_cause(error)}{RESET}")
        print("Is the server running? (cd backend && python server.py)")
        sys.exit(1)
