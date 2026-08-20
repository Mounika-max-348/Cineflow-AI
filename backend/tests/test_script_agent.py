import pytest

from app.agents.script_agent import ScriptAgent
from app.models.schemas import AgentStatus, ScriptAnalysis


class FakeGemini:
    """Stands in for GeminiService in unit tests so we don't need a live API
    key/network to verify the agent's own logic (timing, retry, status
    transitions, ClickHouse call shape). Integration tests that hit the real
    Gemini API live in tests/test_integration_live.py and are skipped unless
    GEMINI_API_KEY is set."""

    def __init__(self, result: ScriptAnalysis):
        self.result = result
        self.calls = 0

    def generate_json(self, **kwargs):
        self.calls += 1
        return self.result


def _sample_analysis() -> ScriptAnalysis:
    return ScriptAnalysis(
        title="Solstice Horizon",
        genre="Sci-Fi",
        subgenre="Drama",
        language="English",
        logline="An astronaut discovers a failing station predicts humanity's future.",
        synopsis="A lone astronaut aboard a decaying orbital station uncovers its true purpose.",
        characters=["Mira Chen", "Station AI 'Solstice'"],
        character_descriptions={"Mira Chen": "Veteran flight engineer, pragmatic and isolated."},
        scene_count=8,
        locations=["Orbital Station Interior", "Earth Mission Control"],
        props=["EVA suit", "Data core"],
        equipment_requirements=["Zero-gravity rig", "LED volume stage"],
        vfx_requirements=["Station exterior CGI", "Holographic UI"],
        shooting_complexity="high",
        estimated_runtime_minutes=118,
        production_complexity="high",
        target_audience="Adults 18-45, sci-fi enthusiasts",
        scene_breakdown=[],
    )


@pytest.mark.asyncio
async def test_script_agent_emits_running_then_completed():
    gemini = FakeGemini(_sample_analysis())
    agent = ScriptAgent(gemini, clickhouse=None)

    events = []
    async for event in agent.execute("proj-1", {"raw_text": "An astronaut...", "input_mode": "idea"}):
        events.append(event)

    assert events[0].status == AgentStatus.RUNNING
    assert events[-1].status == AgentStatus.COMPLETED
    assert events[-1].payload["title"] == "Solstice Horizon"
    assert gemini.calls == 1


@pytest.mark.asyncio
async def test_script_agent_retries_once_then_fails():
    class FailingGemini:
        def __init__(self):
            self.calls = 0

        def generate_json(self, **kwargs):
            self.calls += 1
            raise RuntimeError("simulated Gemini outage")

    gemini = FailingGemini()
    agent = ScriptAgent(gemini, clickhouse=None)

    events = []
    async for event in agent.execute("proj-1", {"raw_text": "x", "input_mode": "idea"}):
        events.append(event)

    statuses = [e.status for e in events]
    assert AgentStatus.RETRYING in statuses
    assert statuses[-1] == AgentStatus.FAILED
    # RUNNING -> RETRYING -> FAILED, and Gemini was called MAX_RETRIES+1 times
    assert gemini.calls == 2
