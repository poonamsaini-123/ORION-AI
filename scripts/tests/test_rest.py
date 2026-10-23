"""End-to-end: start the real server in a subprocess and call it over HTTP."""

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent / "backend"
INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                   "clientInfo": {"name": "test", "version": "1"}}}


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def base_url():
    port = _free_port()
    env = {**os.environ, "PORT": str(port),
           "ORION_DATA_DIR": tempfile.mkdtemp(prefix="orion-e2e-")}
    proc = subprocess.Popen([sys.executable, "server.py"], cwd=BACKEND, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    for _ in range(60):
        try:
            urllib.request.urlopen(url + "/health", timeout=1)
            break
        except OSError:
            time.sleep(0.25)
    else:
        proc.kill()
        pytest.fail("server did not start")
    yield url
    proc.terminate()
    proc.wait(timeout=10)


def call(base, path, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read())


def test_health_and_ui(base_url):
    assert call(base_url, "/health")[1]["status"] == "ok"
    assert urllib.request.urlopen(base_url + "/").status == 200
    for asset in ("/", "/script.js", "/style.css"):
        assert urllib.request.urlopen(base_url + asset).headers["Cache-Control"] == "no-cache"


def test_task_lifecycle(base_url):
    _, added = call(base_url, "/add-task", "POST",
                    {"title": "E2E", "deadline": "Friday", "priority": "High"})
    task_id = added["task"]["id"]
    assert call(base_url, "/complete-task", "POST", {"task_id": task_id})[1]["success"]
    assert call(base_url, "/reopen-task", "POST", {"task_id": task_id})[1]["success"]
    assert call(base_url, "/edit-task", "PUT", {"task_id": task_id, "title": "E2E 2",
                "deadline": "Monday", "priority": "Low"})[1]["task"]["title"] == "E2E 2"
    assert call(base_url, f"/delete-task/{task_id}", "DELETE")[1]["success"]


def test_validation_errors_are_json(base_url):
    status, body = call(base_url, "/add-task", "POST", {"title": "", "priority": "High"})
    assert status == 422 and body["success"] is False and "title" in body["message"]
    status, body = call(base_url, "/add-task", "POST", {"title": "x", "priority": "Urgent"})
    assert body["success"] is False


def test_plan_briefing_and_tool_catalog(base_url):
    _, plan = call(base_url, "/plan", "POST", {"prompt": "I have 1.5 hours from 4:30 pm"})
    assert plan["available_minutes"] == 90 and plan["start_time"] == "4:30 PM"
    assert sum(b["time"] for b in plan["response"]) == 90 and plan["spoken"]
    assert call(base_url, "/briefing")[1]["spoken"].startswith("Good ")
    names = {t["name"] for t in call(base_url, "/mcp-tools")[1]["tools"]}
    assert {"create_study_plan", "get_daily_briefing"} <= names


def test_schedule_endpoints(base_url):
    assert len(call(base_url, "/schedule")[1]["events"]) == 2
    status, bad = call(base_url, "/add-event", "POST", {"time": "25:99", "name": "x"})
    assert bad["success"] is False
    _, added = call(base_url, "/add-event", "POST",
                    {"time": "4pm", "name": "Gym", "duration_minutes": 45})
    assert added["event"]["time"] == "4:00 PM"
    assert call(base_url, f"/delete-event/{added['event']['id']}", "DELETE")[1]["success"]
    assert call(base_url, "/delete-event/0", "DELETE")[0] == 422


def test_demo_client_runs_against_the_server_and_cleans_up(base_url):
    demo = BACKEND.parent / "demo" / "mcp_demo.py"
    before = call(base_url, "/tasks")[1]["total"], len(call(base_url, "/schedule")[1]["events"])
    run = subprocess.run([sys.executable, str(demo), base_url + "/mcp"],
                         capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "2025-11-25" in run.stdout and "Cleaning up" in run.stdout
    after = call(base_url, "/tasks")[1]["total"], len(call(base_url, "/schedule")[1]["events"])
    assert before == after


@pytest.mark.parametrize("path", ["/mcp", "/mcp/"])
def test_mcp_endpoint_works_with_and_without_trailing_slash(base_url, path):
    req = urllib.request.Request(
        base_url + path, data=json.dumps(INIT).encode(), method="POST",
        headers={"Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        assert resp.status == 200
        assert "ORION" in resp.read().decode()