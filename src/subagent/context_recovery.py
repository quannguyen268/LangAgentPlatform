"""Context recovery prompt builder (GAP-1).

When a sub-agent is respawned after failure, build a role-scoped recovery
prompt so it can resume with context rather than starting blank.
"""
from __future__ import annotations

import logging

from langgraph.store.base import BaseStore

from .store import AgentStore

logger = logging.getLogger(__name__)


async def build_recovery_context(
    agent_id: str,
    role: str,
    store: BaseStore,
    all_agent_ids: list[str] | None = None,
) -> str:
    """Build a role-scoped recovery prompt for a respawned sub-agent.

    Args:
        agent_id: ID of the agent being recovered
        role: "executor" | "planner" | "evaluator" | custom
        store: BaseStore for reading agent state
        all_agent_ids: Optional list of other agents (for evaluators)

    Returns:
        Multi-line recovery prompt string
    """
    agent_store = AgentStore(store)
    lines = [f"You are resuming after a failure. Your role: {role}"]

    # Task progress (heartbeat iteration + progress message)
    hb = await agent_store.read_heartbeat(agent_id)
    if hb:
        iteration = hb.get("iteration", 0)
        lines.append(f"You were on iteration {iteration} when the failure occurred.")

    prog = await agent_store.read_progress(agent_id)
    if prog:
        lines.append(f"Recent progress: {prog.get('message', '(no progress recorded)')}")

    # Original task
    config = await agent_store.read_config(agent_id)
    if config and config.get("task"):
        lines.append(f"Original task: {config['task']}")

    # Evaluators see team status; executors only see their own context
    if role != "executor" and all_agent_ids:
        lines.append("")
        lines.append("Team status:")
        for other_id in all_agent_ids:
            if other_id == agent_id:
                continue
            other_prog = await agent_store.read_progress(other_id)
            if other_prog:
                lines.append(f"  - {other_id}: {other_prog.get('message', '(no progress)')}")

    lines.append("")
    lines.append("Continue from where you left off.")

    return "\n".join(lines)
