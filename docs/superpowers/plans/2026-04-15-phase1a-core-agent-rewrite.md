# Phase 1A: Core Agent Rewrite — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace DeepAgents' `create_deep_agent()` with an explicit LangGraph StateGraph that we fully own, enabling custom nodes (permission_check, monitor), streaming events, context compression, per-user sessions, cost tracking, and runner-level error recovery.

**Architecture:** The current agent uses `deepagents.create_deep_agent()` which abstracts the graph. We replace it with an explicit `StateGraph(AgentState)` with 4 nodes: `agent` (LLM reasoning), `permission_check` (tool approval with `interrupt()`), `tools` (parallel execution), and `monitor` (sub-agent health). The RoutingChatModel, tools, skills, and MCP integration are preserved — only the graph and runner change.

**Tech Stack:** LangGraph 1.x, LangChain Core, Pydantic v2, asyncio, aiosqlite

**Spec Reference:** `docs/superpowers/specs/2026-04-15-langagent-platform-design.md` — Sections 4, 6, 14, 15, 16, 19, 21; GAPs 13-15

**Prerequisites:** Phase 0 complete (fork verified, 590 tests passing)

**Key constraint:** This is a refactor, not a rewrite-from-scratch. We preserve all existing tools (web, cron, host, model_router), skills, MCP, channels, gateway, and scheduling. We only replace the agent graph, router thread_id, and add new modules (streaming, permissions, compaction, cost).

---

## File Structure

### Files to create (new modules)

```
src/core/                       # New: explicit agent graph
  __init__.py
  state.py                      # AgentState dataclass
  graph.py                      # StateGraph definition with 4 nodes
  nodes.py                      # Node implementations (agent, permission_check, tools, monitor)
  streaming.py                  # StreamEvent types and emission

src/permissions/                # New: permission system
  __init__.py
  manager.py                    # PermissionManager with modes + rules
  rules.py                      # Path and command rules

src/observability/              # New: cost tracking
  __init__.py
  cost.py                       # CostTracker with per-tier/per-user pricing

src/tools/file_state.py         # New: read-before-edit tracking (GAP-15)

tests/test_core_state.py        # AgentState tests
tests/test_core_graph.py        # Graph creation + basic flow tests
tests/test_core_nodes.py        # Individual node tests
tests/test_streaming.py         # StreamEvent tests
tests/test_permissions.py       # Permission system tests
tests/test_cost_tracker.py      # Cost tracking tests
tests/test_file_state.py        # File state tracker tests
tests/test_compaction.py        # Context compression tests
tests/test_session_multiuser.py # Multi-user thread_id tests
```

### Files to modify (existing)

```
src/agent.py                    # Replace create_deep_agent() with our graph
src/router.py                   # Fix thread_id to include user_id
src/config.py                   # Add permission, streaming, context, cost configs
src/main.py                     # Wire new components
```

### Files to keep unchanged

```
src/tools/web.py                # Inherited tools — no changes
src/tools/cron.py               # Inherited tools — no changes
src/tools/host.py               # Inherited tools — no changes
src/tools/model_router.py       # RoutingChatModel stays as-is
src/channels/                   # All channels stay as-is
src/gateway/                    # Gateway stays as-is
src/scheduler.py                # Scheduler stays as-is
src/middleware.py                # Skill middleware stays as-is
```

---

### Task 1: Define AgentState

**Files:**
- Create: `src/core/__init__.py`
- Create: `src/core/state.py`
- Create: `tests/test_core_state.py`

- [ ] **Step 1: Write failing test for AgentState**

```python
# tests/test_core_state.py
"""Test AgentState schema and defaults."""
import pytest


def test_agent_state_imports():
    from src.core.state import AgentState
    assert AgentState is not None


def test_agent_state_has_required_fields():
    from src.core.state import AgentState
    state = AgentState(messages=[])
    assert state.active_tier == "standard"
    assert state.session_id == ""
    assert state.channel == ""
    assert state.user_id == ""
    assert state.memory_context == ""
    assert state.skills_summary == ""
    assert state.active_sub_agents == {}
    assert state.pending_tasks == []
    assert state.tool_permissions == {}
    assert state.cost_this_session == 0.0
    assert state.cost_budget is None


def test_agent_state_inherits_messages_state():
    from src.core.state import AgentState
    from langgraph.graph import MessagesState
    assert issubclass(AgentState, MessagesState)


def test_agent_state_with_custom_values():
    from src.core.state import AgentState
    state = AgentState(
        messages=[],
        active_tier="expert",
        user_id="user123",
        cost_budget=500.0,
    )
    assert state.active_tier == "expert"
    assert state.user_id == "user123"
    assert state.cost_budget == 500.0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_core_state.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'src.core'`

- [ ] **Step 3: Implement AgentState**

```python
# src/core/__init__.py
"""LangAgent Platform core — explicit LangGraph agent graph."""
```

```python
# src/core/state.py
"""AgentState — the central state schema for the agent graph."""
from __future__ import annotations

from typing import Any
from langgraph.graph import MessagesState


class AgentState(MessagesState):
    """Extended state with platform-specific fields.
    
    Inherits `messages` from MessagesState (list of BaseMessage).
    All fields have defaults so the state can be created with just messages.
    """
    # Core
    active_tier: str = "standard"
    session_id: str = ""
    channel: str = ""
    user_id: str = ""

    # Context (injected before each invocation)
    memory_context: str = ""
    skills_summary: str = ""

    # Orchestration (Phase 1C — empty for now)
    active_sub_agents: dict[str, dict] = {}
    pending_tasks: list[dict] = []

    # Permissions
    tool_permissions: dict[str, str] = {}

    # Cost
    cost_this_session: float = 0.0
    cost_budget: float | None = None
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_core_state.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/ tests/test_core_state.py
git commit -m "feat: add AgentState schema with all spec fields"
```

---

### Task 2: Define StreamEvent types

**Files:**
- Create: `src/core/streaming.py`
- Create: `tests/test_streaming.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_streaming.py
"""Test StreamEvent types and factory functions."""
import pytest
import time


def test_stream_event_imports():
    from src.core.streaming import StreamEvent, EventType
    assert StreamEvent is not None


def test_event_types_defined():
    from src.core.streaming import EventType
    assert EventType.TOKEN == "token"
    assert EventType.THINKING == "thinking"
    assert EventType.TOOL_CALL_START == "tool_call_start"
    assert EventType.TOOL_CALL_END == "tool_call_end"
    assert EventType.TOOL_ERROR == "tool_error"
    assert EventType.TIER_SWITCH == "tier_switch"
    assert EventType.APPROVAL_REQUEST == "approval_request"
    assert EventType.COST_UPDATE == "cost_update"
    assert EventType.ERROR == "error"
    assert EventType.DONE == "done"


def test_stream_event_creation():
    from src.core.streaming import StreamEvent, EventType
    event = StreamEvent(
        type=EventType.TOKEN,
        data={"delta": "Hello"},
        agent_id="master",
        user_id="user123",
    )
    assert event.type == "token"
    assert event.data == {"delta": "Hello"}
    assert event.agent_id == "master"
    assert event.user_id == "user123"
    assert event.timestamp > 0


def test_stream_event_to_dict():
    from src.core.streaming import StreamEvent, EventType
    event = StreamEvent(
        type=EventType.DONE,
        data={},
        agent_id="master",
        user_id="user123",
    )
    d = event.to_dict()
    assert d["type"] == "done"
    assert "timestamp" in d
    assert d["agent_id"] == "master"


def test_token_event_factory():
    from src.core.streaming import token_event
    event = token_event("Hello", user_id="u1")
    assert event.type == "token"
    assert event.data["delta"] == "Hello"


def test_tool_call_start_factory():
    from src.core.streaming import tool_call_start_event
    event = tool_call_start_event("web_search", {"query": "test"}, user_id="u1")
    assert event.type == "tool_call_start"
    assert event.data["name"] == "web_search"
    assert event.data["args"] == {"query": "test"}


def test_cost_update_factory():
    from src.core.streaming import cost_update_event
    event = cost_update_event(
        prompt_tokens=100, completion_tokens=50,
        cost_cents=1.5, tier="standard", user_id="u1",
    )
    assert event.type == "cost_update"
    assert event.data["prompt_tokens"] == 100
    assert event.data["cost_cents"] == 1.5
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_streaming.py -v
```

