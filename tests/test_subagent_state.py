"""Test SubAgentState enum and AgentInfo dataclass."""
import pytest


def test_state_imports():
    from src.subagent.state import SubAgentState, AgentInfo
    assert SubAgentState is not None
    assert AgentInfo is not None


def test_state_values():
    from src.subagent.state import SubAgentState
    assert SubAgentState.SPAWNING == "spawning"
    assert SubAgentState.READY == "ready"
    assert SubAgentState.RUNNING == "running"
    assert SubAgentState.BLOCKED == "blocked"
    assert SubAgentState.FINISHED == "finished"
    assert SubAgentState.FAILED == "failed"


def test_agent_info_creation():
    from src.subagent.state import AgentInfo, SubAgentState
    info = AgentInfo(
        agent_id="agent-abc",
        name="researcher",
        role="executor",
        task="Research topic X",
        tier="standard",
        tools=["web_search", "web_fetch"],
        skills=["summarize"],
    )
    assert info.agent_id == "agent-abc"
    assert info.state == SubAgentState.SPAWNING
    assert info.iteration == 0
    assert info.cost_cents == 0.0
    assert info.retry_count == 0


def test_agent_info_to_dict():
    from src.subagent.state import AgentInfo
    info = AgentInfo(
        agent_id="agent-abc",
        name="researcher",
        role="executor",
        task="Research",
        tier="standard",
        tools=["web_search"],
        skills=[],
    )
    d = info.to_dict()
    assert d["agent_id"] == "agent-abc"
    assert d["state"] == "spawning"
    assert d["cost_cents"] == 0.0


def test_agent_info_state_transitions():
    from src.subagent.state import AgentInfo, SubAgentState
    info = AgentInfo(
        agent_id="agent-abc",
        name="researcher",
        role="executor",
        task="Research",
        tier="standard",
        tools=[],
        skills=[],
    )
    assert info.state == SubAgentState.SPAWNING
    info.state = SubAgentState.RUNNING
    assert info.state == SubAgentState.RUNNING
