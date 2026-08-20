"""
Base class every specialized agent inherits from.

Centralizes the behaviour the hackathon spec calls out explicitly:
- real started_at/completed_at/duration timestamps
- retry handling (one retry on failure, then surfaced as 'failed')
- writing every run to ClickHouse (agent_runs table)
- emitting AgentEvent objects an SSE endpoint can stream to the frontend
"""
from __future__ import annotations

import abc
import logging
import time
from datetime import datetime
from typing import AsyncIterator

from app.models.schemas import AgentName, AgentRun, AgentStatus, AgentEvent
from app.services.clickhouse_service import ClickHouseService, ClickHouseUnavailableError

logger = logging.getLogger("cineflow.agents")

MAX_RETRIES = 1


class AgentExecutionError(RuntimeError):
    pass


class BaseAgent(abc.ABC):
    name: AgentName

    def __init__(self, clickhouse: ClickHouseService | None = None) -> None:
        self.clickhouse = clickhouse

    @abc.abstractmethod
    async def run(self, project_id: str, context: dict) -> dict:
        """Execute the agent. Must return a dict that becomes AgentEvent.payload."""

    async def execute(self, project_id: str, context: dict) -> AsyncIterator[AgentEvent]:
        """
        Wraps `run()` with timing, retry, and ClickHouse persistence, yielding
        AgentEvents as it goes (RUNNING -> COMPLETED/FAILED).
        """
        yield AgentEvent(project_id=project_id, agent_name=self.name, status=AgentStatus.RUNNING,
                          message=f"{self.name.value} started")

        attempt = 0
        started_at = datetime.utcnow()
        t0 = time.monotonic()
        last_error: Exception | None = None

        while attempt <= MAX_RETRIES:
            try:
                output = await self.run(project_id, context)
                duration_ms = int((time.monotonic() - t0) * 1000)
                completed_at = datetime.utcnow()

                self._log_run(project_id, AgentStatus.COMPLETED, started_at, completed_at,
                               duration_ms, context, output, None, attempt)

                yield AgentEvent(
                    project_id=project_id, agent_name=self.name, status=AgentStatus.COMPLETED,
                    message=f"{self.name.value} completed in {duration_ms}ms",
                    payload=output,
                )
                return
            except Exception as exc:  # noqa: BLE001 - we deliberately catch broadly to log+retry
                last_error = exc
                logger.warning("%s attempt %d failed: %s", self.name.value, attempt, exc)
                if attempt < MAX_RETRIES:
                    yield AgentEvent(
                        project_id=project_id, agent_name=self.name, status=AgentStatus.RETRYING,
                        message=f"{self.name.value} failed, retrying ({str(exc)[:200]})",
                    )
                attempt += 1

        duration_ms = int((time.monotonic() - t0) * 1000)
        completed_at = datetime.utcnow()
        self._log_run(project_id, AgentStatus.FAILED, started_at, completed_at,
                       duration_ms, context, {}, str(last_error), attempt)

        yield AgentEvent(
            project_id=project_id, agent_name=self.name, status=AgentStatus.FAILED,
            message=f"{self.name.value} failed after {attempt} attempt(s): {last_error}",
        )

    def _log_run(self, project_id, status, started_at, completed_at, duration_ms,
                 context, output, error, retry_count) -> None:
        if self.clickhouse is None:
            return
        run = AgentRun(
            project_id=project_id, agent_name=self.name, status=status,
            started_at=started_at, completed_at=completed_at, duration_ms=duration_ms,
            input_summary=str(context)[:500], output_summary=str(output)[:500],
            error=error, retry_count=retry_count,
        )
        try:
            self.clickhouse.insert_agent_run(run.model_dump())
        except ClickHouseUnavailableError as exc:
            logger.warning("Could not log agent run to ClickHouse (continuing): %s", exc)