Expected: FAIL

- [ ] **Step 3: Implement StreamEvent**

```python
# src/core/streaming.py
"""StreamEvent types and factory functions for the streaming lifecycle."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


class EventType:
    """All stream event type constants."""
    TOKEN = "token"
    THINKING = "thinking"
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_END = "tool_call_end"
    TOOL_ERROR = "tool_error"
    TIER_SWITCH = "tier_switch"
    AGENT_SPAWN = "agent_spawn"
    AGENT_PROGRESS = "agent_progress"
    AGENT_COMPLETE = "agent_complete"
    AGENT_FAILED = "agent_failed"
    APPROVAL_REQUEST = "approval_request"
    COST_UPDATE = "cost_update"
    ERROR = "error"
    DONE = "done"


@dataclass
class StreamEvent:
    """A typed event emitted during agent execution."""
    type: str
    data: Any
    agent_id: str = "master"
    user_id: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "data": self.data,
            "agent_id": self.agent_id,
            "user_id": self.user_id,
            "timestamp": self.timestamp,
        }


# ── Factory functions ──

def token_event(delta: str, user_id: str = "", agent_id: str = "master") -> StreamEvent:
    return StreamEvent(type=EventType.TOKEN, data={"delta": delta}, agent_id=agent_id, user_id=user_id)


def thinking_event(content: str, user_id: str = "", agent_id: str = "master") -> StreamEvent:
    return StreamEvent(type=EventType.THINKING, data={"content": content}, agent_id=agent_id, user_id=user_id)


def tool_call_start_event(name: str, args: dict, user_id: str = "", agent_id: str = "master") -> StreamEvent:
    return StreamEvent(type=EventType.TOOL_CALL_START, data={"name": name, "args": args}, agent_id=agent_id, user_id=user_id)


def tool_call_end_event(name: str, result: str, user_id: str = "", agent_id: str = "master") -> StreamEvent:
    return StreamEvent(type=EventType.TOOL_CALL_END, data={"name": name, "result": result}, agent_id=agent_id, user_id=user_id)


def tool_error_event(name: str, error: str, user_id: str = "", agent_id: str = "master") -> StreamEvent:
    return StreamEvent(type=EventType.TOOL_ERROR, data={"name": name, "error": error}, agent_id=agent_id, user_id=user_id)


def tier_switch_event(from_tier: str, to_tier: str, user_id: str = "", agent_id: str = "master") -> StreamEvent:
    return StreamEvent(type=EventType.TIER_SWITCH, data={"from": from_tier, "to": to_tier}, agent_id=agent_id, user_id=user_id)


def approval_request_event(tool_name: str, args: dict, user_id: str = "", agent_id: str = "master") -> StreamEvent:
    return StreamEvent(type=EventType.APPROVAL_REQUEST, data={"tool": tool_name, "args": args}, agent_id=agent_id, user_id=user_id)


def cost_update_event(
    prompt_tokens: int, completion_tokens: int, cost_cents: float,
    tier: str = "standard", user_id: str = "", agent_id: str = "master",
) -> StreamEvent:
    return StreamEvent(
        type=EventType.COST_UPDATE,
        data={
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cost_cents": cost_cents,
            "tier": tier,
        },
        agent_id=agent_id, user_id=user_id,
    )


def error_event(message: str, user_id: str = "", agent_id: str = "master") -> StreamEvent:
    return StreamEvent(type=EventType.ERROR, data={"message": message}, agent_id=agent_id, user_id=user_id)


def done_event(user_id: str = "", agent_id: str = "master") -> StreamEvent:
    return StreamEvent(type=EventType.DONE, data={}, agent_id=agent_id, user_id=user_id)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_streaming.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/streaming.py tests/test_streaming.py
git commit -m "feat: add StreamEvent types with 14 event kinds and factory functions"
```

---

### Task 3: Implement CostTracker

**Files:**
- Create: `src/observability/__init__.py`
- Create: `src/observability/cost.py`
- Create: `tests/test_cost_tracker.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_cost_tracker.py
"""Test CostTracker with per-tier and per-user pricing."""
import pytest


def test_cost_tracker_imports():
    from src.observability.cost import CostTracker
    assert CostTracker is not None


def test_default_pricing():
    from src.observability.cost import CostTracker
    tracker = CostTracker()
    # Anthropic Sonnet default pricing should exist
    assert tracker.get_price("anthropic", "claude-sonnet-4-6") is not None


def test_record_usage():
    from src.observability.cost import CostTracker
    tracker = CostTracker()
    tracker.record(
        provider="anthropic",
        model="claude-sonnet-4-6",
        prompt_tokens=1000,
        completion_tokens=500,
        user_id="user1",
        tier="standard",
    )
    summary = tracker.summary()
    assert summary["total_tokens"] > 0
    assert summary["total_cost_cents"] > 0


def test_per_user_tracking():
    from src.observability.cost import CostTracker
    tracker = CostTracker()
    tracker.record(provider="anthropic", model="claude-sonnet-4-6",
                   prompt_tokens=1000, completion_tokens=500,
                   user_id="alice", tier="standard")
    tracker.record(provider="anthropic", model="claude-sonnet-4-6",
                   prompt_tokens=2000, completion_tokens=1000,
                   user_id="bob", tier="standard")
    by_user = tracker.by_user()
    assert "alice" in by_user
    assert "bob" in by_user
    assert by_user["bob"]["total_tokens"] > by_user["alice"]["total_tokens"]


def test_per_tier_tracking():
    from src.observability.cost import CostTracker
    tracker = CostTracker()
    tracker.record(provider="anthropic", model="claude-sonnet-4-6",
                   prompt_tokens=1000, completion_tokens=500,
                   user_id="u1", tier="standard")
    tracker.record(provider="groq", model="llama-3.3-70b",
                   prompt_tokens=5000, completion_tokens=2000,
                   user_id="u1", tier="lite")
    by_tier = tracker.by_tier()
    assert "standard" in by_tier
    assert "lite" in by_tier


def test_budget_check():
    from src.observability.cost import CostTracker
    tracker = CostTracker()
    tracker.record(provider="anthropic", model="claude-sonnet-4-6",
                   prompt_tokens=100000, completion_tokens=50000,
                   user_id="u1", tier="standard")
    assert tracker.is_over_budget("u1", budget_cents=1.0)  # Very small budget
    assert not tracker.is_over_budget("u1", budget_cents=99999.0)  # Very large budget
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_cost_tracker.py -v
```

