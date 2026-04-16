"""Test AgentState schema and defaults."""
import pytest

def test_agent_state_imports():
    from src.core.state import AgentState
    assert AgentState is not None

def test_agent_state_has_required_fields():
    from src.core.state import AgentState
    state = AgentState(messages=[])
    assert state.active_tier == "standard"
    assert state.session_id == ""
    assert state.channel == ""
    assert state.user_id == ""
    assert state.memory_context == ""
    assert state.skills_summary == ""
    assert state.active_sub_agents == {}
    assert state.pending_tasks == []
    assert state.tool_permissions == {}
    assert state.cost_this_session == 0.0
    assert state.cost_budget is None

def test_agent_state_inherits_messages_state():
    from src.core.state import AgentState
    from langgraph.graph import MessagesState
    assert issubclass(AgentState, MessagesState)

def test_agent_state_with_custom_values():
    from src.core.state import AgentState
    state = AgentState(messages=[], active_tier="expert", user_id="user123", cost_budget=500.0)
    assert state.active_tier == "expert"
    assert state.user_id == "user123"
    assert state.cost_budget == 500.0
