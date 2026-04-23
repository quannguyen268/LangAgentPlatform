"""EventBroadcaster — thin facade over EventHub for sub-agent lifecycle events.

Every path that creates, updates, completes, or fails a sub-agent goes through
this class. Consolidating emission here keeps event shape consistent and makes
it trivial to stub in tests (pass None for the hub).
"""
from __future__ import annotations

import logging
from typing import Optional

from ..api.websocket import EventHub
from ..core.streaming import (
    agent_spawn_event,
    agent_progress_event,
    agent_complete_event,
    agent_failed_event,
)

logger = logging.getLogger(__name__)


class EventBroadcaster:
    """Emit sub-agent lifecycle events to an EventHub (or no-op if hub is None)."""

    def __init__(self, hub: Optional[EventHub]):
        self._hub = hub
        if hub is None:
            # Make the no-op path observable so a mis-wired production
            # deployment doesn't silently drop every lifecycle event.
            logger.info("EventBroadcaster: no hub wired; lifecycle events will be dropped")

    def set_hub(self, hub: Optional[EventHub]) -> None:
        """Swap in (or out) the EventHub after construction.

        Useful for wiring: callers that construct the broadcaster before the
        hub exists (e.g., create_agent) can attach the hub later without
        threading a new dependency through every constructor.
        """
        self._hub = hub
        logger.info("EventBroadcaster: hub %s", "attached" if hub else "cleared")

    def _emit(self, event) -> None:
        if self._hub is None:
            return
        try:
            self._hub.broadcast(event)
        except Exception as e:
            logger.warning("EventBroadcaster: broadcast failed: %s", e)

    def agent_spawned(self, agent_id: str, name: str, role: str, tier: str, user_id: str = "") -> None:
        self._emit(agent_spawn_event(agent_id=agent_id, name=name, role=role, tier=tier, user_id=user_id))

    def agent_progress(self, agent_id: str, message: str, cost_cents: float = 0.0, user_id: str = "") -> None:
        self._emit(agent_progress_event(agent_id=agent_id, message=message, cost_cents=cost_cents, user_id=user_id))

    def agent_completed(self, agent_id: str, result: str, cost_total_cents: float = 0.0, user_id: str = "") -> None:
        self._emit(agent_complete_event(agent_id=agent_id, result=result, cost_total_cents=cost_total_cents, user_id=user_id))

    def agent_failed(self, agent_id: str, reason: str, action: str, user_id: str = "") -> None:
        self._emit(agent_failed_event(agent_id=agent_id, reason=reason, action=action, user_id=user_id))
