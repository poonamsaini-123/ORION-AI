# ORION — Intelligent Orchestration

**An MCP server that lets any voice or chat agent manage your tasks and your day, and turns "I have 90 minutes" into a deadline-aware study plan, spoken back in plain language.**

Built for the *Build, Ship, Shape: Amazon Developer Hackathon*, **Alexa+ track** (self-hosted MCP server over Streamable HTTP).

![ORION web app](docs/screenshot-desktop.png)

## Why it exists
Students juggle assignments, classes and labs, and the daily question is *"what should I work on right now, given the time I actually have?"* Task apps list work; they don't plan around the day, and they can't be used hands-free. ORION answers the question, and because it speaks MCP, an assistant like Alexa+ can ask for a briefing, plan the next 45 minutes, add a lab to the timetable, or tick off a task, all by voice.

## Highlights
- **Full MCP surface:** 13 tools, 3 resources and 2 prompts over Streamable HTTP. Negotiates protocol `2025-11-25` (verified with the Python SDK 1.30).
- **Safety annotations on every tool:** read-only, write or destructive hints, so a client can ask before deleting.
- **Voice-first tools:** `get_daily_briefing` and `what_should_i_do_now` return a ready-to-speak `spoken` field.
- **A schedule you can edit:** `add_event` / `remove_event` (or the UI). Plans never overlap an event; a block is shortened to fit the gap before one.
- **Understands how people talk:** "1.5 hours", "2 hours 30 minutes", "from 4:30 pm", and deadlines such as "Monday", "2026-10-25", "next Friday".
- **One source of truth:** the web app calls ORION *through its own MCP server*, so the UI and Alexa+ use identical tools.
- **Voice demo built in:** speak a request, hear the plan read back (browser Web Speech API; Chrome/Edge).
- **Timezone-aware:** set `ORION_TZ` so greetings and "now" follow the user's day even on a UTC server.
- **Optional Amazon Bedrock polish** for more natural spoken replies, with a safe fallback.
- **Verified:** 78 automated tests, including protocol-level MCP tests and a live end-to-end run of the real server.

## Architecture
```
Alexa+ / MCP Inspector / any MCP client ──Streamable HTTP──►  /mcp ─┐
                                                                    ├─► mcp_server.py (tools · resources · prompts)
Web UI ──REST──► FastAPI (server.py) ──MCP client (loopback)──►  /mcp ─┘          │
                                                                    agent.py · briefing.py · tools.py · clock.py
                                                                                   │
                                                              data/tasks.json · data/schedule.json (atomic writes)
```

### MCP tools
| Tool | Hint | Purpose |
|---|---|---|
| `get_tasks(status)` | read-only | List tasks (`all`, `pending`, `completed`) |
| `get_schedule` | read-only | Today's fixed events, in time order |
| `create_study_plan(available_minutes, start_hour, start_minute)` | read-only | Deadline-aware plan around the schedule |
| `get_daily_briefing(voice_polish)` | read-only | Overdue / due today / next event, plus a `spoken` summary |
| `what_should_i_do_now(available_minutes, voice_polish)` | read-only | Plan starting *now*, with a `spoken` summary |
| `get_system_status` | read-only | Health and counts |
| `create_task(title, deadline, priority)` | write | Add a task |
| `add_event(time, name, duration_minutes)` | write | Add a class/lab/appointment (`2pm`, `2:30 PM`, `14:30`) |
| `update_task(task_id, title, deadline, priority)` | idempotent write | Edit a task |
| `complete_task(task_id)` / `reopen_task(task_id)` | idempotent write | Toggle completion |
| `remove_task(task_id)` | **destructive** | Delete a task |
| `remove_event(event_id)` | **destructive** | Delete an event |

**Resources:** `orion://tasks`, `orion://schedule`, `orion://briefing`  
**Prompts:** `plan_my_evening(hours)`, `weekly_review`

## Run locally
```bash
cd backend
python -m venv venv && source venv/bin/activate     # Windows: venv\Scripts\activate
pip install -r requirements.txt
python server.py
```
- Web app: http://127.0.0.1:8000
- MCP endpoint: `http://127.0.0.1:8000/mcp` (with or without trailing slash)
- API docs: http://127.0.0.1:8000/docs

The page finds the backend automatically: it uses its own origin when ORION serves it, otherwise `http://127.0.0.1:8000`, so opening `frontend/index.html` with VS Code Live Server also works while the backend runs. Add `?api=https://your-host` to point it elsewhere.

