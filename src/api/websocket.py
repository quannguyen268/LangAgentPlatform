# src/api/websocket.py
"""WebSocket event broadcasting for real-time StreamEvent delivery.

EventHub manages subscribers. Each WebSocket connection subscribes
to receive StreamEvents. The hub broadcasts events to all subscribers.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator

from aiohttp import web

from ..core.streaming import StreamEvent

logger = logging.getLogger(__name__)


class EventHub:
    """Fan-out StreamEvents to multiple WebSocket subscribers."""

    def __init__(self):
        self._queues: list[asyncio.Queue[StreamEvent | None]] = []

    @property
    def subscriber_count(self) -> int:
        return len(self._queues)

    def broadcast(self, event: StreamEvent) -> None:
        """Send an event to all subscribers."""
        for q in self._queues:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass  # Drop if subscriber is slow

    async def subscribe(self) -> AsyncIterator[StreamEvent]:
        """Async iterator that yields events. Cleans up on exit.

        Uses asyncio.ensure_future so the pending queue.get() Task is
        cancelled automatically when the caller's aclose() is invoked
        (e.g. via ``break`` in an ``async for`` loop).
        """
        queue: asyncio.Queue[StreamEvent | None] = asyncio.Queue(maxsize=1000)
        self._queues.append(queue)
        get_task: asyncio.Task | None = None
        try:
            while True:
                get_task = asyncio.ensure_future(queue.get())
                event = await get_task
                get_task = None
                if event is None:
                    break
                yield event
        except GeneratorExit:
            # Raised by aclose() — cancel the in-flight get task
            if get_task is not None:
                get_task.cancel()
                try:
                    await get_task
                except (asyncio.CancelledError, Exception):
                    pass
        finally:
            if queue in self._queues:
                self._queues.remove(queue)

    def close_all(self) -> None:
        """Signal all subscribers to disconnect."""
        for q in self._queues:
            try:
                q.put_nowait(None)
            except asyncio.QueueFull:
                pass


async def websocket_handler(request: web.Request) -> web.WebSocketResponse:
    """aiohttp WebSocket handler that streams events to connected clients."""
    hub: EventHub = request.app["event_hub"]
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    logger.info("WebSocket client connected (total: %d)", hub.subscriber_count + 1)

    try:
        async for event in hub.subscribe():
            if ws.closed:
                break
            await ws.send_json(event.to_dict())
    except Exception as e:
        logger.debug("WebSocket error: %s", e)
    finally:
        logger.info("WebSocket client disconnected (total: %d)", hub.subscriber_count)

    return ws


def setup_websocket(app: web.Application, hub: EventHub) -> None:
    """Register WebSocket route and store hub on app."""
    app["event_hub"] = hub
    app.router.add_get("/ws", websocket_handler)
