"""Test RecoveryChain — priority-chain recovery."""
import pytest
from langgraph.store.memory import InMemoryStore


def test_recovery_imports():
    from src.subagent.recovery import RecoveryChain, RecoveryAction
    assert RecoveryChain is not None
    assert RecoveryAction is not None


def test_recovery_action_values():
    from src.subagent.recovery import RecoveryAction
    assert RecoveryAction.RETRY == "retry"
    assert RecoveryAction.ESCALATE == "escalate"
    assert RecoveryAction.REASSIGN == "reassign"
    assert RecoveryAction.ABORT == "abort"


def test_next_tier():
    from src.subagent.recovery import next_tier
    assert next_tier("lite") == "standard"
    assert next_tier("standard") == "advanced"
    assert next_tier("advanced") == "expert"
    assert next_tier("expert") is None  # Top tier


def test_next_tier_unknown():
    from src.subagent.recovery import next_tier
    assert next_tier("bogus") is None


def test_decide_action_first_retry():
    """First failure → RETRY."""
    from src.subagent.recovery import RecoveryChain
    from src.subagent.state import AgentInfo

    chain = RecoveryChain(max_retries=1)
    info = AgentInfo(agent_id="a1", name="n", role="executor", task="t", tier="standard", tools=[], skills=[])
    info.retry_count = 0
    action = chain.decide_action(info)
    assert action.value == "retry"


def test_decide_action_after_retries_escalate():
    """After max retries at same tier → ESCALATE."""
    from src.subagent.recovery import RecoveryChain
    from src.subagent.state import AgentInfo

    chain = RecoveryChain(max_retries=1)
    info = AgentInfo(agent_id="a1", name="n", role="executor", task="t", tier="standard", tools=[], skills=[])
    info.retry_count = 1  # Already retried once
    action = chain.decide_action(info)
    assert action.value == "escalate"


def test_decide_action_expert_tier_reassign():
    """At expert tier with retries exhausted → REASSIGN."""
    from src.subagent.recovery import RecoveryChain
    from src.subagent.state import AgentInfo

    chain = RecoveryChain(max_retries=1)
    info = AgentInfo(agent_id="a1", name="n", role="executor", task="t", tier="expert", tools=[], skills=[])
    info.retry_count = 1
    action = chain.decide_action(info)
    assert action.value == "reassign"


def test_decide_action_after_reassign_abort():
    """After 3+ failure cycles → ABORT."""
    from src.subagent.recovery import RecoveryChain
    from src.subagent.state import AgentInfo

    chain = RecoveryChain(max_retries=1)
    info = AgentInfo(agent_id="a1", name="n", role="executor", task="t", tier="expert", tools=[], skills=[])
    info.retry_count = 5  # Way over
    action = chain.decide_action(info)
    assert action.value == "abort"
