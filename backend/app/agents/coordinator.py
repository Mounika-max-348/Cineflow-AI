"""
Gemini Coordinator — the central brain described in spec section 6.

Given the raw project intake (idea vs screenplay, funded vs not), it asks
Gemini to reason about which specialized agents are actually needed, in what
order, and why — rather than always running the full fixed pipeline. This is
the "non-obvious agentic AI" differentiator called out in the judging
criteria (spec section 3.D): Gemini plans the workflow, it doesn't just
answer a question.
"""
from __future__ import annotations

from app.models.schemas import AgentName, ExecutionPlan, InputMode, ProjectCreateRequest
from app.services.gemini_service import GeminiService

COORDINATOR_SYSTEM_PROMPT = """You are the Gemini Coordinator for CineFlow AI, an autonomous \
film-production planning system. Given a director's project intake, decide which specialized \
agents must run, in what order, and why. Available agents: script_agent, budget_agent, \
producer_match_agent, scheduling_agent, risk_agent, analytics_agent.

Rules you must follow:
- script_agent always runs first; every other agent depends on it (directly or transitively).
- budget_agent depends on script_agent.
- producer_match_agent depends on script_agent and budget_agent.
- scheduling_agent depends on script_agent.
- risk_agent depends on script_agent, budget_agent, and scheduling_agent.
- analytics_agent depends on all agents that actually ran (it aggregates results into ClickHouse).
- If the project is already funded, you may still include producer_match_agent for future rounds,
  but note in its "reason" field that this is for expansion/co-production, not primary funding.
- If input_mode is "screenplay", note in script_agent's reason that deep scene-level extraction
  should be performed (not just a logline-level summary).

Return a concise execution plan explaining WHY each agent is included, not just the list."""


class CoordinatorAgent:
    name = AgentName.COORDINATOR

    def __init__(self, gemini: GeminiService) -> None:
        self.gemini = gemini

    def build_execution_plan(self, project_id: str, request: ProjectCreateRequest) -> ExecutionPlan:
        user_prompt = (
            f"Project ID: {project_id}\n"
            f"Input mode: {request.input_mode.value}\n"
            f"Already funded: {request.already_funded}\n"
            f"Country context: {request.country_context or 'unspecified'}\n\n"
            f"Raw input:\n{request.raw_text}\n\n"
            "Produce the execution plan as JSON with fields: project_id, steps "
            "(each with name, reason, depends_on), and notes (one sentence summary "
            "of your orchestration reasoning)."
        )

        plan = self.gemini.generate_json(
            system_prompt=COORDINATOR_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            response_model=ExecutionPlan,
            temperature=0.2,
        )
        # Defensive guarantee regardless of what Gemini returned: script_agent must be first.
        plan.steps.sort(key=lambda s: 0 if s.name == AgentName.SCRIPT_AGENT else 1)
        plan.project_id = project_id
        return plan
