"""DeepAgentsSpawner — create and run a real sub-agent as an asyncio.Task.

For each ``AgentInfo`` passed to ``spawn()``, the spawner:
  1. Builds a DeepAgents instance with that agent's tool subset.
  2. Writes an initial heartbeat and emits ``agent_spawn``.
  3. Invokes the agent with ``info.task`` (optionally augmented by recovery context).
  4. Writes progress + final result to AgentStore and emits ``agent_complete`` /
     ``agent_failed`` to the broadcaster.
  5. Updates SubAgentRegistry state transitions (SPAWNING → RUNNING → FINISHED / FAILED).

Phase 2A limitation: ``iteration`` is written as 0 ("starting") then 1 ("running")
and never incremented during ``inner.ainvoke()`` because the Phase 2A spawner runs
the sub-agent as a single-shot call rather than a per-step stream. HealthMonitor
still detects hangs via heartbeat timestamp staleness. Phase 2B may switch to
``inner.astream()`` and emit ``agent_progress`` events per step.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

from deepagents import create_deep_agent
from langchain_core.messages import AIMessage, HumanMessage

from .broadcaster import EventBroadcaster
from .registry import SubAgentRegistry
from .state import AgentInfo, SubAgentState

logger = logging.getLogger(__name__)


def _extract_last_text(messages: list) -> str:
    """Return the content of the last AIMessage, or '' if none."""
    for m in reversed(messages):
        if isinstance(m, AIMessage):
            content = m.content
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts = [b.get("text", "") for b in content if isinstance(b, dict)]
                return "\n".join(parts)
    return ""


class DeepAgentsSpawner:
    """Runs each sub-agent as a DeepAgents instance inside an asyncio.Task."""

    def __init__(
        self,
        registry: SubAgentRegistry,
        broadcaster: EventBroadcaster,
        base_model: Any,
        tools_by_name: dict[str, Any],
    ):
        self._registry = registry
        self._broadcaster = broadcaster
        self._base_model = base_model
        self._tools_by_name = tools_by_name

    async def spawn(self, info: AgentInfo, recovery_context: Optional[str] = None) -> asyncio.Task:
        """Create the asyncio.Task that runs this sub-agent."""
        task = asyncio.create_task(self._run(info, recovery_context))
        return task

    async def _run(self, info: AgentInfo, recovery_context: Optional[str]) -> None:
        agent_id = info.agent_id
        store = self._registry.agent_store

        try:
            # Resolve tools — error loudly on unknown names (likely a config bug,
            # not a recoverable runtime condition)
            missing = [n for n in info.tools if n not in self._tools_by_name]
            if missing:
                raise ValueError(
                    f"Unknown tools requested by {agent_id}: {missing}. "
                    f"Available: {sorted(self._tools_by_name)}"
                )
            tools = [self._tools_by_name[n] for n in info.tools]

            # Emit spawn + heartbeat
            self._broadcaster.agent_spawned(
                agent_id=agent_id, name=info.name, role=info.role, tier=info.tier,
            )
            await store.write_heartbeat(agent_id, iteration=0, status="starting")

            # Build inner agent (Phase 2A: no nested middleware; keep it simple.
            # Sub-agents intentionally omit checkpointer, interrupt_on, and
            # middleware — those belong to the master graph, not per-sub-agent.)
            inner = create_deep_agent(
                model=self._base_model,
                tools=tools,
            )

            # Compose initial message — prepend recovery context if this is a respawn
            task_text = info.task
            if recovery_context:
                task_text = f"{recovery_context}\n\n---\n\nTask: {info.task}"
            state = {"messages": [HumanMessage(content=task_text)]}

            await store.write_heartbeat(agent_id, iteration=1, status="running")
            # Transition to RUNNING immediately before ainvoke so the state
            # accurately reflects actual execution (not just readiness).
            self._registry.update_state(agent_id, SubAgentState.RUNNING)
            result = await inner.ainvoke(state)

            # Extract output
            output = _extract_last_text(result.get("messages", []))
            await store.write_result(
                agent_id, status="success", output=output, cost_total=info.cost_cents,
            )
            info.result = output
            info.finished_at = time.time()
            self._registry.update_state(agent_id, SubAgentState.FINISHED)
            self._broadcaster.agent_completed(
                agent_id=agent_id, result=output, cost_total_cents=info.cost_cents,
            )
            logger.info("Sub-agent %s completed", agent_id)

        except asyncio.CancelledError:
            logger.info("Sub-agent %s cancelled", agent_id)
            raise
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            info.error = err
            info.finished_at = time.time()
            self._registry.update_state(agent_id, SubAgentState.FAILED)
            try:
                await store.write_result(
                    agent_id, status="failed", output=err, cost_total=info.cost_cents,
                )
            except Exception as store_err:
                logger.warning(
                    "Sub-agent %s: failed to write failure result: %s",
                    agent_id, store_err,
                )
            self._broadcaster.agent_failed(
                agent_id=agent_id, reason=type(e).__name__, action="pending",
            )
            logger.exception("Sub-agent %s failed", agent_id)
