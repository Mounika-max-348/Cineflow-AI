"""
MCP-backed ClickHouse analytics agent — this is the actual ClickHouse-track
requirement: the hackathon rules say the project must "actively use
ClickHouse at runtime via the official ClickHouse MCP server (mcp-clickhouse)."

Everything else in this codebase writes to ClickHouse over clickhouse-connect
directly, which is real but isn't the MCP server. This module is the piece
that is: it spins up the official `mcp-clickhouse` process, hands it to a
Google ADK LlmAgent as a tool source, and lets Gemini itself decide what SQL
to run against `list_databases` / `list_tables` / `run_query` to answer a
question in plain English. The MCP server enforces read-only access
(CLICKHOUSE_ALLOW_WRITE_ACCESS defaults to false), so this can't be used to
mutate data — only to query it.
"""
from __future__ import annotations

import logging
import os

from google.adk.agents.llm_agent import LlmAgent
from google.adk.runners import InMemoryRunner
from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset, StdioServerParameters
from google.genai import types as genai_types

from app.config import get_settings

logger = logging.getLogger("cineflow.mcp_analytics")

# ADK reads GOOGLE_API_KEY, but this project's .env uses GEMINI_API_KEY
# (matching the google-genai SDK used elsewhere). Bridge the two once here
# rather than asking for the same key under two different names.
_settings = get_settings()
if _settings.GEMINI_API_KEY and not os.environ.get("GOOGLE_API_KEY"):
    os.environ["GOOGLE_API_KEY"] = _settings.GEMINI_API_KEY

_INSTRUCTION = """\
You are CineFlow AI's analytics assistant. You have read-only tools that let
you query a live ClickHouse database named "cineflow" via the official
ClickHouse MCP server. Its tables include: projects, agent_runs,
agent_outputs, budget_breakdowns, producer_matches, production_schedule,
risks, workflow_metrics.

When asked a question:
1. Use list_tables to confirm the schema if you're unsure of a column name.
2. Write and run a real SQL SELECT query with run_query to answer the
   question from actual data. Never invent numbers.
3. Answer in 1-3 sentences in plain English, citing the real figures you
   found. If the query returns no rows, say so plainly instead of guessing.
"""


def _build_agent() -> LlmAgent:
    settings = get_settings()
    clickhouse_toolset = MCPToolset(
        connection_params=StdioServerParameters(
            command="mcp-clickhouse",
            env={
                "CLICKHOUSE_HOST": settings.CLICKHOUSE_HOST,
                "CLICKHOUSE_PORT": str(settings.CLICKHOUSE_PORT),
                "CLICKHOUSE_USER": settings.CLICKHOUSE_USER,
                "CLICKHOUSE_PASSWORD": settings.CLICKHOUSE_PASSWORD,
                "CLICKHOUSE_DATABASE": settings.CLICKHOUSE_DATABASE,
                "CLICKHOUSE_SECURE": "true" if settings.CLICKHOUSE_SECURE else "false",
                # Explicit belt-and-braces: this agent only ever reads.
                "CLICKHOUSE_ALLOW_WRITE_ACCESS": "false",
            },
        ),
    )
    return LlmAgent(
        name="clickhouse_analyst",
        model=settings.GEMINI_MODEL,
        instruction=_INSTRUCTION,
        tools=[clickhouse_toolset],
    )


async def ask_clickhouse(question: str) -> str:
    """Runs `question` through Gemini with live MCP-backed ClickHouse tools
    and returns its final text answer. Raises on any failure — callers
    should surface that as a clear error, not silently fall back."""
    agent = _build_agent()
    runner = InMemoryRunner(agent=agent, app_name="cineflow-analytics")
    session = await runner.session_service.create_session(
        app_name="cineflow-analytics", user_id="analytics-api"
    )

    final_text = ""
    async for event in runner.run_async(
        user_id="analytics-api",
        session_id=session.id,
        new_message=genai_types.Content(role="user", parts=[genai_types.Part(text=question)]),
    ):
        if event.is_final_response() and event.content and event.content.parts:
            final_text = "".join(p.text or "" for p in event.content.parts)

    if not final_text:
        raise RuntimeError("The analytics agent did not return an answer.")
    return final_text
