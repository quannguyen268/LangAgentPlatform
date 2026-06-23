"""DeepAgentsSpawner — create and run a real sub-agent as an asyncio.Task.

For each ``AgentInfo`` passed to ``spawn()``, the spawner:
  1. Builds a DeepAgents instance with that agent's tool subset.
  2. Writes an initial heartbeat and emits ``agent_spawn``.
  3. Invokes the agent with ``info.task`` (optionally augmented by recovery context).
  4. Writes progress + final result to AgentStore and emits ``agent_complete`` /
     ``agent_failed`` to the broadcaster.
  5. Updates SubAgentRegistry state transitions (SPAWNING → RUNNING → FINISHED / FAILED).

Execution model: by default the spawner drives the sub-agent via ``inner.astream()``
(streaming), incrementing ``iteration`` and emitting ``agent_progress`` per step, and
honoring a ``shutdown`` directive between steps. Passing ``streaming=False`` (config:
``subagent.streaming``) falls back to a single ``inner.ainvoke()`` call. HealthMonitor
detects hangs via heartbeat timestamp staleness in both modes.
"""
from __future__ import annotations

import asyncio
import logging
import time
from contextlib import aclosing
from typing import Any, Optional

from deepagents import create_deep_agent
from langchain_core.messages import AIMessage, HumanMessage

from .broadcaster import EventBroadcaster
from .registry import SubAgentRegistry
from .state import AgentInfo, SubAgentState

logger = logging.getLogger(__name__)

_PROGRESS_PREVIEW_CHARS = 200


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
        streaming: bool = True,
    ):
        self._registry = registry
        self._broadcaster = broadcaster
        self._base_model = base_model
        self._tools_by_name = tools_by_name
        self._streaming = streaming

    async def spawn(self, info: AgentInfo, recovery_context: Optional[str] = None) -> asyncio.Task:
        """Create the asyncio.Task that runs this sub-agent."""
        task = asyncio.create_task(self._run(info, recovery_context))
        return task

    async def _run(self, info: AgentInfo, recovery_context: Optional[str]) -> None:
        agent_id = info.agent_id
        store = self._registry.agent_store

        try:
            # --- prologue (shared by both execution paths) ---
            missing = [n for n in info.tools if n not in self._tools_by_name]
            if missing:
                raise ValueError(
                    f"Unknown tools requested by {agent_id}: {missing}. "
                    f"Available: {sorted(self._tools_by_name)}"
                )
            tools = [self._tools_by_name[n] for n in info.tools]

            self._broadcaster.agent_spawned(
                agent_id=agent_id, name=info.name, role=info.role, tier=info.tier,
            )
            await store.write_heartbeat(agent_id, iteration=0, status="starting")

            inner = create_deep_agent(
                model=self._base_model,
                tools=tools,
            )

            task_text = info.task
            if recovery_context:
                task_text = f"{recovery_context}\n\n---\n\nTask: {info.task}"
            state = {"messages": [HumanMessage(content=task_text)]}

            await store.write_heartbeat(agent_id, iteration=1, status="running")
            self._registry.update_state(agent_id, SubAgentState.RUNNING)

            # --- execute (streaming default; streaming=False for single-shot fallback) ---
            output, stopped = await self._execute(inner, state, info)

            # --- epilogue (shared) ---
            status = "stopped" if stopped else "success"
            await store.write_result(
                agent_id, status=status, output=output, cost_total=info.cost_cents,
            )
            info.result = output
            info.finished_at = time.time()
            self._registry.update_state(agent_id, SubAgentState.FINISHED)
            self._broadcaster.agent_completed(
                agent_id=agent_id, result=output, cost_total_cents=info.cost_cents,
            )
            logger.info("Sub-agent %s completed (status=%s)", agent_id, status)

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

    async def _execute(self, inner: Any, state: dict, info: AgentInfo) -> tuple[str, bool]:
        """Run the inner agent and return (output, stopped).

        ``stopped`` is True only when a shutdown directive ended a streaming run
        early. Single-shot runs always return stopped=False.
        """
        if self._streaming:
            return await self._stream_run(inner, state, info)
        result = await inner.ainvoke(state)
        return _extract_last_text(result.get("messages", [])), False

    async def _stream_run(self, inner: Any, state: dict, info: AgentInfo) -> tuple[str, bool]:
        """Drive the inner agent turn-by-turn via astream.

        Per chunk: increment iteration, write heartbeat + progress, emit
        agent_progress, and break early if a shutdown directive is pending.
        Uses stream_mode="values" so each chunk is the full state snapshot; the
        last snapshot carries the final messages.
        """
        agent_id = info.agent_id
        store = self._registry.agent_store
        final_state = state
        stopped = False
        saw_step = False

        async with aclosing(inner.astream(state, stream_mode="values")) as stream:
            first = True
            async for chunk in stream:
                final_state = chunk
                if first:
                    # stream_mode="values" echoes the input state as the first
                    # chunk, before any agent step runs — not a step to count.
                    first = False
                    continue
                saw_step = True
                self._registry.increment_iteration(agent_id)
                iteration = self._registry.get_agent(agent_id).iteration
                preview = _extract_last_text(chunk.get("messages", []))[:_PROGRESS_PREVIEW_CHARS]

                await store.write_heartbeat(agent_id, iteration=iteration, status="running")
                await store.write_progress(agent_id, message=preview, cost=info.cost_cents)
                self._broadcaster.agent_progress(
                    agent_id=agent_id, message=preview, cost_cents=info.cost_cents,
                )

                directive = await store.read_directive(agent_id)
                if directive and directive.get("action") == "shutdown":
                    await store.clear_directive(agent_id)
                    stopped = True
                    logger.info("Sub-agent %s received shutdown directive; stopping", agent_id)
                    break

        if not stopped and not saw_step:
            raise RuntimeError(f"Sub-agent {agent_id}: astream produced no steps")

        return _extract_last_text(final_state.get("messages", [])), stopped
