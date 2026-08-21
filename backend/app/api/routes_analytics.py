"""
Analytics endpoints — spec section 14. Every response here comes straight
from a ClickHouse query (see services/clickhouse_service.py); nothing is
computed from in-memory fake data.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.clickhouse_service import ClickHouseUnavailableError, get_clickhouse_service
from app.services.mcp_analytics_service import ask_clickhouse

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


class AskRequest(BaseModel):
    question: str


@router.post("/ask")
async def ask(request: AskRequest):
    """Natural-language ClickHouse query, answered live through the official
    mcp-clickhouse MCP server (not the direct clickhouse-connect client used
    elsewhere in this file) — this is the ClickHouse hackathon track's
    specific runtime requirement."""
    try:
        answer = await ask_clickhouse(request.question)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Analytics agent failed: {exc}") from exc
    return {"question": request.question, "answer": answer}


@router.get("/budget")
def budget_by_genre():
    ch = get_clickhouse_service()
    try:
        return {"data": ch.average_budget_by_genre()}
    except ClickHouseUnavailableError as exc:
        raise HTTPException(status_code=503, detail=f"ClickHouse unavailable: {exc}") from exc


@router.get("/agents")
def agent_success_rates():
    ch = get_clickhouse_service()
    try:
        return {"data": ch.agent_success_rates()}
    except ClickHouseUnavailableError as exc:
        raise HTTPException(status_code=503, detail=f"ClickHouse unavailable: {exc}") from exc


@router.get("/budget-breakdown")
def budget_breakdown():
    """Real spend by category, summed across every project's Budget Agent
    output. Powers the Analytics page's "Budget Allocation" chart."""
    ch = get_clickhouse_service()
    try:
        return {"data": ch.budget_totals_by_category()}
    except ClickHouseUnavailableError as exc:
        raise HTTPException(status_code=503, detail=f"ClickHouse unavailable: {exc}") from exc


@router.get("/pipeline-progress")
def pipeline_progress():
    """Real cumulative agent-completion count over time. Powers the
    Analytics page's "Production Progress" chart."""
    ch = get_clickhouse_service()
    try:
        return {"data": ch.pipeline_completion_over_time()}
    except ClickHouseUnavailableError as exc:
        raise HTTPException(status_code=503, detail=f"ClickHouse unavailable: {exc}") from exc


@router.get("/risk-heatmap")
def risk_heatmap():
    """Real risk rows bucketed into a probability x impact grid. Powers the
    Analytics page's "Risk Heatmap" chart."""
    ch = get_clickhouse_service()
    try:
        return {"data": ch.risk_heatmap()}
    except ClickHouseUnavailableError as exc:
        raise HTTPException(status_code=503, detail=f"ClickHouse unavailable: {exc}") from exc


@router.get("/project/{project_id}")
def project_timeline(project_id: str):
    ch = get_clickhouse_service()
    try:
        return {"data": ch.workflow_timeline(project_id)}
    except ClickHouseUnavailableError as exc:
        raise HTTPException(status_code=503, detail=f"ClickHouse unavailable: {exc}") from exc
