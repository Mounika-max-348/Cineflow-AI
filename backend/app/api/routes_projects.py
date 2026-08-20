"""
Project intake, listing, and real-time execution endpoints.

Every project is persisted in the real SQL database (app/db/auth_db.py ->
Project table), scoped to owner_id. Nothing here is stored in memory —
restart the server and your projects are still there, which also means a
brand-new account genuinely has zero projects until it creates one (no
seeded fake data).
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from app.agents.analytics_agent import AnalyticsAgent
from app.agents.budget_agent import BudgetAgent
from app.agents.coordinator import CoordinatorAgent
from app.agents.producer_match_agent import ProducerMatchAgent
from app.agents.risk_agent import RiskAgent
from app.agents.scheduling_agent import SchedulingAgent
from app.agents.script_agent import ScriptAgent
from app.api.routes_auth import get_current_user
from app.db.auth_db import Project, User, get_db
from app.models.schemas import AgentName, ProjectCreateRequest
from app.services.activity_service import log_activity
from app.services.clickhouse_service import ClickHouseUnavailableError, get_clickhouse_service
from app.services.gemini_service import GeminiNotConfiguredError, get_gemini_service

logger = logging.getLogger("cineflow.api.projects")
router = APIRouter(prefix="/api/projects", tags=["projects"])

_IMPLEMENTED_AGENTS = {
    AgentName.SCRIPT_AGENT,
    AgentName.BUDGET_AGENT,
    AgentName.PRODUCER_MATCH_AGENT,
    AgentName.SCHEDULING_AGENT,
    AgentName.RISK_AGENT,
    AgentName.ANALYTICS_AGENT,
}


@router.post("")
def create_project(
    request: ProjectCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = Project(
        id=str(uuid.uuid4()),
        owner_id=current_user.id,
        title=request.title or "Untitled Project",
        input_mode=request.input_mode.value,
        raw_text=request.raw_text,
        already_funded=request.already_funded,
        country_context=request.country_context,
        status="draft",
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    log_activity(
        db, user_id=current_user.id, event_type="project_created",
        title=f"Project created: {project.title}",
        description=f"{'Screenplay' if project.input_mode == 'screenplay' else 'Idea'} submitted for analysis.",
        project_id=project.id,
    )

    clickhouse = get_clickhouse_service()
    try:
        clickhouse.insert_project({
            "project_id": project.id,
            "title": project.title,
            "genre": "",
            "input_mode": project.input_mode,
            "already_funded": project.already_funded,
            "created_at": project.created_at,
        })
    except ClickHouseUnavailableError as exc:
        logger.warning("ClickHouse unavailable, project created without analytics row: %s", exc)

    return {"project_id": project.id, "status": "created"}


@router.get("")
def list_my_projects(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Returns only the current user's own projects. A new account gets an
    empty list — there is no seeded/demo data mixed into real accounts."""
    projects = (
        db.query(Project)
        .filter(Project.owner_id == current_user.id)
        .order_by(Project.created_at.desc())
        .all()
    )
    return {
        "projects": [
            {
                "project_id": p.id,
                "title": p.title,
                "input_mode": p.input_mode,
                "status": p.status,
                "created_at": p.created_at.isoformat(),
            }
            for p in projects
        ]
    }


