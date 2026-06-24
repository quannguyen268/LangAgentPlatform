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
from deepagents.backends import FilesystemBackend
from langchain_core.messages import AIMessage, HumanMessage

from ..tools.model_router import set_active_tier
from .broadcaster import EventBroadcaster
from .registry import SubAgentRegistry
from .state import AgentInfo, SubAgentState

logger = logging.getLogger(__name__)

_PROGRESS_PREVIEW_CHARS = 200
_MAX_SEGMENTS = 50  # safety cap on inbox-driven re-runs of a single sub-agent


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
        workspace: str | None = None,
        skills_dirs: list[str] | None = None,
        cost_tracker: Any = None,
    ):
        self._registry = registry
        self._broadcaster = broadcaster
        self._base_model = base_model
        self._tools_by_name = tools_by_name
        self._streaming = streaming
        self._workspace = workspace
        self._skills_dirs = skills_dirs
        self._cost_tracker = cost_tracker

    def _build_inner(self, info: AgentInfo) -> Any:
        """Construct the inner DeepAgents instance for this agent's current config.

        Rebuilt each segment so tool changes (subscribe_tool/unsubscribe_tool)
        take effect. Raises ValueError on an unknown tool name — a config bug,
        surfaced loudly (and create_deep_agent is not called).
        """
        missing = [n for n in info.tools if n not in self._tools_by_name]
        if missing:
            raise ValueError(
                f"Unknown tools requested by {info.agent_id}: {missing}. "
                f"Available: {sorted(self._tools_by_name)}"
            )
        tools = [self._tools_by_name[n] for n in info.tools]
        kwargs: dict = {"model": self._base_model, "tools": tools}
        if self._workspace:
            kwargs["backend"] = FilesystemBackend(root_dir=self._workspace, virtual_mode=True)
        if self._skills_dirs:
            kwargs["skills"] = self._skills_dirs
        return create_deep_agent(**kwargs)

    @staticmethod
    def _skills_hint(info: AgentInfo) -> str | None:
        """A prompt nudge listing the agent's subscribed skills, or None."""
        if not info.skills:
            return None
        return f"Prioritize these skills for this work: {', '.join(info.skills)}."

    def _record_costs(self, info: AgentInfo, new_messages: list) -> None:
        """Record usage for any newly produced AIMessages, accruing info.cost_cents.

        Token counts come from ``usage_metadata``; the cents are computed by the
        CostTracker from the message's model name (0.0 if the model is not in the
        pricing table). No-op when no cost tracker is wired.
        """
        if self._cost_tracker is None:
            return
        for m in new_messages:
            if not isinstance(m, AIMessage):
                continue
            usage = getattr(m, "usage_metadata", None)
            if not usage:
                continue
            meta = m.response_metadata or {}
            model = meta.get("model_name") or meta.get("model") or ""
            cost = self._cost_tracker.record(
                provider="",
                model=model,
                prompt_tokens=usage.get("input_tokens", 0) or 0,
                completion_tokens=usage.get("output_tokens", 0) or 0,
                user_id="subagent",   # spawning user id not threaded yet (future work)
                tier=info.tier,
                agent_id=info.agent_id,
            )
            if cost == 0.0 and model:
                logger.debug(
                    "_record_costs: no pricing for model %r; tokens counted, cost=0", model
                )
            info.cost_cents += cost

    async def spawn(self, info: AgentInfo, recovery_context: Optional[str] = None) -> asyncio.Task:
        """Create the asyncio.Task that runs this sub-agent."""
        task = asyncio.create_task(self._run(info, recovery_context))
        return task

    async def _run(self, info: AgentInfo, recovery_context: Optional[str]) -> None:
        agent_id = info.agent_id
        store = self._registry.agent_store

        try:
            # --- prologue (shared by both execution paths) ---
            # Validate tools up-front (also re-checked per build in _build_inner).
            missing = [n for n in info.tools if n not in self._tools_by_name]
            if missing:
                raise ValueError(
                    f"Unknown tools requested by {agent_id}: {missing}. "
                    f"Available: {sorted(self._tools_by_name)}"
                )

            self._broadcaster.agent_spawned(
                agent_id=agent_id, name=info.name, role=info.role, tier=info.tier,
            )
            await store.write_heartbeat(agent_id, iteration=0, status="starting")

            # Scope this sub-agent's tier to its own asyncio task. Effective only
            # when base_model is the RoutingChatModel; a harmless no-op otherwise.
            set_active_tier(info.tier)

            task_text = info.task
            if recovery_context:
                task_text = f"{recovery_context}\n\n---\n\nTask: {info.task}"
            hint = self._skills_hint(info)
            if hint:
                # Hint leads so it reads as a directive ahead of the recovery/task narrative.
                task_text = f"{hint}\n\n{task_text}"
            messages = [HumanMessage(content=task_text)]

            await store.write_heartbeat(agent_id, iteration=1, status="running")
            self._registry.update_state(agent_id, SubAgentState.RUNNING)

            # --- execute (streaming default; streaming=False for single-shot fallback) ---
            output, stopped = await self._execute(info, messages)

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

    async def _execute(self, info: AgentInfo, messages: list) -> tuple[str, bool]:
        """Run the inner agent and return (output, stopped).

        ``stopped`` is True only when a shutdown directive ended a streaming run
        early. Single-shot runs always return stopped=False.
        """
        if self._streaming:
            return await self._stream_run(info, messages)
        inner = self._build_inner(info)
        result = await inner.ainvoke({"messages": messages})
        msgs = result.get("messages", [])
        # ainvoke returns a single final state (no cumulative re-emission), so
        # every AIMessage appears once — no dedup needed here.
        self._record_costs(info, msgs)
        return _extract_last_text(msgs), False

    async def _stream_run(self, info: AgentInfo, messages: list) -> tuple[str, bool]:
        """Outer loop: run streaming segments until the inbox is empty or shutdown.

        Each segment is a full ``inner.astream`` run rebuilt from the agent's
        current config (so subscribe_tool changes apply). Between segments — a
        guaranteed-clean boundary — the inbox is drained: queued tasks become new
        HumanMessages and trigger another segment. tier changes apply live via
        the per-chunk ``change_tier`` directive.
        """
        agent_id = info.agent_id
        store = self._registry.agent_store
        first_segment = True
        segment_count = 0

        while True:
            segment_count += 1
            if segment_count > _MAX_SEGMENTS:
                logger.warning(
                    "Sub-agent %s exceeded %d segments; terminating", agent_id, _MAX_SEGMENTS
                )
                return _extract_last_text(messages), True   # mark as stopped, not a clean finish
            inner = self._build_inner(info)
            messages, stopped, saw_step = await self._run_segment(inner, messages, info)

            if stopped:                       # shutdown directive mid-segment
                return _extract_last_text(messages), True
            if not saw_step:
                if first_segment:
                    raise RuntimeError(f"Sub-agent {agent_id}: astream produced no steps")
                logger.warning("Sub-agent %s: a follow-up segment produced no steps", agent_id)
            first_segment = False

            # Clean boundary: drain inbox for follow-up work.
            inbox = await store.drain_inbox(agent_id)
            if not inbox:
                return _extract_last_text(messages), False
            for item in inbox:
                messages = messages + [HumanMessage(content=item["message"])]

    async def _run_segment(self, inner: Any, messages: list, info: AgentInfo) -> tuple[list, bool, bool]:
        """Stream one inner run. Returns (final_messages, stopped, saw_step)."""
        agent_id = info.agent_id
        store = self._registry.agent_store
        state = {"messages": messages}
        final_state = state
        stopped = False
        saw_step = False
        counted = 0
        costed_ids: set[int] = set()

        async with aclosing(inner.astream(state, stream_mode="values")) as stream:
            first = True
            async for chunk in stream:
                final_state = chunk
                msgs = chunk.get("messages", [])
                if first:
                    # stream_mode="values" echoes the input state first — not a step.
                    # Seed costed_ids with every already-present message so prior-step
                    # AND prior-segment (carried-forward) messages are never re-costed.
                    # id()-identity is stable because langgraph's add_messages reuses
                    # prior message OBJECTS across cumulative snapshots; the carried-
                    # forward list reuses the same objects across segments too.
                    first = False
                    costed_ids = {id(m) for m in msgs}
                    continue
                saw_step = True
                new_msgs = [m for m in msgs[counted:] if id(m) not in costed_ids]
                self._record_costs(info, new_msgs)
                for m in new_msgs:
                    costed_ids.add(id(m))
                counted = len(msgs)
                self._registry.increment_iteration(agent_id)
                iteration = self._registry.get_agent(agent_id).iteration
                preview = _extract_last_text(msgs)[:_PROGRESS_PREVIEW_CHARS]

                await store.write_heartbeat(agent_id, iteration=iteration, status="running")
                await store.write_progress(agent_id, message=preview, cost=info.cost_cents)
                self._broadcaster.agent_progress(
                    agent_id=agent_id, message=preview, cost_cents=info.cost_cents,
                )

                directive = await store.read_directive(agent_id)
                if directive:
                    action = directive.get("action")
                    if action == "shutdown":
                        await store.clear_directive(agent_id)
                        stopped = True
                        logger.info("Sub-agent %s received shutdown directive; stopping", agent_id)
                        break
                    if action == "change_tier":
                        new_tier = directive.get("params", {}).get("tier")
                        if new_tier:
                            set_active_tier(new_tier)
                            logger.info("Sub-agent %s tier → %s (live)", agent_id, new_tier)
                        await store.clear_directive(agent_id)

        return final_state.get("messages", []), stopped, saw_step
