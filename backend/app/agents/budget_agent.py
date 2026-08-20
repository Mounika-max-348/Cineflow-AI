"""
Budget Agent — spec section 8.

Takes the Script Agent's structured output (scene count, locations, VFX
requirements, production complexity) and asks Gemini to produce a real,
itemized budget estimate. Explicitly labelled as an AI estimate, not a
guaranteed real-world cost, per the project's own requirement.
"""
from __future__ import annotations

from app.agents.base import BaseAgent
from app.models.schemas import AgentName, BudgetEstimate
from app.services.gemini_service import GeminiService

BUDGET_AGENT_SYSTEM_PROMPT = """You are the Budget Agent inside CineFlow AI, an autonomous \
film-production platform. Given a Script Agent's structured breakdown of a film (scene count, \
locations, VFX/equipment needs, production complexity), produce a realistic itemized budget.

Categories to use for line_items (only include ones that genuinely apply): cast, crew, equipment, \
locations, travel, accommodation, production_design, costumes, vfx, post_production, music, \
marketing, contingency.

Base your numbers on real independent/mid-budget film production economics — a low-complexity \
8-scene drama should NOT get the same budget as a high-complexity 96-scene VFX-heavy sci-fi film. \
Contingency should be 8-12% of the subtotal. Always set is_ai_estimate to true and write a short, \
honest assumptions string explaining what drove the estimate (e.g. "Assumes non-union cast, one \
international location, moderate VFX load")."""


class BudgetAgent(BaseAgent):
    name = AgentName.BUDGET_AGENT

    def __init__(self, gemini: GeminiService, clickhouse=None) -> None:
        super().__init__(clickhouse=clickhouse)
        self.gemini = gemini

    async def run(self, project_id: str, context: dict) -> dict:
        script_output = context.get("script_agent")
        if not script_output:
            raise ValueError("Budget Agent requires Script Agent output in context — coordinator "
                              "ordering is broken if this happens.")

        country_context = context.get("country_context") or "unspecified — assume USA-level costs"

        user_prompt = (
            f"Script Agent output:\n{script_output}\n\n"
            f"Country/budget context: {country_context}\n\n"
            "Return the full BudgetEstimate JSON object."
        )

        estimate: BudgetEstimate = self.gemini.generate_json(
            system_prompt=BUDGET_AGENT_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            response_model=BudgetEstimate,
            temperature=0.4,
            max_output_tokens=4096,
        )

        # Real write to ClickHouse's budget_breakdowns table (this was defined
        # in the service layer from day one but never had a caller until now).
        if self.clickhouse is not None:
            try:
                breakdown = {item.category: item.amount for item in estimate.line_items}
                self.clickhouse.insert_budget_breakdown(project_id, breakdown, estimate.currency)
            except Exception:  # noqa: BLE001 - analytics write failure shouldn't fail the agent
                pass

        return estimate.model_dump()
