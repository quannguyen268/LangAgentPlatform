"""Orchestration tools — spawn_agent, recall_agent, monitor_agents, etc.

These tools are given to the master agent so it can manage sub-agents.
The tools operate on a module-level SubAgentRegistry set by init_orchestration_tools.
"""
from __future__ import annotations

import logging
import uuid
from typing import Callable, Optional

from langchain.tools import tool

from .registry import SubAgentRegistry
from .state import AgentInfo, SubAgentState

logger = logging.getLogger(__name__)

# Module-level references initialized by init_orchestration_tools()
_registry: SubAgentRegistry | None = None
_spawner: Callable | None = None          # async (info, **kwargs) → asyncio.Task
_cost_tracker = None                        # CostTracker or None


def init_orchestration_tools(
    registry: SubAgentRegistry,
    spawner: Optional[Callable] = None,
    cost_tracker=None,
) -> None:
    """Initialize module-level references for orchestration tools.

    Args:
        registry: SubAgentRegistry for tracking agents
        spawner: async callable that creates the asyncio.Task for an agent
                 signature: async spawner(info: AgentInfo) → asyncio.Task
        cost_tracker: Optional CostTracker for review_cost
    """
    global _registry, _spawner, _cost_tracker
    _registry = registry
    _spawner = spawner
    _cost_tracker = cost_tracker


@tool
async def spawn_agent(
    name: str,
    role: str,
    task: str,
    tools: list[str],
    tier: str = "standard",
    skills: list[str] | None = None,
) -> str:
    """Spawn a sub-agent to work on a task in the background.

    Args:
        name: Human-readable agent name (e.g., "researcher")
        role: "planner" | "executor" | "evaluator" | custom
        task: The task description for this agent
        tools: List of tool names to make available
        tier: LLM tier ("lite" | "standard" | "advanced" | "expert")
        skills: Optional list of skill names to load

    Returns:
        The spawned agent's ID
    """
    if _registry is None:
        return "Error: orchestration not initialized"

    agent_id = f"agent-{uuid.uuid4().hex[:8]}"
    info = AgentInfo(
        agent_id=agent_id,
        name=name,
        role=role,
        task=task,
        tier=tier,
        tools=list(tools),
        skills=list(skills) if skills else [],
    )

    # Write config to store
    await _registry.agent_store.write_config(agent_id, {
        "role": role,
        "tier": tier,
        "task": task,
        "tools": list(tools),
        "skills": list(skills) if skills else [],
    })

    # Use spawner to create the backing task (or a placeholder if not configured)
    if _spawner:
        task_obj = await _spawner(info)
    else:
        import asyncio
        async def placeholder():
            await asyncio.sleep(0.1)
        task_obj = asyncio.create_task(placeholder())

    _registry.register(info, task_obj)
    logger.info("Spawned agent %s (name=%s, role=%s, tier=%s)", agent_id, name, role, tier)
    return agent_id


@tool
async def recall_agent(agent_id: str) -> str:
    """Terminate a sub-agent and collect its final results.

    Sends a shutdown directive, waits briefly for graceful termination,
    then cancels the task.

    Args:
        agent_id: The ID of the agent to recall
    """
    if _registry is None:
        return "Error: orchestration not initialized"

    info = _registry.get_agent(agent_id)
    if info is None:
        return f"Agent {agent_id} not found"

    # Write shutdown directive (graceful shutdown — GAP-3)
    await _registry.agent_store.write_directive(agent_id, action="shutdown")

    # Read final result if available
    result = await _registry.agent_store.read_result(agent_id)

    # Deregister (cancels task)
    await _registry.deregister(agent_id)

    summary = f"Agent {agent_id} recalled."
    if result:
        summary += f" Final result: {result.get('output', '(no output)')[:200]}"
    return summary


@tool
async def monitor_agents() -> str:
    """Get the status of all active sub-agents.

    Returns a formatted status line for each agent.
    """
    if _registry is None:
        return "Error: orchestration not initialized"

    agents = _registry.list_agents()
    if not agents:
        return "No active sub-agents."

    lines = ["Active sub-agents:"]
    for info in agents:
        state_value = info.state.value if hasattr(info.state, "value") else info.state
        lines.append(
            f"  - {info.agent_id} [{info.name}/{info.role}/{info.tier}] "
            f"state={state_value} "
            f"iter={info.iteration} cost={info.cost_cents:.2f}¢"
        )
    return "\n".join(lines)


@tool
async def assign_task(agent_id: str, task: str) -> str:
    """Send a new task to a running sub-agent via its inbox.

    Args:
        agent_id: The agent to send to
        task: The task description
    """
    if _registry is None:
        return "Error: orchestration not initialized"

    info = _registry.get_agent(agent_id)
    if info is None:
        return f"Agent {agent_id} not found"

    await _registry.agent_store.send_inbox(agent_id, sender="master", message=task)
    return f"Task assigned to {agent_id}: {task[:100]}"


@tool
async def switch_agent_model(agent_id: str, tier: str) -> str:
    """Change the LLM tier of a running sub-agent.

    Args:
        agent_id: The agent to modify
        tier: New tier ("lite" | "standard" | "advanced" | "expert")
    """
    if _registry is None:
        return "Error: orchestration not initialized"

    info = _registry.get_agent(agent_id)
    if info is None:
        return f"Agent {agent_id} not found"

    old_tier = info.tier
    info.tier = tier
    await _registry.agent_store.write_directive(
        agent_id, action="change_tier", params={"tier": tier}
    )
    return f"Agent {agent_id} tier changed: {old_tier} → {tier}"


@tool
async def review_cost() -> str:
    """Get cost breakdown across agents, users, and tiers."""
    if _cost_tracker is None:
        return "Cost tracker not initialized"

    summary = _cost_tracker.summary()
    lines = [
        f"Total: {summary['total_tokens']} tokens, ¢{summary['total_cost_cents']:.2f}",
        f"Calls: {summary['total_calls']}",
    ]
    by_tier = _cost_tracker.by_tier()
    if by_tier:
        lines.append("By tier:")
        for tier, data in by_tier.items():
            lines.append(f"  {tier}: {data['total_tokens']} tokens, ¢{data['total_cost_cents']:.2f}")
    by_user = _cost_tracker.by_user()
    if by_user:
        lines.append("By user:")
        for user, data in by_user.items():
            lines.append(f"  {user}: {data['total_tokens']} tokens, ¢{data['total_cost_cents']:.2f}")
    return "\n".join(lines)