@router.get("/{project_id}/stream")
async def stream_execution(project_id: str, token: str, db: Session = Depends(get_db)):
    # EventSource cannot send an Authorization header, so the frontend passes
    # the JWT as a query param here instead — verified exactly like any other
    # protected route, not an unauthenticated back door.
    from app.services.auth_service import InvalidTokenError, decode_access_token

    try:
        payload = decode_access_token(token)
    except InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")

    project = db.query(Project).filter(Project.id == project_id).first()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.owner_id != payload.get("sub"):
        raise HTTPException(status_code=403, detail="You do not own this project.")

    request = ProjectCreateRequest(
        title=project.title,
        input_mode=project.input_mode,
        raw_text=project.raw_text,
        already_funded=project.already_funded,
        country_context=project.country_context,
    )

    async def event_generator():
        gemini = get_gemini_service()
        clickhouse = get_clickhouse_service()

        project.status = "analyzing"
        db.commit()

        yield _sse(project_id, "coordinator", "running", "Gemini Coordinator is analyzing your production…")
        try:
            coordinator = CoordinatorAgent(gemini)
            plan = coordinator.build_execution_plan(project_id, request)
        except GeminiNotConfiguredError as exc:
            project.status = "failed"
            db.commit()
            yield _sse(project_id, "coordinator", "failed", str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            logger.exception("Coordinator failed")
            project.status = "failed"
            db.commit()
            yield _sse(project_id, "coordinator", "failed", f"Coordinator error: {exc}")
            return

        yield _sse(project_id, "coordinator", "completed", plan.notes or "Execution plan ready",
                    payload=plan.model_dump())

        context = {
            "raw_text": request.raw_text,
            "input_mode": request.input_mode.value,
            "already_funded": request.already_funded,
            "country_context": request.country_context,
        }

        any_failed = False
        for step in plan.steps:
            if step.name not in _IMPLEMENTED_AGENTS:
                yield _sse(project_id, step.name.value, "skipped",
                           f"{step.name.value} is planned ({step.reason}) but not yet implemented "
                           "in this build phase.")
                continue

            agent = _build_agent(step.name, gemini, clickhouse, db)
            async for event in agent.execute(project_id, context):
                yield {"event": "agent_update", "data": event.model_dump_json()}
                if event.status.value == "completed" and event.payload:
                    context[step.name.value] = event.payload
                    log_activity(
                        db, user_id=project.owner_id, event_type="agent_completed",
                        title=f"{step.name.value.replace('_', ' ').title()} finished",
                        description=f"Completed analysis for \"{project.title}\".",
                        project_id=project_id,
                    )
                if event.status.value == "failed":
                    any_failed = True
                    log_activity(
                        db, user_id=project.owner_id, event_type="agent_failed",
                        title=f"{step.name.value.replace('_', ' ').title()} failed",
                        description=event.message[:200],
                        project_id=project_id,
                    )

        project.status = "failed" if any_failed else "completed"
        db.commit()

        log_activity(
            db, user_id=project.owner_id, event_type="pipeline_completed",
            title=f"Pipeline finished: {project.title}",
            description="Completed successfully." if not any_failed else "Finished with one or more agent failures.",
            project_id=project_id,
        )

        yield _sse(project_id, "pipeline", "completed", "Pipeline finished for currently implemented agents.")

    return EventSourceResponse(event_generator())


def _build_agent(name: AgentName, gemini, clickhouse, db: Session):
    if name == AgentName.SCRIPT_AGENT:
        return ScriptAgent(gemini, clickhouse=clickhouse)
    if name == AgentName.BUDGET_AGENT:
        return BudgetAgent(gemini, clickhouse=clickhouse)
    if name == AgentName.PRODUCER_MATCH_AGENT:
        return ProducerMatchAgent(gemini, db, clickhouse=clickhouse)
    if name == AgentName.SCHEDULING_AGENT:
        return SchedulingAgent(gemini, clickhouse=clickhouse)
    if name == AgentName.RISK_AGENT:
        return RiskAgent(gemini, clickhouse=clickhouse)
    if name == AgentName.ANALYTICS_AGENT:
        return AnalyticsAgent(clickhouse=clickhouse)
    raise ValueError(f"No agent builder registered for {name}")


def _sse(project_id: str, agent: str, status: str, message: str, payload: dict | None = None) -> dict:
    return {
        "event": "agent_update",
        "data": json.dumps({
            "project_id": project_id,
            "agent_name": agent,
            "status": status,
            "message": message,
            "timestamp": datetime.utcnow().isoformat(),
            "payload": payload,
        }),
    }