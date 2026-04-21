"""Test StreamEvent factory helpers for agent lifecycle events."""
from src.core.streaming import (
    agent_spawn_event,
    agent_progress_event,
    agent_complete_event,
    agent_failed_event,
    EventType,
)


def test_agent_spawn_event_shape():
    ev = agent_spawn_event(agent_id="agent-abc", name="researcher", role="executor", tier="standard")
    assert ev.type == EventType.AGENT_SPAWN
    assert ev.data["name"] == "researcher"
    assert ev.data["role"] == "executor"
    assert ev.data["tier"] == "standard"
    assert ev.agent_id == "agent-abc"


def test_agent_progress_event_shape():
    ev = agent_progress_event(agent_id="agent-abc", message="Step 2/5", cost_cents=1.5)
    assert ev.type == EventType.AGENT_PROGRESS
    assert ev.data["message"] == "Step 2/5"
    assert ev.data["cost_cents"] == 1.5


def test_agent_complete_event_shape():
    ev = agent_complete_event(agent_id="agent-abc", result="Done!", cost_total_cents=5.0)
    assert ev.type == EventType.AGENT_COMPLETE
    assert ev.data["result"] == "Done!"
    assert ev.data["cost_total_cents"] == 5.0


def test_agent_failed_event_shape():
    ev = agent_failed_event(agent_id="agent-abc", reason="stale_heartbeat", action="retry")
    assert ev.type == EventType.AGENT_FAILED
    assert ev.data["reason"] == "stale_heartbeat"
    assert ev.data["action"] == "retry"
