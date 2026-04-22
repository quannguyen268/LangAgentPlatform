"""Test BudgetEnforcer — per-agent and per-session budget checks."""
from src.subagent.budget import BudgetEnforcer, BudgetDecision
from src.subagent.state import AgentInfo


def _info(cost: float) -> AgentInfo:
    i = AgentInfo(
        agent_id="a1", name="n1", role="executor", task="t",
        tier="standard", tools=[], skills=[],
    )
    i.cost_cents = cost
    return i


def test_budget_ok_under_warn_threshold():
    enforcer = BudgetEnforcer(agent_budget_cents=100.0, warn_threshold=0.8)
    assert enforcer.check_agent(_info(50.0)) == BudgetDecision.OK


def test_budget_warn_between_warn_and_hard():
    enforcer = BudgetEnforcer(agent_budget_cents=100.0, warn_threshold=0.8)
    # 80.0 is the warn threshold (0.8 * 100)
    assert enforcer.check_agent(_info(85.0)) == BudgetDecision.WARN


def test_budget_over_at_or_above_hard():
    enforcer = BudgetEnforcer(agent_budget_cents=100.0, warn_threshold=0.8)
    assert enforcer.check_agent(_info(100.0)) == BudgetDecision.OVER
    assert enforcer.check_agent(_info(200.0)) == BudgetDecision.OVER


def test_budget_disabled_returns_ok():
    """None budget means no enforcement — always OK."""
    enforcer = BudgetEnforcer(agent_budget_cents=None, warn_threshold=0.8)
    assert enforcer.check_agent(_info(9999.0)) == BudgetDecision.OK
