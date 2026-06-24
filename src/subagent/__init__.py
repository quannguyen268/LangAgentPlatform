"""Sub-agent system — registry, orchestration tools, health monitoring, recovery.

## Public API

Importable directly from `src.subagent`:

    # Data types
    SubAgentState, AgentInfo
    FailureReason, RecoveryAction
    BudgetDecision, Conflict

    # Infrastructure
    SubAgentRegistry, AgentStore
    HealthMonitor, RecoveryChain, next_tier
    build_recovery_context
    EventBroadcaster, BudgetEnforcer, WorktreeManager, ConflictDetector
    DeepAgentsSpawner, RecoveryExecutor, TaskRebalancer

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
from .broadcaster import EventBroadcaster
from .budget import BudgetDecision, BudgetEnforcer
from .conflicts import Conflict, ConflictDetector
from .context_recovery import build_recovery_context
from .health import FailureReason, HealthMonitor
from .rebalance import TaskRebalancer
from .recovery import RecoveryAction, RecoveryChain, next_tier
from .recovery_executor import RecoveryExecutor
from .registry import SubAgentRegistry
from .spawner import DeepAgentsSpawner
from .state import AgentInfo, SubAgentState
from .store import AgentStore
from .tools import (
    assign_task,
    init_orchestration_tools,
    monitor_agents,
    recall_agent,
    review_cost,
    spawn_agent,
    switch_agent_model,
)
from .worktree import WorktreeManager

__all__ = [
    "AgentInfo",
    "AgentStore",
    "BudgetDecision",
    "BudgetEnforcer",
    "Conflict",
    "ConflictDetector",
    "DeepAgentsSpawner",
    "EventBroadcaster",
    "FailureReason",
    "HealthMonitor",
    "RecoveryAction",
    "RecoveryChain",
    "RecoveryExecutor",
    "SubAgentRegistry",
    "SubAgentState",
    "TaskRebalancer",
    "WorktreeManager",
    "assign_task",
    "build_recovery_context",
    "init_orchestration_tools",
    "monitor_agents",
    "next_tier",
    "recall_agent",
    "review_cost",
    "spawn_agent",
    "switch_agent_model",
]
