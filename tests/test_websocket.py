# tests/test_websocket.py
"""Test WebSocket event broadcasting."""
import pytest
import asyncio
import json


def test_event_hub_imports():
    from src.api.websocket import EventHub
    assert EventHub is not None


@pytest.mark.asyncio
async def test_event_hub_subscribe_and_broadcast():
    from src.api.websocket import EventHub
    from src.core.streaming import token_event

    hub = EventHub()
    received = []

    async def subscriber():
        async for event in hub.subscribe():
            received.append(event)
            if len(received) >= 2:
                break

    # Start subscriber
    task = asyncio.create_task(subscriber())

    # Give subscriber time to register
    await asyncio.sleep(0.05)

    # Broadcast events
    hub.broadcast(token_event("Hello", user_id="u1"))
    hub.broadcast(token_event("World", user_id="u1"))

    await asyncio.wait_for(task, timeout=2.0)
    assert len(received) == 2
    assert received[0].data["delta"] == "Hello"
    assert received[1].data["delta"] == "World"


@pytest.mark.asyncio
async def test_event_hub_multiple_subscribers():
    from src.api.websocket import EventHub
    from src.core.streaming import done_event

    hub = EventHub()
    counts = [0, 0]

    async def sub(idx):
        async for event in hub.subscribe():
            counts[idx] += 1
            break

    t1 = asyncio.create_task(sub(0))
    t2 = asyncio.create_task(sub(1))
    await asyncio.sleep(0.05)

    hub.broadcast(done_event(user_id="u1"))
    await asyncio.wait_for(asyncio.gather(t1, t2), timeout=2.0)

    assert counts[0] == 1
    assert counts[1] == 1


@pytest.mark.asyncio
async def test_event_hub_unsubscribe_on_exit():
    """Verify subscriber_count returns to 0 after a subscriber breaks out."""
    from src.api.websocket import EventHub
    from src.core.streaming import token_event
    hub = EventHub()

    done = asyncio.Event()

    async def one_shot():
        async for event in hub.subscribe():
            break  # Exit after first event
        done.set()

    task = asyncio.create_task(one_shot())
    # Yield to let the subscriber register and start waiting
    await asyncio.sleep(0.05)
    assert hub.subscriber_count == 1

    # Wake the subscriber so it can break and clean up
    hub.broadcast(token_event("trigger", user_id="u1"))
    await asyncio.wait_for(done.wait(), timeout=2.0)

    assert hub.subscriber_count == 0
    await task