Expected: FAIL

- [ ] **Step 3: Implement CostTracker**

```python
# src/observability/__init__.py
"""Observability — cost tracking, tracing, metrics."""
```

```python
# src/observability/cost.py
"""CostTracker — per-tier, per-user, per-agent token and cost tracking."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Pricing per 1M tokens (input, output) in USD cents
DEFAULT_PRICING: dict[str, tuple[float, float]] = {
    # Anthropic
    "claude-sonnet-4-6": (300.0, 1500.0),
    "claude-opus-4-6": (1500.0, 7500.0),
    "claude-haiku-4-5": (80.0, 400.0),
    # OpenAI
    "gpt-4o": (250.0, 1000.0),
    "gpt-4o-mini": (15.0, 60.0),
    # Groq
    "llama-3.3-70b-versatile": (59.0, 79.0),
    # Gemini
    "gemini-2.5-flash": (15.0, 60.0),
    "gemini-2.5-pro": (125.0, 500.0),
}


@dataclass
class UsageRecord:
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    user_id: str
    tier: str
    cost_cents: float
    agent_id: str = "master"


class CostTracker:
    """Track token usage and costs across tiers, users, and agents."""

    def __init__(self, pricing: dict[str, tuple[float, float]] | None = None):
        self._pricing = pricing or DEFAULT_PRICING
        self._records: list[UsageRecord] = []

    def get_price(self, provider: str, model: str) -> tuple[float, float] | None:
        """Get (input_per_1M, output_per_1M) pricing in cents."""
        # Try exact model name first
        if model in self._pricing:
            return self._pricing[model]
        # Try without provider prefix
        short = model.split("/")[-1] if "/" in model else model
        return self._pricing.get(short)

    def calculate_cost(self, provider: str, model: str,
                       prompt_tokens: int, completion_tokens: int) -> float:
        """Calculate cost in cents for a single API call."""
        price = self.get_price(provider, model)
        if not price:
            return 0.0
        input_rate, output_rate = price
        return (prompt_tokens * input_rate + completion_tokens * output_rate) / 1_000_000

    def record(self, provider: str, model: str,
               prompt_tokens: int, completion_tokens: int,
               user_id: str = "", tier: str = "standard",
               agent_id: str = "master") -> float:
        """Record a usage event. Returns cost in cents."""
        cost = self.calculate_cost(provider, model, prompt_tokens, completion_tokens)
        self._records.append(UsageRecord(
            provider=provider, model=model,
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
            user_id=user_id, tier=tier, cost_cents=cost, agent_id=agent_id,
        ))
        return cost

    def summary(self) -> dict:
        """Aggregate summary across all records."""
        total_prompt = sum(r.prompt_tokens for r in self._records)
        total_completion = sum(r.completion_tokens for r in self._records)
        total_cost = sum(r.cost_cents for r in self._records)
        return {
            "total_tokens": total_prompt + total_completion,
            "prompt_tokens": total_prompt,
            "completion_tokens": total_completion,
            "total_cost_cents": total_cost,
            "total_calls": len(self._records),
        }

    def by_user(self) -> dict[str, dict]:
        """Aggregate by user_id."""
        result: dict[str, dict] = {}
        for r in self._records:
            if r.user_id not in result:
                result[r.user_id] = {"total_tokens": 0, "total_cost_cents": 0.0, "calls": 0}
            entry = result[r.user_id]
            entry["total_tokens"] += r.prompt_tokens + r.completion_tokens
            entry["total_cost_cents"] += r.cost_cents
            entry["calls"] += 1
        return result

    def by_tier(self) -> dict[str, dict]:
        """Aggregate by tier."""
        result: dict[str, dict] = {}
        for r in self._records:
            if r.tier not in result:
                result[r.tier] = {"total_tokens": 0, "total_cost_cents": 0.0, "calls": 0}
            entry = result[r.tier]
            entry["total_tokens"] += r.prompt_tokens + r.completion_tokens
            entry["total_cost_cents"] += r.cost_cents
            entry["calls"] += 1
        return result

    def by_agent(self) -> dict[str, dict]:
        """Aggregate by agent_id."""
        result: dict[str, dict] = {}
        for r in self._records:
            if r.agent_id not in result:
                result[r.agent_id] = {"total_tokens": 0, "total_cost_cents": 0.0, "calls": 0}
            entry = result[r.agent_id]
            entry["total_tokens"] += r.prompt_tokens + r.completion_tokens
            entry["total_cost_cents"] += r.cost_cents
            entry["calls"] += 1
        return result

    def user_cost(self, user_id: str) -> float:
        """Get total cost in cents for a specific user."""
        return sum(r.cost_cents for r in self._records if r.user_id == user_id)

    def is_over_budget(self, user_id: str, budget_cents: float) -> bool:
        """Check if a user has exceeded their budget."""
        return self.user_cost(user_id) > budget_cents
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_cost_tracker.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/observability/ tests/test_cost_tracker.py
git commit -m "feat: add CostTracker with per-tier/per-user/per-agent tracking"
```

---

### Task 4: Implement PermissionManager

**Files:**
- Create: `src/permissions/__init__.py`
- Create: `src/permissions/manager.py`
- Create: `tests/test_permissions.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_permissions.py
"""Test PermissionManager with modes and rules."""
import pytest


def test_permission_manager_imports():
    from src.permissions.manager import PermissionManager, PermissionMode
    assert PermissionManager is not None


def test_permission_modes():
    from src.permissions.manager import PermissionMode
    assert PermissionMode.DEFAULT == "default"
    assert PermissionMode.AUTO == "auto"
    assert PermissionMode.PLAN == "plan"


def test_auto_mode_allows_everything():
    from src.permissions.manager import PermissionManager, PermissionMode
    pm = PermissionManager(mode=PermissionMode.AUTO)
    result = pm.check("exec", {"command": "rm -rf /"})
    assert result.action == "allow"


def test_plan_mode_blocks_writes():
    from src.permissions.manager import PermissionManager, PermissionMode
    pm = PermissionManager(mode=PermissionMode.PLAN)
    # Read tools should be allowed
    assert pm.check("read_file", {"path": "foo.py"}).action == "allow"
    assert pm.check("glob", {"pattern": "*.py"}).action == "allow"
    assert pm.check("grep", {"pattern": "test"}).action == "allow"
    assert pm.check("web_search", {"query": "test"}).action == "allow"
    assert pm.check("web_fetch", {"url": "http://test"}).action == "allow"
    # Write tools should be denied
    assert pm.check("write_file", {"path": "foo.py"}).action == "deny"
    assert pm.check("edit_file", {"path": "foo.py"}).action == "deny"
    assert pm.check("exec", {"command": "echo hi"}).action == "deny"
    assert pm.check("host_execute", {"bridge": "spotify"}).action == "deny"


def test_default_mode_asks_for_write_tools():
    from src.permissions.manager import PermissionManager, PermissionMode
    pm = PermissionManager(mode=PermissionMode.DEFAULT)
    # Read tools allowed
    assert pm.check("read_file", {"path": "foo.py"}).action == "allow"
    # Write tools require approval
    assert pm.check("exec", {"command": "echo hi"}).action == "ask"
    assert pm.check("write_file", {"path": "foo.py"}).action == "ask"


def test_sensitive_path_always_denied():
    from src.permissions.manager import PermissionManager, PermissionMode
    pm = PermissionManager(mode=PermissionMode.AUTO)
    result = pm.check("read_file", {"path": "/home/user/.ssh/id_rsa"})
    assert result.action == "deny"
    assert "sensitive" in result.reason.lower()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_permissions.py -v
```

