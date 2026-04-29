"""SubAgentState enum and AgentInfo dataclass.

Worker state machine (GAP-2):
    SPAWNING → READY → RUNNING → FINISHED
        │         │        │
        │         │        ├→ BLOCKED (waiting on approval/resource)
        │         │        │
        │         │        └→ FAILED
        │         │
        │         └→ (trust prompt auto-resolution)
        │
        └→ FAILED (spawn error)
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class SubAgentState(str, Enum):
    SPAWNING = "spawning"       # asyncio.Task created, graph compiling
    READY = "ready"             # Graph compiled, awaiting first invocation
    RUNNING = "running"         # Processing messages/tools
    BLOCKED = "blocked"         # Waiting on permission approval or resource
    FINISHED = "finished"       # Completed successfully
    FAILED = "failed"           # Unrecoverable error


@dataclass
class AgentInfo:
    """Metadata about a running sub-agent."""
    agent_id: str
    name: str
    role: str                   # "planner" | "executor" | "evaluator" | custom
    task: str
    tier: str                   # "lite" | "standard" | "advanced" | "expert"
    tools: list[str]
    skills: list[str]
    state: SubAgentState = SubAgentState.SPAWNING
    iteration: int = 0          # Tool-call cycle count
    cost_cents: float = 0.0
    retry_count: int = 0
    last_heartbeat: float = field(default_factory=time.time)
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    error: str | None = None
    result: str | None = None
    worktree_path: str | None = None    # For git worktree isolation

    def to_dict(self) -> dict:
        """Internal serializer for state snapshots / debug logging.

        Returns the full field set with raw float timestamps. The API-edge
        projection used by ``/v1/agents`` lives in ``src/api/management.py``
        as ``_agent_to_dict``; it intentionally trims fields and emits
        ISO-8601 timestamps. Do not use this method for HTTP responses.
        """
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "role": self.role,
            "task": self.task,
            "tier": self.tier,
            "tools": list(self.tools),
            "skills": list(self.skills),
            "state": self.state.value if isinstance(self.state, SubAgentState) else self.state,
            "iteration": self.iteration,
            "cost_cents": self.cost_cents,
            "retry_count": self.retry_count,
            "last_heartbeat": self.last_heartbeat,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "result": self.result,
            "worktree_path": self.worktree_path,
        }
