"""
Script Agent — spec section 7.

Takes the raw movie idea or screenplay text and returns a fully structured
ScriptAnalysis (never unstructured prose). For screenplay input we instruct
Gemini to do scene-level extraction (scene number, INT/EXT, day/night,
characters, props, equipment, VFX, complexity); for a short idea we ask it
to infer a reasonable scene structure explicitly labelled as an estimate.
"""
from __future__ import annotations

from app.agents.base import BaseAgent
from app.models.schemas import AgentName, InputMode, ScriptAnalysis
from app.services.gemini_service import GeminiService

SCRIPT_AGENT_SYSTEM_PROMPT = """You are the Script Agent inside CineFlow AI, an autonomous \
film-production platform. You analyze a movie idea or screenplay and output ONLY structured \
production data — never freeform prose outside the JSON schema.

If given a full screenplay, perform deep scene-level extraction: enumerate real scenes with \
location, INT/EXT, day/night, characters present, props, special equipment, VFX needs, and a \
per-scene shooting-complexity rating (low/medium/high).

If given only a short movie idea (not a full screenplay), infer a plausible scene structure and \
production requirements, but keep scene_breakdown shorter (5-10 representative scenes) since this \
is an estimate, not an extraction from real script pages. Be realistic about production_complexity \
and shooting_complexity — do not default everything to 'medium'."""


class ScriptAgent(BaseAgent):
    name = AgentName.SCRIPT_AGENT

    def __init__(self, gemini: GeminiService, clickhouse=None) -> None:
        super().__init__(clickhouse=clickhouse)
        self.gemini = gemini

    async def run(self, project_id: str, context: dict) -> dict:
        raw_text: str = context["raw_text"]
        input_mode: str = context.get("input_mode", InputMode.IDEA.value)

        user_prompt = (
            f"Input mode: {input_mode}\n\n"
            f"Content:\n{raw_text}\n\n"
            "Return the full ScriptAnalysis JSON object."
        )

        analysis: ScriptAnalysis = self.gemini.generate_json(
            system_prompt=SCRIPT_AGENT_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            response_model=ScriptAnalysis,
            temperature=0.5,
            max_output_tokens=8192,
        )
        return analysis.model_dump()