Expected: FAIL

- [ ] **Step 3: Implement PermissionManager**

```python
# src/permissions/__init__.py
"""Permission & security system."""
```

```python
# src/permissions/manager.py
"""PermissionManager — multi-mode tool permission enforcement."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


class PermissionMode:
    DEFAULT = "default"
    AUTO = "auto"
    PLAN = "plan"


READ_ONLY_TOOLS = frozenset({
    "read_file", "glob", "grep", "web_search", "web_fetch",
    "list_tasks", "monitor_agents", "review_cost", "switch_model",
})

WRITE_TOOLS = frozenset({
    "write_file", "edit_file", "exec", "host_execute",
    "schedule_task", "cancel_task", "notebook_edit",
    "spawn_agent", "recall_agent", "create_team", "dissolve_team",
})

SENSITIVE_PATHS = [
    ".ssh/", ".gnupg/", ".aws/", ".gcp/", ".azure/",
    ".docker/config.json", ".kube/config",
    "id_rsa", "id_ed25519", "credentials.json",
    ".env", ".netrc", "token", "secret",
]


@dataclass
class PermissionResult:
    action: str   # "allow" | "deny" | "ask"
    reason: str = ""


class PermissionManager:
    """Check tool permissions based on mode and rules."""

    def __init__(self, mode: str = PermissionMode.DEFAULT):
        self.mode = mode

    def check(self, tool_name: str, args: dict[str, Any]) -> PermissionResult:
        """Check if a tool call is allowed.
        
        Returns:
            PermissionResult with action: "allow", "deny", or "ask"
        """
        # Sensitive path check (always, regardless of mode)
        path = args.get("path", "") or args.get("file", "") or ""
        if path and self._is_sensitive_path(path):
            return PermissionResult(
                action="deny",
                reason=f"Sensitive path detected: {path}",
            )

        # Mode-based checks
        if self.mode == PermissionMode.AUTO:
            return PermissionResult(action="allow")

        if self.mode == PermissionMode.PLAN:
            if tool_name in READ_ONLY_TOOLS:
                return PermissionResult(action="allow")
            return PermissionResult(
                action="deny",
                reason=f"Plan mode: {tool_name} is not a read-only tool",
            )

        # Default mode: read tools allowed, write tools ask
        if tool_name in READ_ONLY_TOOLS:
            return PermissionResult(action="allow")
        if tool_name in WRITE_TOOLS:
            return PermissionResult(
                action="ask",
                reason=f"{tool_name} requires approval",
            )
        # Unknown tools: ask
        return PermissionResult(action="ask", reason=f"Unknown tool: {tool_name}")

    def _is_sensitive_path(self, path: str) -> bool:
        """Check if path matches any sensitive patterns."""
        path_lower = path.lower()
        return any(pattern in path_lower for pattern in SENSITIVE_PATHS)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_permissions.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/permissions/ tests/test_permissions.py
git commit -m "feat: add PermissionManager with default/auto/plan modes and sensitive path protection"
```

---

### Task 5: Implement FileStateTracker (GAP-15)

**Files:**
- Create: `src/tools/file_state.py`
- Create: `tests/test_file_state.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_file_state.py
"""Test FileStateTracker for read-before-edit warnings."""
import pytest
import os
import hashlib
from pathlib import Path


def test_file_state_imports():
    from src.tools.file_state import FileStateTracker
    assert FileStateTracker is not None


def test_record_and_check_ok(tmp_path):
    from src.tools.file_state import FileStateTracker
    tracker = FileStateTracker()
    f = tmp_path / "test.py"
    f.write_text("print('hello')")

    tracker.record_read(str(f), f.read_text())
    warning = tracker.check_before_edit(str(f))
    assert warning is None  # No warning — file was read and unchanged


def test_check_without_read(tmp_path):
    from src.tools.file_state import FileStateTracker
    tracker = FileStateTracker()
    f = tmp_path / "test.py"
    f.write_text("print('hello')")

    warning = tracker.check_before_edit(str(f))
    assert warning is not None
    assert "not been read" in warning


def test_check_after_modification(tmp_path):
    from src.tools.file_state import FileStateTracker
    tracker = FileStateTracker()
    f = tmp_path / "test.py"
    f.write_text("print('hello')")
    tracker.record_read(str(f), f.read_text())

    # Modify the file externally
    f.write_text("print('modified')")

    warning = tracker.check_before_edit(str(f))
    assert warning is not None
    assert "modified" in warning.lower()


def test_no_false_positive_on_touch(tmp_path):
    """Touch (mtime change without content change) should NOT warn."""
    from src.tools.file_state import FileStateTracker
    tracker = FileStateTracker()
    f = tmp_path / "test.py"
    f.write_text("print('hello')")
    tracker.record_read(str(f), f.read_text())

    # Touch the file (change mtime, same content)
    os.utime(str(f), (os.path.getatime(str(f)) + 1, os.path.getmtime(str(f)) + 1))

    warning = tracker.check_before_edit(str(f))
    assert warning is None  # Content hash matches, no warning
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_file_state.py -v
```

Expected: FAIL

- [ ] **Step 3: Implement FileStateTracker**

```python
# src/tools/file_state.py
"""FileStateTracker — read-before-edit warnings and staleness detection."""
from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ReadState:
    mtime: float
    content_hash: str
    offset: int = 0
    limit: int = 0


def _hash_content(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()


class FileStateTracker:
    """Track file reads to warn before stale edits."""

    def __init__(self):
        self._states: dict[str, ReadState] = {}

    def record_read(self, path: str, content: str, offset: int = 0, limit: int = 0) -> None:
        """Record that a file was read with given content."""
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = 0.0
        self._states[path] = ReadState(
            mtime=mtime,
            content_hash=_hash_content(content),
            offset=offset,
            limit=limit,
        )

    def check_before_edit(self, path: str) -> str | None:
        """Check if it's safe to edit. Returns warning string or None if OK."""
        if path not in self._states:
            return f"Warning: {path} has not been read yet. Read before editing."

        state = self._states[path]
        try:
            current_mtime = os.path.getmtime(path)
        except OSError:
            return f"Warning: {path} no longer exists."

        if current_mtime != state.mtime:
            # mtime changed — check content hash to avoid false positives from touch
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    current_hash = _hash_content(f.read())
            except OSError:
                return f"Warning: {path} cannot be read for staleness check."

            if current_hash != state.content_hash:
                return f"Warning: {path} was modified since last read. Re-read before editing."

        return None  # Safe to edit

    def clear(self) -> None:
        """Reset all tracked state."""
        self._states.clear()
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_file_state.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/tools/file_state.py tests/test_file_state.py
git commit -m "feat: add FileStateTracker for read-before-edit warnings (GAP-15)"
```

---

### Task 6: Implement context compression (micro-compact + reactive)

