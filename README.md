# 🎬 CineFlow AI

**From Story to Screen — Powered by Autonomous AI Agents**

Built for [Agentic Cinema: The Blockbuster Hackathon](https://agentic-cinema.devpost.com/).

## Problem

Independent directors often have a great idea or finished screenplay but no
path from there to production: no budget model, no risk analysis, no
schedule, and no way to find producers whose money, genre interests, and
geography actually match the project.

## Solution

CineFlow AI turns a movie idea or screenplay into an investor-ready
production blueprint. A **Gemini Coordinator** reasons about the project
(idea vs. full screenplay, already funded or not) and dynamically decides
which specialized agents to run — it does not blindly run a fixed pipeline.
Each agent's structured output is persisted to **ClickHouse**, which powers
the analytics layer judges/users see in the dashboard.

## Why this is agentic, not a chatbot

Gemini isn't answering questions here — it's producing a dependency-ordered
execution plan (`ExecutionPlan` in `app/models/schemas.py`), and the backend
executes that plan step by step, streaming real status over SSE. See
`docs/architecture.md` for the full flow and an honest build-status table.

## Current build status

This repo currently implements **Phase 1–2** of the roadmap end-to-end and
for real: project intake → Gemini Coordinator → Script Agent → ClickHouse
logging → SSE streaming to the frontend. Budget/Producer-Match/Scheduling/
Risk/Analytics agents are modeled in the schema and orchestration logic but
not yet implemented — the pipeline reports them as `skipped (not yet
implemented)` rather than faking their output. See `docs/architecture.md`
for the exact status table and the phase-by-phase roadmap below.

## Tech stack

| Layer | Tech |
|---|---|
| Frontend | Static HTML prototype (`frontend/`) today; React + TS + Tailwind planned |
| Backend | Python, FastAPI, SSE |
| AI | Gemini via `google-genai` SDK (API key or Vertex AI) |
| Analytics DB (partner tech) | ClickHouse |
| Deployment target | Google Cloud Run + Secret Manager |

## Local setup

### 1. Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env: add GEMINI_API_KEY, and ClickHouse creds if you have them
uvicorn app.main:app --reload
```

Visit `http://localhost:8000/docs` for the interactive API (Swagger).
`GET /health` reports whether Gemini is configured.

### 2. ClickHouse

Easiest path: a free [ClickHouse Cloud](https://clickhouse.com/cloud) instance.
Put its host/user/password into `backend/.env`, then:

```bash
cd backend
python scripts/init_clickhouse.py
```

Or run ClickHouse locally via Docker (see `docker-compose.yml`), using
`CLICKHOUSE_PORT=8123` and `CLICKHOUSE_SECURE=false`.

### 3. Everything via Docker Compose

```bash
docker compose up --build
```

### 4. Frontend

The original prototype lives at `frontend/cineflow-ai.html` — open it
directly, or serve it:

```bash
cd frontend && python -m http.server 5173
```

It is not yet wired to the live backend (see Roadmap). Wiring the wizard's
"Generate" step to `POST /api/projects` + `GET /api/projects/{id}/stream`
is the next concrete task.

## Testing

```bash
cd backend
pytest tests/ -v
```

Unit tests mock the Gemini/ClickHouse clients to test agent logic (timing,
retries, status transitions, execution ordering) without needing live
credentials in CI. They do **not** mock or fake what the running app does —
that distinction matters and is documented in each test file's docstring.

## API surface (current)

- `POST /api/projects` — create a project from an idea or screenplay
- `GET /api/projects/{id}/stream` — SSE stream of the real Coordinator +
  agent pipeline execution
- `GET /api/analytics/budget` — average budget by genre (ClickHouse)
- `GET /api/analytics/agents` — agent success rate / avg duration (ClickHouse)
- `GET /api/analytics/project/{id}` — per-project agent run timeline (ClickHouse)

## Roadmap (phase-by-phase, matches the build order in the project brief)

- [x] Phase 1: repo structure, architecture
- [x] Phase 2: Gemini Coordinator + Script Agent, one real end-to-end flow
- [ ] Phase 3: Budget Agent
- [ ] Phase 4: Producer Match Agent + producer marketplace + seed data (25+ producers)
- [ ] Phase 5: Scheduling Agent (Gantt/timeline)
- [ ] Phase 6: Risk Agent
- [x] Phase 7: ClickHouse (schema + service layer done; more write paths land with Phases 3-6)
- [x] Phase 8: Real-time SSE agent visualization (backend done; frontend wiring pending)
- [ ] Phase 9: Producer marketplace UI
- [ ] Phase 10: Investment workflow
- [ ] Phase 11: Full analytics dashboard UI
- [ ] Phase 12: Deploy to Cloud Run
- [ ] Phase 13: Broader test coverage (Budget/Producer/Scheduling/Risk)
- [ ] Phase 14: Hackathon polish, demo video

## License

MIT — see `LICENSE`.
