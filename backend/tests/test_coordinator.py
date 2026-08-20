from app.agents.coordinator import CoordinatorAgent
from app.models.schemas import AgentName, ExecutionPlan, InputMode, PlannedAgentStep, ProjectCreateRequest


class FakeGemini:
    def __init__(self, plan: ExecutionPlan):
        self.plan = plan

    def generate_json(self, **kwargs):
        return self.plan


def test_coordinator_forces_script_agent_first_even_if_gemini_orders_it_wrong():
    # Simulate Gemini returning a plan with script_agent NOT first.
    bad_order_plan = ExecutionPlan(
        project_id="placeholder",
        steps=[
            PlannedAgentStep(name=AgentName.BUDGET_AGENT, reason="need cost", depends_on=[AgentName.SCRIPT_AGENT]),
            PlannedAgentStep(name=AgentName.SCRIPT_AGENT, reason="parse idea", depends_on=[]),
        ],
        notes="test plan",
    )
    coordinator = CoordinatorAgent(FakeGemini(bad_order_plan))
    request = ProjectCreateRequest(input_mode=InputMode.IDEA, raw_text="A story about a lighthouse keeper.")

    plan = coordinator.build_execution_plan("proj-42", request)

    assert plan.steps[0].name == AgentName.SCRIPT_AGENT
    assert plan.project_id == "proj-42"