**Files:**
- Create: `src/core/compaction.py`
- Create: `tests/test_compaction.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_compaction.py
"""Test context compression — micro-compact and reactive compaction."""
import pytest
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage


def test_compaction_imports():
    from src.core.compaction import estimate_tokens, micro_compact, should_compact


def test_estimate_tokens():
    from src.core.compaction import estimate_tokens
    from langchain_core.messages import HumanMessage
    messages = [HumanMessage(content="Hello " * 100)]  # ~600 chars
    tokens = estimate_tokens(messages)
    assert 100 < tokens < 200  # ~150 tokens at 4 chars/token


def test_should_compact_below_threshold():
    from src.core.compaction import should_compact
    from langchain_core.messages import HumanMessage
    messages = [HumanMessage(content="Hello")]
    assert should_compact(messages, max_tokens=128000, threshold=0.8) == False


def test_should_compact_above_threshold():
    from src.core.compaction import should_compact
    from langchain_core.messages import HumanMessage
    # Create messages that exceed 80% of a tiny context window
    messages = [HumanMessage(content="x" * 4000)]  # ~1000 tokens
    assert should_compact(messages, max_tokens=1000, threshold=0.8) == True


def test_micro_compact_preserves_recent():
    from src.core.compaction import micro_compact
    messages = []
    for i in range(20):
        messages.append(HumanMessage(content=f"User message {i}"))
        messages.append(AIMessage(content=f"Assistant response {i} " + "padding " * 50))

    result = micro_compact(messages, preserve_recent=5)
    # Should have fewer messages than original
    assert len(result) < len(messages)
    # Last 5 turns (10 messages) should be preserved
    assert result[-1].content == messages[-1].content


def test_micro_compact_empty_messages():
    from src.core.compaction import micro_compact
    result = micro_compact([], preserve_recent=5)
    assert result == []


def test_micro_compact_few_messages():
    """If messages fewer than preserve_recent, return as-is."""
    from src.core.compaction import micro_compact
    messages = [HumanMessage(content="Hello"), AIMessage(content="Hi")]
    result = micro_compact(messages, preserve_recent=5)
    assert len(result) == 2
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_compaction.py -v
```

Expected: FAIL

- [ ] **Step 3: Implement compaction module**

```python
# src/core/compaction.py
"""Context compression — micro-compact and reactive compaction.

Two stages:
1. Micro-compact: summarize old tool results, keep recent turns
2. Reactive: triggered by prompt-too-long errors, more aggressive

Token estimation uses character heuristic (4 chars ≈ 1 token).
"""
from __future__ import annotations

import logging
from langchain_core.messages import (
    BaseMessage, HumanMessage, AIMessage, SystemMessage, ToolMessage,
)

logger = logging.getLogger(__name__)

# Constants
_CHARS_PER_TOKEN = 4
_MAX_COMPACT_FAILURES = 3


def estimate_tokens(messages: list[BaseMessage]) -> int:
    """Fast token estimation using character count heuristic.
    
    ~4 chars per token for English. Accurate to ~10%.
    """
    total = 0
    for m in messages:
        if isinstance(m.content, str):
            total += len(m.content)
        elif isinstance(m.content, list):
            # Multimodal: sum text blocks, estimate image tokens
            for block in m.content:
                if isinstance(block, dict) and block.get("type") == "text":
                    total += len(block.get("text", ""))
                elif isinstance(block, dict) and block.get("type") == "image_url":
                    total += 1000 * _CHARS_PER_TOKEN  # ~1000 tokens per image
        # Add overhead for role, metadata
        total += 20  # ~5 tokens overhead per message
    return total // _CHARS_PER_TOKEN


def should_compact(
    messages: list[BaseMessage],
    max_tokens: int = 128000,
    threshold: float = 0.8,
) -> bool:
    """Check if messages exceed the compaction threshold."""
    current = estimate_tokens(messages)
    limit = int(max_tokens * threshold)
    return current > limit


def micro_compact(
    messages: list[BaseMessage],
    preserve_recent: int = 10,
) -> list[BaseMessage]:
    """Micro-compact: summarize old messages, preserve recent turns.
    
    Strategy:
    1. Keep system messages at the start
    2. Summarize old tool results (replace with "[Tool result summarized]")
    3. Preserve the last `preserve_recent` user/assistant turn pairs
    """
    if not messages:
        return []

    # Count turn pairs (user + assistant = 1 pair)
    turn_count = sum(1 for m in messages if isinstance(m, HumanMessage))
    if turn_count <= preserve_recent:
        return list(messages)

    # Split: system messages | old messages | recent messages
    system_msgs = []
    other_msgs = []
    for m in messages:
        if isinstance(m, SystemMessage):
            system_msgs.append(m)
        else:
            other_msgs.append(m)

    # Find the split point: keep last `preserve_recent` turns
    # Walk backwards counting HumanMessages
    recent_start = len(other_msgs)
    turns_found = 0
    for i in range(len(other_msgs) - 1, -1, -1):
        if isinstance(other_msgs[i], HumanMessage):
            turns_found += 1
            if turns_found >= preserve_recent:
                recent_start = i
                break

    old_msgs = other_msgs[:recent_start]
    recent_msgs = other_msgs[recent_start:]

    # Compact old messages: keep user/assistant, summarize tool results
    compacted_old = []
    for m in old_msgs:
        if isinstance(m, ToolMessage):
            # Replace verbose tool results with summary
            content = m.content if isinstance(m.content, str) else str(m.content)
            if len(content) > 200:
                summary = content[:100] + "... [truncated]"
                compacted_old.append(ToolMessage(
                    content=summary,
                    tool_call_id=m.tool_call_id,
                    name=getattr(m, 'name', ''),
                ))
            else:
                compacted_old.append(m)
        else:
            compacted_old.append(m)

    # Add a summary marker
    if compacted_old:
        summary_text = f"[Context compacted: {len(old_msgs)} older messages summarized, {len(recent_msgs)} recent messages preserved]"
        compacted_old = [AIMessage(content=summary_text)]

    return system_msgs + compacted_old + recent_msgs
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_compaction.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/compaction.py tests/test_compaction.py
git commit -m "feat: add context compression with micro-compact and token estimation"
```

---

### Task 7: Fix thread_id to include user_id (multi-user)

**Files:**
- Modify: `src/router.py` (fix `get_thread_id`)
- Create: `tests/test_session_multiuser.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_session_multiuser.py
"""Test multi-user session isolation via thread_id."""
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path


def test_thread_id_includes_user_id(tmp_path):
    """Thread ID must include user_id for multi-user isolation."""
    from src.router import MessageRouter
    from src.config import load_config

    # Create a minimal config
    config = _make_config(tmp_path)
    router = MessageRouter(agent=MagicMock(), config=config)

    # Same chat, different users → different thread IDs
    tid_alice = router.get_thread_id("telegram", "chat123", "alice")
    tid_bob = router.get_thread_id("telegram", "chat123", "bob")
    assert tid_alice != tid_bob
    assert "alice" in tid_alice
    assert "bob" in tid_bob


def test_thread_id_same_user_same_thread(tmp_path):
    """Same user in same chat → same thread ID."""
    from src.router import MessageRouter
    config = _make_config(tmp_path)
    router = MessageRouter(agent=MagicMock(), config=config)

    tid1 = router.get_thread_id("telegram", "chat123", "alice")
    tid2 = router.get_thread_id("telegram", "chat123", "alice")
    assert tid1 == tid2


def test_thread_id_format(tmp_path):
    """Thread ID format: {channel}_{chat_id}_{user_id}_s{counter}."""
    from src.router import MessageRouter
    config = _make_config(tmp_path)
    router = MessageRouter(agent=MagicMock(), config=config)

    tid = router.get_thread_id("telegram", "chat123", "alice")
    # Should match format (counter 0 may be omitted or included)
    assert tid.startswith("telegram_chat123_alice")


def _make_config(tmp_path):
    """Create minimal config for testing."""
    from src.config import AppConfig, AgentConfig, ProviderConfig, SchedulerConfig, GatewayConfig, SkillsConfig, TranscriptionConfig, ChannelsConfig, TelegramChannelConfig
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    return AppConfig(
        agent=AgentConfig(workspace=str(workspace), data_dir=str(data_dir)),
        provider=ProviderConfig(name="anthropic", model="test", api_key="test"),
        scheduler=SchedulerConfig(poll_interval=60),
        gateway=GatewayConfig(enabled=False),
        skills=SkillsConfig(enabled=False),
        transcription=TranscriptionConfig(enabled=False),
        channels=ChannelsConfig(telegram=TelegramChannelConfig(enabled=False)),
    )
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_session_multiuser.py -v
```

