"""Sub-agent system — registry, orchestration tools, health monitoring, recovery.

## Public API

Importable directly from `src.subagent`:

    # Data types
    SubAgentState, AgentInfo
    FailureReason, RecoveryAction

    # Infrastructure
    SubAgentRegistry, AgentStore
    HealthMonitor, RecoveryChain, next_tier
    build_recovery_context

    # Orchestration tools (@tool-decorated, given to the master agent)
    init_orchestration_tools
    spawn_agent, recall_agent, monitor_agents,
    assign_task, switch_agent_model, review_cost

## Cross-module contracts

- **Source of truth for liveness:** sub-agents write heartbeats to BaseStore via
  ``AgentStore.write_heartbeat``. The in-memory ``AgentInfo.last_heartbeat`` /
  ``AgentInfo.iteration`` fields are a cache. Call
  ``SubAgentRegistry.sync_from_store()`` before ``HealthMonitor.check_all()``
  to refresh the cache — ``main.py``'s health loop does this.

- **State transitions:** mutate ``AgentInfo.state`` only via
  ``SubAgentRegistry.update_state()`` (which logs the transition). Direct
  attribute assignment works but bypasses logging.

- **Cost tracking:** ``CostTracker`` is the authoritative source for per-tier /
  per-user cost aggregation. ``AgentInfo.cost_cents`` is a display cache
  updated by ``SubAgentRegistry.update_cost()``.

- **Directive lifecycle:** ``recall_agent`` writes a ``shutdown`` directive
  best-effort, then cancels the task. There is no graceful-shutdown wait —
  the sub-agent must observe the directive within its next heartbeat loop
  or be cancelled mid-iteration.
"""
from .state import SubAgentState, AgentInfo
from .store import AgentStore
from .registry import SubAgentRegistry
from .context_recovery import build_recovery_context
from .health import HealthMonitor, FailureReason
from .recovery import RecoveryChain, RecoveryAction, next_tier
from .tools import (
    init_orchestration_tools,
    spawn_agent,
    recall_agent,
    monitor_agents,
    assign_task,
    switch_agent_model,
    review_cost,
)

__all__ = [
    # Data types
    "SubAgentState",
    "AgentInfo",
    "FailureReason",
    "RecoveryAction",
    # Infrastructure
    "AgentStore",
    "SubAgentRegistry",
    "HealthMonitor",
    "RecoveryChain",
    "next_tier",
    "build_recovery_context",
    # Orchestration tools
    "init_orchestration_tools",
    "spawn_agent",
    "recall_agent",
    "monitor_agents",
    "assign_task",
    "switch_agent_model",
    "review_cost",
]