### See the MCP server in action
```bash
python demo/mcp_demo.py                      # or: python demo/mcp_demo.py https://your-app/mcp
```
A scripted agent connects over Streamable HTTP, lists the tools with their safety hints, asks for a briefing, plans around a new lab, creates a task, and cleans up after itself. Or use the official inspector:
```bash
npx @modelcontextprotocol/inspector          # transport: Streamable HTTP, URL: http://127.0.0.1:8000/mcp
```

## Deploy
```bash
docker build -t orion . && docker run -p 8000:8000 -v orion-data:/data orion
```
Or use the included `render.yaml` (Render Blueprint). On a public host:
- `HOST=0.0.0.0` (set in the Dockerfile). Render's hostname is allowed automatically; elsewhere set `ORION_ALLOWED_HOSTS=your.domain.com` (MCP DNS-rebinding protection rejects unknown hosts by design).
- Set `ORION_TZ` to your timezone (for example `Asia/Kolkata`).
- Mount a persistent disk and set `ORION_DATA_DIR`, otherwise data resets whenever the host recreates its filesystem (Render's free tier has no persistent disk).

| Variable | Default | Meaning |
|---|---|---|
| `HOST` / `PORT` | `127.0.0.1` / `8000` | Bind address and port |
| `ORION_TZ` | system zone | IANA timezone, e.g. `Asia/Kolkata` |
| `ORION_DATA_DIR` | `./data` | Where `tasks.json` and `schedule.json` live |
| `ORION_ALLOWED_HOSTS` | *(empty)* | Public hostnames allowed to call `/mcp` |
| `MCP_URL` | `http://127.0.0.1:$PORT/mcp/` | How the REST layer reaches the MCP server |
| `ORION_BEDROCK_MODEL_ID` | *(empty)* | Enables Amazon Bedrock voice polish |
| `AWS_REGION` | `us-east-1` | Region for Bedrock |

## Optional: Amazon Bedrock voice polish
Set `ORION_BEDROCK_MODEL_ID`, `pip install boto3`, and provide AWS credentials. ORION then asks Bedrock (Converse API) to rephrase spoken summaries naturally, and **rejects any rewrite that drops a number from the original**. Any failure falls back to the deterministic text, so ORION never depends on AWS. Step-by-step setup and a checker (`python scripts/check_bedrock.py`) are in [docs/AWS_BEDROCK.md](docs/AWS_BEDROCK.md). *This path is covered by mocked tests; verify it against your own AWS account.*

## Tests
```bash
pip install -r backend/requirements.txt pytest
python -m pytest -q
```
Covers request parsing, deadline logic, the planner (ordering, no overlaps, end of day), storage (validation, corruption backup, atomic writes), schedule editing, timezone handling, the MCP protocol (tools, annotations, resources, prompts), and a live end-to-end run of the real server including the demo client.

## Project layout
```
backend/   server.py (REST + UI + /mcp) · mcp_server.py (tools/resources/prompts)
           agent.py (parsing + planner) · briefing.py (spoken text, Bedrock) · tools.py (storage) · clock.py
frontend/  index.html · script.js · style.css
demo/      mcp_demo.py        scripts/  check_bedrock.py        docs/  AWS_BEDROCK.md, screenshots
tests/     78 tests           Dockerfile · render.yaml · .github/workflows/ci.yml
```

## Known limitations
- No authentication on the REST API or MCP endpoint (hackathon scope). Add auth before storing anything private.
- One shared task list and timetable, not multi-user.
- The timetable is a single day's list of events, not a week calendar.
- Deadlines are free text, understood for common forms (today, tomorrow, weekdays, ISO dates, DD/MM); anything else counts as "no deadline".
- Request parsing is rule-based, not a language model.
- Voice input/output in the web app needs a browser with the Web Speech API (Chrome/Edge).

## What was built during the hackathon
ORION began as a rule-based planner exposing a handful of MCP tools (`get_tasks`, `get_schedule`, `create_study_plan`, `create_task`, `complete_task`) with a basic web UI. During the submission window it was substantially extended:
- MCP: 8 more tools, resources, prompts, safety annotations, voice-first tools, spoken briefings, protocol 2025-11-25 verified, DNS-rebinding configuration for deployment, and `/mcp` served with or without a trailing slash.
- Planner rewrite: correct duration/time parsing, real deadline understanding, schedule-aware blocks that never overlap events, end-of-day handling.
- An editable timetable (tools and UI), task edit/delete/reopen, filters, a daily briefing card with progress, voice input and read-aloud, and a live MCP tool catalog in the UI.
- Reliability: validated input everywhere (including direct MCP calls), atomic saves with corruption backup, timezone support.
- Engineering: 78 tests, Dockerfile, Render blueprint, CI, scripted MCP demo client, optional Bedrock integration.

## License
MIT — see [LICENSE](LICENSE).