Expected: FAIL — `get_thread_id()` takes 3 args but 4 were given (missing user_id param)

- [ ] **Step 3: Fix router.get_thread_id to include user_id**

Read `src/router.py` and modify `get_thread_id` to accept and include `user_id`:

Change from:
```python
def get_thread_id(self, channel: str, chat_id: str) -> str:
    key = f"{channel}_{chat_id}"
```

To:
```python
def get_thread_id(self, channel: str, chat_id: str, user_id: str = "") -> str:
    if user_id:
        key = f"{channel}_{chat_id}_{user_id}"
    else:
        key = f"{channel}_{chat_id}"
```

Also update the `handle_message` call to pass `msg.user_id`:
```python
thread_id = self.get_thread_id(msg.channel, msg.chat_id, msg.user_id)
```

And update `reset_session` similarly:
```python
def reset_session(self, channel: str, chat_id: str, user_id: str = "") -> None:
    if user_id:
        key = f"{channel}_{chat_id}_{user_id}"
    else:
        key = f"{channel}_{chat_id}"
```

- [ ] **Step 4: Run tests to verify**

```bash
pytest tests/test_session_multiuser.py tests/test_router.py tests/test_router_extended.py -v --tb=short
```

Expected: New tests PASS, existing router tests still pass

- [ ] **Step 5: Commit**

```bash
git add src/router.py tests/test_session_multiuser.py
git commit -m "feat: include user_id in thread_id for multi-user session isolation"
```

---

### Task 8: Build the explicit StateGraph (replace create_deep_agent)

**Files:**
- Create: `src/core/nodes.py`
- Create: `src/core/graph.py`
- Create: `tests/test_core_graph.py`

This is the central task — replacing DeepAgents with our own graph.

- [ ] **Step 1: Write failing test for graph creation**

```python
# tests/test_core_graph.py
"""Test the explicit LangGraph StateGraph."""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from langchain_core.messages import HumanMessage, AIMessage


def test_graph_imports():
    from src.core.graph import build_agent_graph
    assert build_agent_graph is not None


def test_nodes_import():
    from src.core.nodes import agent_reasoning_node, tool_executor_node, permission_node
    assert agent_reasoning_node is not None


@pytest.mark.asyncio
async def test_graph_compiles():
    """Verify the graph compiles without errors."""
    from src.core.graph import build_agent_graph
    from langgraph.checkpoint.memory import MemorySaver

    mock_model = MagicMock()
    mock_model.bind_tools = MagicMock(return_value=mock_model)

    graph = build_agent_graph(model=mock_model, tools=[])
    checkpointer = MemorySaver()
    app = graph.compile(checkpointer=checkpointer)
    assert app is not None


@pytest.mark.asyncio
async def test_graph_simple_response():
    """Test that the graph handles a simple message (no tool calls)."""
    from src.core.graph import build_agent_graph
    from src.core.state import AgentState
    from langgraph.checkpoint.memory import MemorySaver

    # Mock model that returns a simple text response (no tool calls)
    mock_response = AIMessage(content="Hello! How can I help?")
    mock_model = MagicMock()
    mock_model.bind_tools = MagicMock(return_value=mock_model)
    mock_model.ainvoke = AsyncMock(return_value=mock_response)

    graph = build_agent_graph(model=mock_model, tools=[])
    app = graph.compile(checkpointer=MemorySaver())

    result = await app.ainvoke(
        {"messages": [HumanMessage(content="Hi")]},
        config={"configurable": {"thread_id": "test-1"}},
    )

    assert len(result["messages"]) >= 2  # User + AI
    assert "Hello" in result["messages"][-1].content
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_core_graph.py -v
```

Expected: FAIL

- [ ] **Step 3: Implement graph nodes**

```python
# src/core/nodes.py
"""Graph node implementations for the agent state graph.

Nodes:
- agent_reasoning_node: calls the LLM with RoutingChatModel
- permission_node: checks tool permissions, may interrupt for approval
- tool_executor_node: executes approved tool calls in parallel
- sub_agent_monitor_node: checks sub-agent health (placeholder for Phase 1C)
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from langchain_core.messages import AIMessage, ToolMessage

from .state import AgentState

logger = logging.getLogger(__name__)

# These are set by build_agent_graph() — avoids passing through state
_model = None
_tools_by_name: dict[str, Any] = {}
_permission_manager = None
_max_parallel_tools: int = 10


def configure_nodes(model, tools, permission_manager=None, max_parallel_tools=10):
    """Configure module-level references for nodes. Called once at graph build time."""
    global _model, _tools_by_name, _permission_manager, _max_parallel_tools
    _model = model
    _tools_by_name = {t.name: t for t in tools}
    _permission_manager = permission_manager
    _max_parallel_tools = max_parallel_tools


async def agent_reasoning_node(state: AgentState) -> dict:
    """Call the LLM with current messages and return its response."""
    response = await _model.ainvoke(state["messages"])
    return {"messages": [response]}


def route_after_reasoning(state: AgentState) -> str:
    """Route based on whether the LLM wants to use tools."""
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        if _permission_manager:
            return "permission_check"
        return "tools"
    return "__end__"


async def permission_node(state: AgentState) -> dict:
    """Check tool permissions. May interrupt for user approval."""
    # For now, pass through — full interrupt() implementation requires
    # channel-specific approval UI (Task for Phase 1A integration)
    return {}


def route_after_permission(state: AgentState) -> str:
    """Route after permission check."""
    # For now, always proceed to tools
    # Full implementation will check PermissionResult.action
    return "tools"


async def tool_executor_node(state: AgentState) -> dict:
    """Execute tool calls from the last AI message, in parallel."""
    last_message = state["messages"][-1]
    if not hasattr(last_message, "tool_calls") or not last_message.tool_calls:
        return {}

    tool_calls = last_message.tool_calls

    async def execute_one(tc: dict) -> ToolMessage:
        name = tc["name"]
        args = tc["args"]
        tool_call_id = tc["id"]
        tool = _tools_by_name.get(name)
        if not tool:
            return ToolMessage(
                content=f"Error: tool '{name}' not found",
                tool_call_id=tool_call_id,
            )
        try:
            result = await tool.ainvoke(args)
            content = str(result) if not isinstance(result, str) else result
        except Exception as e:
            logger.exception("Tool %s failed", name)
            content = f"Error executing {name}: {e}"
        return ToolMessage(content=content, tool_call_id=tool_call_id)

    # Execute in parallel with concurrency limit
    sem = asyncio.Semaphore(_max_parallel_tools)

    async def limited(tc):
        async with sem:
            return await execute_one(tc)

    results = await asyncio.gather(*(limited(tc) for tc in tool_calls))
    return {"messages": list(results)}


async def sub_agent_monitor_node(state: AgentState) -> dict:
    """Check sub-agent health. Placeholder for Phase 1C."""
    return {}
```

