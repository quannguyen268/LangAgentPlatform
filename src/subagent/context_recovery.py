"""Context recovery prompt builder (GAP-1).

When a sub-agent is respawned after failure, build a role-scoped recovery
prompt so it can resume with context rather than starting blank.
"""
from __future__ import annotations

from langgraph.store.base import BaseStore

from .store import AgentStore


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

    # Heartbeat iteration (only informative if we'd started running)
    hb = await agent_store.read_heartbeat(agent_id)
    if hb and hb.get("iteration", 0) > 0:
        lines.append(
            f"You were on iteration {hb['iteration']} when the failure occurred."
        )

    # Recent progress (skip empty messages to avoid bare "Recent progress: " line)
    prog = await agent_store.read_progress(agent_id)
    if prog and prog.get("message"):
        lines.append(f"Recent progress: {prog['message']}")

    # Original task
    config = await agent_store.read_config(agent_id)
    if config and config.get("task"):
        lines.append(f"Original task: {config['task']}")

    # Team status — only non-executors with a peer list and at least one
    # teammate with reportable progress get this section.
    if role != "executor" and all_agent_ids:
        team_lines = []
        for other_id in all_agent_ids:
            if other_id == agent_id:
                continue
            other_prog = await agent_store.read_progress(other_id)
            if other_prog and other_prog.get("message"):
                team_lines.append(f"  - {other_id}: {other_prog['message']}")
        if team_lines:
            lines.append("")
            lines.append("Team status:")
            lines.extend(team_lines)

    lines.append("")
    lines.append("Continue from where you left off.")

    return "\n".join(lines)
