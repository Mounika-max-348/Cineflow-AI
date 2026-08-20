import pytest

from app.agents.budget_agent import BudgetAgent
from app.models.schemas import AgentStatus, BudgetEstimate, BudgetLineItem


class FakeGemini:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def generate_json(self, **kwargs):
        self.calls += 1
        return self.result


def _sample_estimate() -> BudgetEstimate:
    return BudgetEstimate(
        currency="USD",
        line_items=[
            BudgetLineItem(category="cast", amount=2_700_000),
            BudgetLineItem(category="crew", amount=2_000_000),
            BudgetLineItem(category="vfx", amount=1_500_000),
            BudgetLineItem(category="contingency", amount=680_000),
        ],
        minimum_budget=6_200_000,
        expected_budget=8_400_000,
        maximum_budget=10_100_000,
        confidence_score=78,
        assumptions="Assumes non-union cast, one international location, moderate VFX load.",
    )


@pytest.mark.asyncio
async def test_budget_agent_uses_script_output_and_completes():
    gemini = FakeGemini(_sample_estimate())
    agent = BudgetAgent(gemini, clickhouse=None)

    context = {"script_agent": {"genre": "Sci-Fi", "scene_count": 96}, "country_context": None}
    events = []
    async for event in agent.execute("proj-1", context):
        events.append(event)

    assert events[0].status == AgentStatus.RUNNING
    assert events[-1].status == AgentStatus.COMPLETED
    assert events[-1].payload["expected_budget"] == 8_400_000
    assert gemini.calls == 1


@pytest.mark.asyncio
async def test_budget_agent_fails_without_script_output():
    gemini = FakeGemini(_sample_estimate())
    agent = BudgetAgent(gemini, clickhouse=None)

    events = []
    async for event in agent.execute("proj-1", {}):  # no script_agent key
        events.append(event)

    assert events[-1].status == AgentStatus.FAILED