- [ ] **Step 4: Implement graph builder**

```python
# src/core/graph.py
"""Build the explicit LangGraph StateGraph for the agent."""
from __future__ import annotations

from typing import Any

from langgraph.graph import StateGraph, END

from .state import AgentState
from .nodes import (
    configure_nodes,
    agent_reasoning_node,
    route_after_reasoning,
    permission_node,
    route_after_permission,
    tool_executor_node,
    sub_agent_monitor_node,
)


def build_agent_graph(
    model,
    tools: list,
    permission_manager=None,
    max_parallel_tools: int = 10,
) -> StateGraph:
    """Build and return the agent StateGraph (uncompiled).
    
    Call .compile(checkpointer=...) on the returned graph to get a runnable.
    
    Args:
        model: LLM (or RoutingChatModel) to use for reasoning
        tools: List of LangChain tools available to the agent
        permission_manager: Optional PermissionManager for tool approval
        max_parallel_tools: Max concurrent tool executions
    
    Returns:
        StateGraph ready to compile
    """
    # Bind tools to model
    if tools:
        bound_model = model.bind_tools(tools)
    else:
        bound_model = model

    # Configure node module globals
    configure_nodes(
        model=bound_model,
        tools=tools,
        permission_manager=permission_manager,
        max_parallel_tools=max_parallel_tools,
    )

    # Build graph
    graph = StateGraph(AgentState)

    graph.add_node("agent", agent_reasoning_node)
    graph.add_node("permission_check", permission_node)
    graph.add_node("tools", tool_executor_node)
    graph.add_node("monitor", sub_agent_monitor_node)

    # Entry point
    graph.set_entry_point("agent")

    # Conditional edges from agent node
    graph.add_conditional_edges("agent", route_after_reasoning, {
        "permission_check": "permission_check",
        "tools": "tools",
        "__end__": END,
    })

    # Conditional edges from permission check
    graph.add_conditional_edges("permission_check", route_after_permission, {
        "tools": "tools",
        "agent": "agent",
    })

    # After tools, go back to agent for next reasoning step
    graph.add_edge("tools", "agent")

    # After monitor, go back to agent
    graph.add_edge("monitor", "agent")

    return graph
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_core_graph.py -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/core/nodes.py src/core/graph.py tests/test_core_graph.py
git commit -m "feat: implement explicit StateGraph with agent, permission, tools, monitor nodes"
```

---

### Task 9: Replace create_deep_agent() in agent.py

**Files:**
- Modify: `src/agent.py`

This is the integration task — rewire agent.py to use our graph instead of DeepAgents.

- [ ] **Step 1: Read current agent.py**

Read `src/agent.py` to understand the current flow.

- [ ] **Step 2: Replace create_deep_agent with build_agent_graph**

The key changes:
1. Remove `from deepagents import create_deep_agent`
2. Add `from .core.graph import build_agent_graph`
3. Replace the `create_deep_agent(...)` call with `build_agent_graph(...)` followed by `.compile(checkpointer=checkpointer)`
4. Keep all tool initialization (web, cron, host, model_router, MCP) exactly as-is
5. Keep RoutingChatModel exactly as-is
6. Keep the WorkspaceShellBackend for now (DeepAgents tools that need it will need adaptation)

**Important:** DeepAgents' `create_deep_agent()` automatically provides built-in tools (read_file, write_file, edit_file, exec, glob, grep). Our explicit graph does NOT have these — they come from DeepAgents. For Phase 1A, we keep DeepAgents as a dependency and use its tools, but wire them through our graph instead of its graph.

Read `deepagents` to find how to get its built-in tools:
```bash
python3 -c "from deepagents import get_default_tools; print([t.name for t in get_default_tools()])" 2>&1
```

If that doesn't work, check what tools DeepAgents provides and import them directly.

- [ ] **Step 3: Update agent.py**

Replace the bottom section of agent.py. Keep everything above the `create_deep_agent()` call. Replace from that line:

```python
    # Create agent — explicit StateGraph (replaces DeepAgents create_deep_agent)
    from .core.graph import build_agent_graph
    from .permissions.manager import PermissionManager

    permission_manager = PermissionManager(mode=config.permissions.mode if hasattr(config, 'permissions') else "default")

    graph = build_agent_graph(
        model=model,
        tools=all_tools,
        permission_manager=permission_manager,
        max_parallel_tools=getattr(config.agent, 'max_parallel_tools', 10),
    )

    agent = graph.compile(checkpointer=checkpointer)

    logger.info(
        "Agent created (explicit graph): %d tools, %d MCP tools, %d memory files",
        len(custom_tools), len(mcp_tools), len(memory_files),
    )

    return agent, checkpointer, mcp_client
```

**Note:** Memory file loading and skills directory loading were handled by DeepAgents. We'll need to handle context injection separately (in the router or as a system message). For now, the agent works without memory/skills injection — that's Task 10.

- [ ] **Step 4: Run existing tests to check for regressions**

```bash
pytest tests/test_config.py tests/test_router.py tests/test_model_router.py tests/test_tools_web.py tests/test_tools_cron.py tests/test_tools_host.py -v --tb=short
```

