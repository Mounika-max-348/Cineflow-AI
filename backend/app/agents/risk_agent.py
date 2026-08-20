"""
Risk Agent — spec section 11.

Takes the Script, Budget, and Scheduling agents' output and asks Gemini to
identify realistic production, financial, safety, and scheduling risks —
mirroring the `risks` ClickHouse table exactly (risk_type, probability_pct,
impact, risk_score, explanation, mitigation).
"""
from __future__ import annotations

from app.agents.base import BaseAgent
from app.models.schemas import AgentName, RiskAssessment
from app.services.gemini_service import GeminiService

RISK_AGENT_SYSTEM_PROMPT = """You are the Risk Agent inside CineFlow AI, an autonomous film-production \
platform. Given a Script Agent breakdown, a Budget Agent estimate, and a Scheduling Agent plan, \
identify realistic risks to this production.

Use risk_type values like: budget, scheduling, location, weather, safety, legal, cast, vfx, funding, \
other. For each risk give probability_pct (0-100, how likely this risk materializes), impact \
(low/medium/high — how bad it is if it does), risk_score (0-100, an overall severity combining \
probability and impact — do not just multiply them naively, use judgment), a clear explanation \
grounded in the specific project details you were given (not generic boilerplate), and a concrete \
mitigation. A high-VFX action film should surface different risks than a low-budget indie drama — \
be specific to what you were actually given. Set overall_risk_level (low/medium/high) based on the \
full risk profile, and write an honest summary. Always set is_ai_estimate to true."""


class RiskAgent(BaseAgent):
    name = AgentName.RISK_AGENT

    def __init__(self, gemini: GeminiService, clickhouse=None) -> None:
        super().__init__(clickhouse=clickhouse)
        self.gemini = gemini

    async def run(self, project_id: str, context: dict) -> dict:
        script_output = context.get("script_agent")
        budget_output = context.get("budget_agent")
        scheduling_output = context.get("scheduling_agent")

        missing = [
            name for name, val in [
                ("Script Agent", script_output),
                ("Budget Agent", budget_output),
                ("Scheduling Agent", scheduling_output),
            ] if not val
        ]
        if missing:
            raise ValueError(f"Risk Agent requires output from: {', '.join(missing)}.")

        user_prompt = (
            f"Script Agent output:\n{script_output}\n\n"
            f"Budget Agent output:\n{budget_output}\n\n"
            f"Scheduling Agent output:\n{scheduling_output}\n\n"
            "Return the full RiskAssessment JSON object."
        )

        assessment: RiskAssessment = self.gemini.generate_json(
            system_prompt=RISK_AGENT_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            response_model=RiskAssessment,
            temperature=0.4,
            max_output_tokens=4096,
        )

        if self.clickhouse is not None:
            try:
                self.clickhouse.insert_risks(project_id, [r.model_dump() for r in assessment.risks])
            except Exception:  # noqa: BLE001 — analytics write failure shouldn't fail the agent
                pass

        return assessment.model_dump()
