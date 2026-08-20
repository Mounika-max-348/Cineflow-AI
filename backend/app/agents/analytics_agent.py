"""
Analytics Agent — spec section 12.

Unlike the other agents, this one doesn't call Gemini — there is nothing to
reason about. Its job (per the Coordinator's own description) is to
aggregate whatever the other agents that actually ran already produced, and
write a real summary row into ClickHouse's `workflow_metrics` table. Calling
an LLM to restate numbers that are already sitting in structured JSON would
just be theater; genuine aggregation is the honest implementation here.
"""
from __future__ import annotations

from app.agents.base import BaseAgent
from app.models.schemas import AgentName, ProjectAnalyticsSummary

# Every agent name whose presence in `context` we roll up, in pipeline order.
_TRACKED_AGENTS = ["script_agent", "budget_agent", "producer_match_agent", "scheduling_agent", "risk_agent"]


class AnalyticsAgent(BaseAgent):
    name = AgentName.ANALYTICS_AGENT

    def __init__(self, clickhouse=None) -> None:
        super().__init__(clickhouse=clickhouse)

    async def run(self, project_id: str, context: dict) -> dict:
        completed = [name for name in _TRACKED_AGENTS if context.get(name)]

        script_output = context.get("script_agent") or {}
        budget_output = context.get("budget_agent") or {}
        producer_match_output = context.get("producer_match_agent") or {}
        scheduling_output = context.get("scheduling_agent") or {}
        risk_output = context.get("risk_agent") or {}

        matched = producer_match_output.get("matched_producers") or []
        top_producer = matched[0]["name"] if matched else None

        summary_parts = [f"{len(completed)} of {len(_TRACKED_AGENTS)} planned agents completed."]
        if script_output.get("scene_count"):
            summary_parts.append(f"{script_output['scene_count']} scenes analyzed.")
        if budget_output.get("expected_budget"):
            summary_parts.append(f"Expected budget ${budget_output['expected_budget']:,.0f}.")
        if scheduling_output.get("total_duration_days"):
            summary_parts.append(f"Estimated {scheduling_output['total_duration_days']}-day production timeline.")
        if risk_output.get("overall_risk_level"):
            summary_parts.append(f"Overall risk level: {risk_output['overall_risk_level']}.")
        if top_producer:
            summary_parts.append(f"Top producer match: {top_producer}.")

        summary = ProjectAnalyticsSummary(
            agents_completed=completed,
            estimated_budget_usd=budget_output.get("expected_budget"),
            scene_count=script_output.get("scene_count"),
            total_schedule_days=scheduling_output.get("total_duration_days"),
            overall_risk_level=risk_output.get("overall_risk_level"),
            top_matched_producer=top_producer,
            summary=" ".join(summary_parts),
        )

        if self.clickhouse is not None:
            try:
                self.clickhouse.insert_workflow_metrics(
                    project_id,
                    agents_run=len(completed),
                    agents_failed=0,  # a failed upstream dep would have blocked this agent too — see routes_projects.py
                    agents_retried=0,  # per-attempt retry counts live in agent_runs, not re-derivable here
                    total_duration_ms=0,  # end-to-end pipeline timing isn't threaded through context; see agent_runs for per-agent timing
                )
            except Exception:  # noqa: BLE001 — analytics write failure shouldn't fail the agent
                pass

        return summary.model_dump()
