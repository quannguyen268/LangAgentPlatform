"""BaseStore namespace helpers for master ↔ sub-agent communication.

Namespaces:
    ("agents", "{agent_id}") — Per-agent data (config, heartbeat, progress, result, inbox, directive)
    ("teams", "{team_id}")    — Per-team data (config, task_board, cost) — Phase 2A

All methods are async and use LangGraph's BaseStore (InMemoryStore for dev,
SQLite/Postgres-backed in production).
"""
from __future__ import annotations

import time
from typing import Any

from langgraph.store.base import BaseStore


class AgentStore:
    """Typed wrapper over BaseStore for sub-agent communication."""

    def __init__(self, store: BaseStore):
        self._store = store

    # ── Config (written by master at spawn) ──

    async def write_config(self, agent_id: str, config: dict) -> None:
        await self._store.aput(("agents", agent_id), "config", config)

    async def read_config(self, agent_id: str) -> dict | None:
        item = await self._store.aget(("agents", agent_id), "config")
        return item.value if item else None

    # ── Heartbeat (written by sub-agent periodically) ──

    async def write_heartbeat(self, agent_id: str, iteration: int = 0, status: str = "running") -> None:
        await self._store.aput(("agents", agent_id), "heartbeat", {
            "timestamp": time.time(),
            "iteration": iteration,
            "status": status,
        })

    async def read_heartbeat(self, agent_id: str) -> dict | None:
        item = await self._store.aget(("agents", agent_id), "heartbeat")
        return item.value if item else None

    # ── Progress (written by sub-agent after each step) ──

    async def write_progress(self, agent_id: str, message: str, cost: float = 0.0) -> None:
        await self._store.aput(("agents", agent_id), "progress", {
            "timestamp": time.time(),
            "message": message,
            "cost": cost,
        })

    async def read_progress(self, agent_id: str) -> dict | None:
        item = await self._store.aget(("agents", agent_id), "progress")
        return item.value if item else None

    # ── Result (written by sub-agent on completion) ──

    async def write_result(self, agent_id: str, status: str, output: str, cost_total: float = 0.0) -> None:
        await self._store.aput(("agents", agent_id), "result", {
            "timestamp": time.time(),
            "status": status,
            "output": output,
            "cost_total": cost_total,
        })

    async def read_result(self, agent_id: str) -> dict | None:
        item = await self._store.aget(("agents", agent_id), "result")
        return item.value if item else None

    # ── Directive (master → agent, e.g., shutdown, change_tier) ──

    async def write_directive(self, agent_id: str, action: str, params: dict | None = None) -> None:
        await self._store.aput(("agents", agent_id), "directive", {
            "timestamp": time.time(),
            "action": action,
            "params": params or {},
        })

    async def read_directive(self, agent_id: str) -> dict | None:
        item = await self._store.aget(("agents", agent_id), "directive")
        return item.value if item else None

    async def clear_directive(self, agent_id: str) -> None:
        """Delete the directive for an agent (called after processing)."""
        await self._store.adelete(("agents", agent_id), "directive")

    # ── Inbox (master/agents → this agent) ──

    async def send_inbox(self, agent_id: str, sender: str, message: str) -> None:
        """Append a message to the agent's inbox, preserving insertion order."""
        current = await self._store.aget(("agents", agent_id), "inbox")
        messages = current.value if current else []
        messages.append({
            "timestamp": time.time(),
            "from": sender,
            "message": message,
        })
        await self._store.aput(("agents", agent_id), "inbox", messages)

    async def drain_inbox(self, agent_id: str) -> list[dict]:
        """Read and clear the agent's inbox. Returns empty list if already drained."""
        current = await self._store.aget(("agents", agent_id), "inbox")
        messages = current.value if current else []
        if messages:
            await self._store.aput(("agents", agent_id), "inbox", [])
        return messages
