
import asyncio
import json
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

async def main():
    url = "http://127.0.0.1:8000/mcp"
    test_title = "ORION MCP TEST - TEMPORARY"

    async with streamablehttp_client(url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            async def call(name, args):
                result = await session.call_tool(name, args)
                if result.isError:
                    raise RuntimeError(f"{name} failed: {result.content}")
                print(f"\n{name}: {result.content}")
                return result

            # Create a test task
            await call("create_task", {
                "title": test_title,
                "deadline": "Today",
                "priority": "Low"
            })

            # Find the task and get its ID
            result = await call("get_tasks", {"status": "pending"})
            records = [
                json.loads(item.text)
                for item in result.content
                if item.type == "text"
            ]
            test_task = next(t for t in records if t["title"] == test_title)
            task_id = test_task["id"]
            print("Created task ID:", task_id)

            # Complete it and verify
            await call("complete_task", {"task_id": task_id})
            result = await call("get_tasks", {"status": "completed"})
            completed = [
                json.loads(item.text)
                for item in result.content
                if item.type == "text"
            ]
            assert any(t["id"] == task_id for t in completed)
            print("PASS: task created and marked completed")

            # Add a temporary schedule event
            await call("add_event", {
                "time": "11:45 PM",
                "name": "ORION MCP TEST EVENT",
                "duration_minutes": 5
            })

            result = await call("get_schedule", {})
            events = [
                json.loads(item.text)
                for item in result.content
                if item.type == "text"
            ]
            event = next(e for e in events if e["event"] == "ORION MCP TEST EVENT")
            await call("remove_event", {"event_id": event["id"]})
            print("PASS: event added and removed")

            # Clean up the test task
            await call("remove_task", {"task_id": task_id})
            print("\nALL LIVE MCP WRITE TESTS PASSED")

asyncio.run(main())
