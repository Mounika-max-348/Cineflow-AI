"""
Structured data contracts passed between agents, the Coordinator, the API,
and ClickHouse. Keeping these as real Pydantic models (not raw dicts) is what
lets us validate agent output and reject malformed Gemini responses instead
of silently trusting free text.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


def new_id() -> str:
    return str(uuid.uuid4())


class InputMode(str, Enum):
    IDEA = "idea"
    SCREENPLAY = "screenplay"


class AgentName(str, Enum):
    COORDINATOR = "coordinator"
    SCRIPT_AGENT = "script_agent"
    BUDGET_AGENT = "budget_agent"
    PRODUCER_MATCH_AGENT = "producer_match_agent"
    SCHEDULING_AGENT = "scheduling_agent"
    RISK_AGENT = "risk_agent"
    ANALYTICS_AGENT = "analytics_agent"


class AgentStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"
    SKIPPED = "skipped"


# ---------------------------------------------------------------------------
# Project intake
# ---------------------------------------------------------------------------

class ProjectCreateRequest(BaseModel):
    title: Optional[str] = None
    input_mode: InputMode
    raw_text: str = Field(..., min_length=10, description="Movie idea or full screenplay text")
    already_funded: bool = False
    country_context: Optional[str] = None  # for budget localization


# ---------------------------------------------------------------------------
# Coordinator execution plan
# ---------------------------------------------------------------------------

class PlannedAgentStep(BaseModel):
    name: AgentName
    reason: str
    depends_on: list[AgentName] = Field(default_factory=list)


class ExecutionPlan(BaseModel):
    project_id: str
    steps: list[PlannedAgentStep]
    notes: str = ""


# ---------------------------------------------------------------------------
# Script Agent output
# ---------------------------------------------------------------------------

class SceneBreakdown(BaseModel):
    scene_number: int
    location: str
    interior_exterior: str
    day_night: str
    characters: list[str] = Field(default_factory=list)
    props: list[str] = Field(default_factory=list)
    special_equipment: list[str] = Field(default_factory=list)
    vfx_required: bool = False
    shooting_complexity: str = "medium"  # low | medium | high


class ScriptAnalysis(BaseModel):
    title: str
    genre: str
    subgenre: Optional[str] = None
    language: str = "English"
    logline: str
    synopsis: str
    characters: list[str] = Field(default_factory=list)
    character_descriptions: dict[str, str] = Field(default_factory=dict)
    scene_count: int
    locations: list[str] = Field(default_factory=list)
    props: list[str] = Field(default_factory=list)
    equipment_requirements: list[str] = Field(default_factory=list)
    vfx_requirements: list[str] = Field(default_factory=list)
    shooting_complexity: str
    estimated_runtime_minutes: int
    production_complexity: str  # low | medium | high
    target_audience: str
    scene_breakdown: list[SceneBreakdown] = Field(default_factory=list)


class BudgetLineItem(BaseModel):
    category: str  # cast | crew | equipment | locations | travel | accommodation | production_design | costumes | vfx | post_production | music | marketing | contingency
    amount: float


class BudgetEstimate(BaseModel):
    currency: str = "USD"
    line_items: list[BudgetLineItem]
    minimum_budget: float
    expected_budget: float
    maximum_budget: float
    confidence_score: int  # 0-100
    assumptions: str
    is_ai_estimate: bool = True


# ---------------------------------------------------------------------------
# Producer Match Agent output
# ---------------------------------------------------------------------------

class MatchedProducer(BaseModel):
    producer_id: str
    name: str
    company: str
    country: str
    compatibility_pct: float  # 0-100, weighted average of the sub-scores below
    genre_score: float
    budget_score: float
    geo_score: float
    language_score: float
    portfolio_score: float
    risk_score: float
    match_reason: str


class ProducerMatchResult(BaseModel):
    matched_producers: list[MatchedProducer] = Field(default_factory=list)
    total_candidates_considered: int
    notes: str


# ---------------------------------------------------------------------------
# Scheduling Agent output
# ---------------------------------------------------------------------------

class ScheduleStage(BaseModel):
    stage: str  # e.g. Development, Pre-Production, Casting, Principal Photography, VFX & Post, Marketing & Release
    start_offset_days: int  # days from pipeline run date
    duration_days: int
    depends_on: list[str] = Field(default_factory=list)  # names of other stages
    notes: str = ""


class SchedulingPlan(BaseModel):
    stages: list[ScheduleStage]
    total_duration_days: int
    critical_path: list[str] = Field(default_factory=list)
    assumptions: str
    is_ai_estimate: bool = True


# ---------------------------------------------------------------------------
# Risk Agent output
# ---------------------------------------------------------------------------

class RiskFactor(BaseModel):
    risk_type: str  # budget | scheduling | location | weather | safety | legal | cast | vfx | funding | other
    probability_pct: int  # 0-100
    impact: str  # low | medium | high
    risk_score: int  # 0-100 combined severity (probability x impact)
    explanation: str
    mitigation: str


class RiskAssessment(BaseModel):
    risks: list[RiskFactor]
    overall_risk_level: str  # low | medium | high
    summary: str
    is_ai_estimate: bool = True


# ---------------------------------------------------------------------------
# Analytics Agent output — real aggregation of whatever upstream agents
# actually produced, not a fresh Gemini call (there's nothing to "reason"
# about here, just genuine roll-up of already-generated structured data).
# ---------------------------------------------------------------------------

class ProjectAnalyticsSummary(BaseModel):
    agents_completed: list[str] = Field(default_factory=list)
    estimated_budget_usd: Optional[float] = None
    scene_count: Optional[int] = None
    total_schedule_days: Optional[int] = None
    overall_risk_level: Optional[str] = None
    top_matched_producer: Optional[str] = None
    summary: str


# ---------------------------------------------------------------------------
# Agent run bookkeeping (mirrors what gets written to ClickHouse)
# ---------------------------------------------------------------------------

class AgentRun(BaseModel):
    run_id: str = Field(default_factory=new_id)
    project_id: str
    agent_name: AgentName
    status: AgentStatus = AgentStatus.PENDING
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    input_summary: str = ""
    output_summary: str = ""
    error: Optional[str] = None
    retry_count: int = 0


class AgentEvent(BaseModel):
    """One SSE frame sent to the frontend during a live execution."""
    project_id: str
    agent_name: AgentName
    status: AgentStatus
    message: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    payload: Optional[dict] = None