# Devpost submission kit — ORION (Alexa+ track)

Copy these into the Devpost form. Items marked ✍️ must come from **your own** experience; I deliberately left them as prompts rather than invent feedback.

## Project description (paste)
**ORION** is an MCP server that turns a voice request like *"I have 90 minutes from 4:30 pm"* into a deadline-aware study plan that fits around a student's classes, then reads it back in plain language.

**Why:** the daily student question is "what should I work on right now?" Task apps list work; they don't plan around the time you actually have, and they aren't usable hands-free.

**How it works:** ORION exposes 11 tools, 3 resources and 2 prompts over MCP (Streamable HTTP, protocol 2025-11-25). Tools carry read-only/destructive annotations so an assistant can confirm before deleting. Voice-first tools (`get_daily_briefing`, `what_should_i_do_now`) return a ready-to-speak summary. The planner ranks tasks by deadline urgency then priority and lays them out in blocks that never overlap scheduled events. The included web app calls ORION through its own MCP server and adds a simulated voice-assistant experience (speak a request, hear the plan). Optional Amazon Bedrock rewrites spoken replies more naturally, with number-preservation checks and a safe fallback.

**Built with:** Python, FastAPI, MCP Python SDK (FastMCP), Streamable HTTP, vanilla JS, Web Speech API, optional Amazon Bedrock (Converse API), pytest.

## Track and mini challenges
- **Primary track:** Alexa+ (self-hosted MCP server, Streamable HTTP).
- **AWS Builder mini challenge:** only enter if you actually enable and demo the Bedrock polish (see README) and describe it in your feedback answer.
- **Open Source mini challenge:** needs an *additional* open-source project or a contribution (fork/PR) during the window, with its URL. Not covered by ORION itself.

## Requirement checklist (from the hackathon rules)
- [ ] Repo is public with the MIT license visible at the top, **or** private and shared with: chris-trag, knmeiss, giolaq, anishamalde, mosesroth, emersonsklar (add them at submission time; invitations expire in 7 days)
- [ ] Repo calls the track tech in code: `backend/mcp_server.py` (FastMCP) is mounted by `backend/server.py` at `/mcp`
- [ ] Demo video **under 3 minutes**, public on YouTube/Vimeo, in English, showing the MCP server in action
- [ ] Text description (above), tracks selected, and "what changed during the window" filled in README
- [ ] Product feedback on every tool/SDK you used ✍️
- [ ] Optional: friction log entries (up to a 10% judging bonus) ✍️
- [ ] No third-party trademarks or copyrighted music in the video

## 3-minute demo script
| Time | Show | Say |
|---|---|---|
| 0:00–0:15 | Web UI, click 🎤 Speak: *"I have an hour from four thirty"* | "Students don't need another to-do list. They need to know what to do with the time they have." |
| 0:15–0:40 | Plan appears and is read aloud; point at a block shortened before the AI Lab | "ORION plans around my schedule and never overlaps a class." |
| 0:40–1:10 | Say/type *"What's due today?"*; briefing card + chips | "A spoken briefing: overdue, due today, what's next." |
| 1:10–2:00 | **MCP Inspector** against the deployed `/mcp`: list tools (point at read-only vs destructive badges), call `what_should_i_do_now`, then `create_task` | "ORION is a real MCP server over Streamable HTTP. Alexa+ or any client gets the same tools the UI uses." |
| 2:00–2:25 | Open the UI's *Connect an agent* panel; add a task via Inspector and show it appear after Refresh | "One source of truth for every client." |
| 2:25–2:50 | Terminal: `python -m pytest -q` → 54 passed | "Protocol-level tests and a live end-to-end run." |
| 2:50–3:00 | Architecture slide / README | "ORION: what should I do right now?" |

Tip: lead with the voice moment; judges may stop watching at 3:00.

## Product feedback prompts ✍️
For each tool you used (MCP Python SDK, MCP Inspector, Alexa+ developer resources, Amazon Bedrock if enabled, Render/hosting), answer in your own words: what you used it for; what worked well; what needed work; how onboarding felt; would you build with it again. If you used Bedrock, name the service, model and how it is called.

Real observations from building ORION you may want to include if they match your experience:
- `pip install mcp` now resolves to 2.x, which renamed `FastMCP`; ORION pins `mcp<2`.
- FastMCP enables DNS-rebinding protection by default for loopback hosts, so a deployed server answers `421 Invalid Host header` until the public hostname is allowed.
- Starlette's `Mount("/mcp")` does not match `/mcp` without a trailing slash once a static mount sits at `/`, so some MCP clients fail until the path is normalised.

## Friction-log template ✍️
Task attempted · steps taken · expected vs actual · severity (low/med/high) · workaround · suggestion.