Expected: All pass (these don't test agent creation directly)

- [ ] **Step 5: Commit**

```bash
git add src/agent.py
git commit -m "feat: replace create_deep_agent with explicit StateGraph build_agent_graph"
```

---

### Task 10: Add memory context injection

**Files:**
- Create: `src/memory/__init__.py`
- Create: `src/memory/context.py`
- Create: `tests/test_memory_context.py`

Since we removed DeepAgents, memory files (IDENTITY.md, AGENT.md, MEMORY.md) are no longer auto-injected. We need to load them and inject as system message.

- [ ] **Step 1: Write failing test**

```python
# tests/test_memory_context.py
"""Test memory context injection."""
import pytest
from pathlib import Path


def test_context_builder_imports():
    from src.memory.context import build_memory_context
    assert build_memory_context is not None


def test_build_context_from_workspace(tmp_path):
    from src.memory.context import build_memory_context
    # Create memory files
    (tmp_path / "IDENTITY.md").write_text("I am LangAgent.")
    (tmp_path / "AGENT.md").write_text("Be helpful.")
    (tmp_path / "MEMORY.md").write_text("User likes Python.")

    context = build_memory_context(str(tmp_path))
    assert "I am LangAgent" in context
    assert "Be helpful" in context
    assert "User likes Python" in context


def test_build_context_missing_files(tmp_path):
    from src.memory.context import build_memory_context
    # Only one file exists
    (tmp_path / "IDENTITY.md").write_text("I am LangAgent.")

    context = build_memory_context(str(tmp_path))
    assert "I am LangAgent" in context
    # Should not crash on missing files


def test_build_context_empty_workspace(tmp_path):
    from src.memory.context import build_memory_context
    context = build_memory_context(str(tmp_path))
    assert isinstance(context, str)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_memory_context.py -v
```

Expected: FAIL

- [ ] **Step 3: Implement memory context builder**

```python
# src/memory/__init__.py
"""Memory system — persistent knowledge files and context injection."""
```

```python
# src/memory/context.py
"""Build memory context from workspace files for system prompt injection."""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Files to load (in order)
MEMORY_FILES = [
    ("IDENTITY.md", "Identity"),
    ("AGENT.md", "Agent Instructions"),
    ("MEMORY.md", "Memory"),
    ("AGENT_REGISTRY.md", "Agent Registry"),
    ("TEAM_PLAYBOOK.md", "Team Playbook"),
]


def build_memory_context(workspace: str, user_id: str = "") -> str:
    """Load memory files from workspace and build context string.
    
    Args:
        workspace: Path to workspace directory
        user_id: If provided, also loads per-user USER.md
    
    Returns:
        Combined context string for system prompt injection
    """
    workspace_path = Path(workspace)
    sections = []

    for filename, label in MEMORY_FILES:
        fpath = workspace_path / filename
        if fpath.exists():
            try:
                content = fpath.read_text(encoding="utf-8").strip()
                if content:
                    sections.append(f"## {label}\n\n{content}")
                    logger.debug("Loaded memory file: %s (%d chars)", filename, len(content))
            except Exception as e:
                logger.warning("Failed to read %s: %s", filename, e)

    # Per-user USER.md
    if user_id:
        user_file = workspace_path / "users" / user_id / "USER.md"
        if user_file.exists():
            try:
                content = user_file.read_text(encoding="utf-8").strip()
                if content:
                    sections.append(f"## User Preferences\n\n{content}")
            except Exception as e:
                logger.warning("Failed to read USER.md for %s: %s", user_id, e)

    return "\n\n---\n\n".join(sections)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_memory_context.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/memory/ tests/test_memory_context.py
git commit -m "feat: add memory context builder for system prompt injection"
```

---

### Task 11: Add config sections for new features

**Files:**
- Modify: `src/config.py`

- [ ] **Step 1: Read current config.py to find where to add sections**

Read `src/config.py` to understand the structure.

- [ ] **Step 2: Add new config sections**

Add the following Pydantic models to `src/config.py`:

```python
@dataclass
class PermissionsConfig:
    mode: str = "default"  # "default" | "auto" | "plan"

@dataclass
class StreamingConfig:
    enabled: bool = True
    token_batching_ms: int = 50
    show_thinking: bool = False
    show_tool_details: bool = True
    show_cost: bool = False

@dataclass
class ContextConfig:
    max_tokens: int = 128000
    compact_threshold: float = 0.8
    consolidate_threshold: float = 0.9
    preserve_recent_turns: int = 10

@dataclass
class CostConfig:
    budget_per_session: float | None = None
    budget_per_agent: float = 100.0
    on_budget_exceeded: str = "downgrade"  # "downgrade" | "pause" | "abort"
```

Add these as fields on the main AppConfig class with defaults.

- [ ] **Step 3: Update config.yaml with new sections**

```yaml
permissions:
  mode: "default"

streaming:
  enabled: true
  token_batching_ms: 50
  show_thinking: false
  show_tool_details: true
  show_cost: false

context:
  max_tokens: 128000
  compact_threshold: 0.8
  consolidate_threshold: 0.9
  preserve_recent_turns: 10

cost:
  budget_per_session: null
  budget_per_agent: 100.0
  on_budget_exceeded: "downgrade"
```

- [ ] **Step 4: Run config tests**

```bash
pytest tests/test_config.py -v --tb=short
```

Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add src/config.py config.yaml
git commit -m "feat: add permissions, streaming, context, cost config sections"
```

---

### Task 12: Integration — wire everything into main.py

**Files:**
- Modify: `src/main.py`
- Modify: `src/router.py`

- [ ] **Step 1: Update router to inject memory context**

In `router.py`'s `handle_message`, before invoking the agent, inject memory context as a system message. Read the current `handle_message` flow and add context injection:

```python
# In handle_message, before agent.ainvoke:
from .memory.context import build_memory_context

memory_ctx = build_memory_context(self._workspace, msg.user_id)
system_msg = {"role": "system", "content": memory_ctx} if memory_ctx else None
```

- [ ] **Step 2: Update main.py to pass new config to agent creation**

Pass permissions config and cost tracker through the system.

- [ ] **Step 3: Run full test suite**

```bash
pytest tests/ -q --tb=line --ignore=tests/test_middleware_bridge.py --ignore=tests/test_middleware_full.py
```

Expected: All existing tests pass, new tests pass

- [ ] **Step 4: Commit**

```bash
git add src/main.py src/router.py
git commit -m "feat: integrate memory context, permissions, and cost tracking into main loop"
```

---

### Task 13: Final verification and tag

- [ ] **Step 1: Run full test suite**

```bash
pytest tests/ -v --tb=short --ignore=tests/test_middleware_bridge.py --ignore=tests/test_middleware_full.py
```

Expected: All pass (except pre-existing 6 failures)

- [ ] **Step 2: Verify graph creates with real config**

```bash
python3 -c "
from src.config import load_config
print('Config loads OK')
from src.core.state import AgentState
print('AgentState OK')
from src.core.streaming import StreamEvent, EventType
print('StreamEvent OK:', len([x for x in dir(EventType) if not x.startswith('_')]), 'event types')
from src.permissions.manager import PermissionManager
print('PermissionManager OK')
from src.observability.cost import CostTracker
print('CostTracker OK')
from src.core.compaction import estimate_tokens, micro_compact
print('Compaction OK')
from src.memory.context import build_memory_context
print('Memory context OK')
from src.core.graph import build_agent_graph
print('Graph builder OK')
print('All Phase 1A modules verified!')
"
```

- [ ] **Step 3: Commit and tag**

```bash
git add -A
git commit -m "chore: Phase 1A complete — core agent rewrite with explicit StateGraph"
git tag v0.1.0-phase1a
```

---

## Exit Criteria

- [ ] `create_deep_agent()` replaced with explicit `StateGraph(AgentState)`
- [ ] AgentState has all spec fields (tier, user_id, cost, permissions, etc.)
- [ ] 4 graph nodes implemented: agent, permission_check, tools, monitor
- [ ] StreamEvent system with 14 event types and factory functions
- [ ] PermissionManager with 3 modes (default/auto/plan) and sensitive path protection
- [ ] CostTracker with per-tier, per-user, per-agent tracking
- [ ] FileStateTracker for read-before-edit warnings
- [ ] Context compression (micro-compact + token estimation)
- [ ] Thread_id includes user_id for multi-user isolation
- [ ] Memory context builder loads workspace files for system prompt
- [ ] Config sections added for permissions, streaming, context, cost
- [ ] All existing tests still pass
- [ ] Tagged as v0.1.0-phase1a

## What's deferred to later phases

- **LangGraph interrupt() for permission approvals** — requires channel-specific approval UI (Phase 2B)
- **Sub-agent monitor node** — placeholder, full implementation in Phase 1C
- **Dream memory** — Phase 1B
- **Reactive compaction** — integrated into agent loop in Phase 1B (compaction module exists, trigger logic needed)
- **Runner-level error recovery (GAP-13)** — Phase 1B (requires deeper integration with the agent loop)
- **Skills loading without DeepAgents** — may need DeepAgents' skill loader or our own implementation
