"""Test StreamEvent types and factory functions."""
import pytest

def test_stream_event_imports():
    from src.core.streaming import StreamEvent, EventType
    assert StreamEvent is not None

def test_event_types_defined():
    from src.core.streaming import EventType
    assert EventType.TOKEN == "token"
    assert EventType.THINKING == "thinking"
    assert EventType.TOOL_CALL_START == "tool_call_start"
    assert EventType.TOOL_CALL_END == "tool_call_end"
    assert EventType.TOOL_ERROR == "tool_error"
    assert EventType.TIER_SWITCH == "tier_switch"
    assert EventType.APPROVAL_REQUEST == "approval_request"
    assert EventType.COST_UPDATE == "cost_update"
    assert EventType.ERROR == "error"
    assert EventType.DONE == "done"

def test_stream_event_creation():
    from src.core.streaming import StreamEvent, EventType
    event = StreamEvent(type=EventType.TOKEN, data={"delta": "Hello"}, agent_id="master", user_id="user123")
    assert event.type == "token"
    assert event.data == {"delta": "Hello"}
    assert event.timestamp > 0

def test_stream_event_to_dict():
    from src.core.streaming import StreamEvent, EventType
    event = StreamEvent(type=EventType.DONE, data={}, agent_id="master", user_id="user123")
    d = event.to_dict()
    assert d["type"] == "done"
    assert "timestamp" in d

def test_token_event_factory():
    from src.core.streaming import token_event
    event = token_event("Hello", user_id="u1")
    assert event.type == "token"
    assert event.data["delta"] == "Hello"

def test_tool_call_start_factory():
    from src.core.streaming import tool_call_start_event
    event = tool_call_start_event("web_search", {"query": "test"}, user_id="u1")
    assert event.type == "tool_call_start"
    assert event.data["name"] == "web_search"

def test_cost_update_factory():
    from src.core.streaming import cost_update_event
    event = cost_update_event(prompt_tokens=100, completion_tokens=50, cost_cents=1.5, tier="standard", user_id="u1")
    assert event.type == "cost_update"
    assert event.data["prompt_tokens"] == 100
    assert event.data["cost_cents"] == 1.5
