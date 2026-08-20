"""
Scheduling Agent — spec section 10.

Takes the Script Agent's output (scene count, locations, VFX needs,
shooting complexity) and asks Gemini to produce a realistic preliminary
production schedule broken into named stages (development, pre-production,
principal photography, post/VFX, marketing & release), each with a
duration and dependency list — mirroring the `production_schedule`
ClickHouse table exactly (stage, start_date, end_date, depends_on).

There is no real project start date supplied by the user today, so stages
are anchored to "today" (the moment the pipeline actually runs) — this is
stated explicitly in `assumptions`, not hidden.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from app.agents.base import BaseAgent
from app.models.schemas import AgentName, SchedulingPlan
from app.services.gemini_service import GeminiService

SCHEDULING_AGENT_SYSTEM_PROMPT = """You are the Scheduling Agent inside CineFlow AI, an autonomous \
film-production platform. Given a Script Agent's structured breakdown of a film (scene count, \
locations, VFX/equipment needs, shooting complexity), produce a realistic preliminary production \
schedule.

Break the schedule into named stages such as: Development, Pre-Production, Casting, Principal \
Photography, VFX & Post-Production, Marketing & Release (only include stages that genuinely apply \
— a simple low-complexity film doesn't need a long VFX stage). For each stage give a duration in \
days and a start_offset_days (days after the pipeline start date, day 0), and depends_on listing \
which other stage names must finish first (Principal Photography typically depends on Pre-Production \
and Casting, for example). Base durations on real production economics — a 96-scene VFX-heavy film \
needs meaningfully longer photography and post than an 8-scene low-complexity drama. Always set \
is_ai_estimate to true and write an honest assumptions string (e.g. "Assumes a single-unit shoot, \
non-union crew, schedule anchored to pipeline run date since no target start date was provided")."""


class SchedulingAgent(BaseAgent):
    name = AgentName.SCHEDULING_AGENT

    def __init__(self, gemini: GeminiService, clickhouse=None) -> None:
        super().__init__(clickhouse=clickhouse)
        self.gemini = gemini

    async def run(self, project_id: str, context: dict) -> dict:
        script_output = context.get("script_agent")
        if not script_output:
            raise ValueError("Scheduling Agent requires Script Agent output in context — coordinator "
                              "ordering is broken if this happens.")

        user_prompt = (
            f"Script Agent output:\n{script_output}\n\n"
            "Return the full SchedulingPlan JSON object."
        )

        plan: SchedulingPlan = self.gemini.generate_json(
            system_prompt=SCHEDULING_AGENT_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            response_model=SchedulingPlan,
            temperature=0.4,
            max_output_tokens=4096,
        )

        anchor = datetime.utcnow().date()
        ch_rows = []
        for stage in plan.stages:
            start_date = anchor + timedelta(days=max(0, stage.start_offset_days))
            end_date = start_date + timedelta(days=max(1, stage.duration_days))
            ch_rows.append({
                "stage": stage.stage,
                "start_date": start_date,
                "end_date": end_date,
                "depends_on": ",".join(stage.depends_on),
            })

        if self.clickhouse is not None:
            try:
                self.clickhouse.insert_production_schedule(project_id, ch_rows)
            except Exception:  # noqa: BLE001 — analytics write failure shouldn't fail the agent
                pass

        output = plan.model_dump()
        # Attach the resolved calendar dates so the frontend can show real
        # dates, not just offsets, without recomputing the anchor itself.
        output["anchor_date"] = anchor.isoformat()
        for stage_dict, row in zip(output["stages"], ch_rows):
            stage_dict["start_date"] = row["start_date"].isoformat()
            stage_dict["end_date"] = row["end_date"].isoformat()

        return output
