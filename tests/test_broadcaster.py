"""Test EventBroadcaster helper around EventHub."""
import asyncio
import pytest
from src.api.websocket import EventHub
from src.subagent.broadcaster import EventBroadcaster


@pytest.mark.asyncio
async def test_broadcaster_spawn_emits_event():
    hub = EventHub()
    b = EventBroadcaster(hub)
    received = []

    async def sub():
        async for ev in hub.subscribe():
            received.append(ev)
            break

    t = asyncio.create_task(sub())
    await asyncio.sleep(0.05)

    b.agent_spawned(agent_id="a1", name="n1", role="executor", tier="standard")
    await asyncio.wait_for(t, timeout=2.0)

    assert len(received) == 1
    assert received[0].type == "agent_spawn"
    assert received[0].data["name"] == "n1"


def test_broadcaster_handles_none_hub():
    """If hub is None, methods should be no-ops, not raise."""
    b = EventBroadcaster(None)
    # Any of these would fail if the hub was required
    b.agent_spawned("a1", "n1", "executor", "standard")
    b.agent_progress("a1", "working", 0.5)
    b.agent_completed("a1", "result", 1.0)
    b.agent_failed("a1", "timeout", "retry")


def test_broadcaster_swallows_broadcast_exceptions():
    """A broken hub.broadcast should log a warning, not crash the caller."""
    class BrokenHub:
        def broadcast(self, event):
            raise RuntimeError("hub is broken")

    b = EventBroadcaster(BrokenHub())
    # Should not raise
    b.agent_spawned("a1", "n1", "executor", "standard")
