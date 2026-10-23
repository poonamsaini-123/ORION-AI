"""ORION server: REST API + web UI + MCP endpoint in one process.

The web UI deliberately calls ORION *through its own MCP server*, so the MCP
tools are the single source of truth for every client (UI, Alexa+, inspectors).
"""

import asyncio
import contextlib
import json
import os
import traceback
from pathlib import Path

from fastapi import FastAPI, Path as PathParam, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from pydantic import BaseModel, Field

from agent import extract_start_time, extract_time, format_minutes
from briefing import polish_for_voice, spoken_plan
from mcp_server import mcp

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8000"))
# How the REST layer reaches the MCP server (loopback to this same process).
MCP_URL = os.environ.get("MCP_URL", f"http://127.0.0.1:{PORT}/mcp/")
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

VERSION = "1.0.0"


# =========================
# MCP CLIENT HELPERS
# =========================

class BackendError(Exception):
    """ORION could not complete a call to its MCP server."""


@contextlib.asynccontextmanager
async def mcp_session():
    try:
        async with streamablehttp_client(MCP_URL) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session
    except Exception as error:
        traceback.print_exc()
        raise BackendError("ORION could not reach its MCP server.") from error


async def call_tool(name: str, arguments: dict | None = None):
    async with mcp_session() as session:
        return await session.call_tool(name, arguments=arguments or {})


def parse_items(result) -> list:
    """Extract dict items from a tool result (list tools return one JSON text
    block per item; dict tools return a single block)."""
    items = []
    for block in result.content:
        if block.type != "text":
            continue
        try:
            parsed = json.loads(block.text)
            while isinstance(parsed, str):
                parsed = json.loads(parsed)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(parsed, dict):
            items.append(parsed)
        elif isinstance(parsed, list):
            items.extend(v for v in parsed if isinstance(v, dict))
    return items


def parse_dict(result) -> dict:
    if result.isError:
        text = next((b.text for b in result.content if b.type == "text"), "Tool error.")
        return {"success": False, "message": text}
    items = parse_items(result)
    return items[0] if items else {"success": False,
                                   "message": "Could not parse MCP response."}


# =========================
# APPLICATION
# =========================

mcp_app = mcp.streamable_http_app()


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    async with mcp.session_manager.run():
        yield


app = FastAPI(
    title="ORION API",
    version=VERSION,
    description="Context-aware task management and study planning, "
                "built on the Model Context Protocol.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["mcp-session-id"],
)


class MCPPathMiddleware:
    """Serve the MCP endpoint at both /mcp and /mcp/ (clients differ)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"] == "/mcp":
            scope = dict(scope, path="/mcp/", raw_path=b"/mcp/")
        await self.app(scope, receive, send)


app.add_middleware(MCPPathMiddleware)


@app.exception_handler(BackendError)
async def backend_error_handler(request: Request, error: BackendError):
    return JSONResponse(status_code=502,
                        content={"success": False, "message": str(error)})


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, error: RequestValidationError):
    first = error.errors()[0] if error.errors() else {}
    field = str(first["loc"][-1]) if first.get("loc") else ""
    message = f"Invalid {field or 'input'}: {first.get('msg', 'bad value')}"
    return JSONResponse(status_code=422,
                        content={"success": False, "message": message})


# =========================
# REQUEST MODELS
# =========================

class PlanRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=1000)


class TaskIdRequest(BaseModel):
    task_id: int = Field(gt=0)


class AddTaskRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    deadline: str = Field(default="Not specified", max_length=100)
    priority: str = "Medium"


class EditTaskRequest(AddTaskRequest):
    task_id: int = Field(gt=0)


class AddEventRequest(BaseModel):
    time: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=100)
    duration_minutes: int = Field(default=60, ge=5, le=480)


def summarize(text: str, limit: int = 170) -> str:
    """First paragraph of a docstring, whitespace-collapsed and trimmed."""
    first = " ".join((text or "").split("\n\n")[0].split())
    return first if len(first) <= limit else first[:limit].rsplit(" ", 1)[0] + "…"


# =========================
# ENDPOINTS
# =========================

@app.get("/health")
def health():
    return {"status": "ok", "service": "ORION", "version": VERSION,
            "mcp_endpoint": "/mcp"}


@app.get("/tasks")
async def list_tasks():
    result = await call_tool("get_tasks")
    task_list = parse_items(result)
    completed = sum(1 for t in task_list if t.get("completed", False))
    return {"success": True, "tasks": task_list, "total": len(task_list),
            "completed": completed, "pending": len(task_list) - completed}


@app.post("/plan")
async def generate_plan(request: PlanRequest):
    minutes = extract_time(request.prompt)
    start = extract_start_time(request.prompt)

    result = await call_tool("create_study_plan", {
        "available_minutes": minutes,
        "start_hour": start // 60,
        "start_minute": start % 60,
    })
    plan = parse_items(result)

    has_pending = any(not t.get("completed") for t in parse_items(await call_tool("get_tasks")))
    spoken, polished = await asyncio.to_thread(
        polish_for_voice, spoken_plan(plan, has_pending=has_pending))
    return {
        "success": True,
        "response": plan,
        "spoken": spoken,
        "polished": polished,
        "available_minutes": minutes,
        "start_time": format_minutes(start),
        "source": "MCP create_study_plan",
    }


@app.get("/schedule")
async def get_schedule():
    events = parse_items(await call_tool("get_schedule"))
    return {"success": True, "events": events}


@app.post("/add-event")
async def add_event_endpoint(request: AddEventRequest):
    return parse_dict(await call_tool("add_event", request.model_dump()))


@app.delete("/delete-event/{event_id}")
async def delete_event_endpoint(event_id: int = PathParam(gt=0)):
    return parse_dict(await call_tool("remove_event", {"event_id": event_id}))


@app.get("/briefing")
async def briefing():
    result = await call_tool("get_daily_briefing", {"voice_polish": True})
    data = parse_dict(result)
    return {"success": True, **data} if data.get("success", True) else data


@app.get("/mcp-tools")
async def mcp_tools():
    async with mcp_session() as session:
        listing = await session.list_tools()
    return {
        "success": True,
        "tools": [
            {
                "name": tool.name,
                "description": summarize(tool.description),
                "read_only": bool(tool.annotations and tool.annotations.readOnlyHint),
                "destructive": bool(tool.annotations and tool.annotations.destructiveHint),
            }
            for tool in listing.tools
        ],
    }


@app.post("/add-task")
async def add_task_endpoint(request: AddTaskRequest):
    return parse_dict(await call_tool("create_task", request.model_dump()))


@app.put("/edit-task")
async def edit_task_endpoint(request: EditTaskRequest):
    return parse_dict(await call_tool("update_task", request.model_dump()))


@app.post("/complete-task")
async def complete_task_endpoint(request: TaskIdRequest):
    return parse_dict(await call_tool("complete_task", {"task_id": request.task_id}))


@app.post("/reopen-task")
async def reopen_task_endpoint(request: TaskIdRequest):
    return parse_dict(await call_tool("reopen_task", {"task_id": request.task_id}))


@app.delete("/delete-task/{task_id}")
async def delete_task_endpoint(task_id: int = PathParam(gt=0)):
    return parse_dict(await call_tool("remove_task", {"task_id": task_id}))


class RevalidatingStaticFiles(StaticFiles):
    """Static files the browser must revalidate on every load, so an old cached
    script.js can never be paired with a newer index.html (or vice versa)."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


# =========================
# MOUNT MCP + FRONTEND (static must be last)
# =========================

app.mount("/mcp", mcp_app)
app.mount("/", RevalidatingStaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT)
