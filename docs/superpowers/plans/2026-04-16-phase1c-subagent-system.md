# Phase 1C: Sub-Agent System — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the sub-agent orchestration layer on top of DeepAgents — a registry tracking sub-agent state, orchestration tools (spawn/recall/monitor/assign/switch/escalate/review_cost), health monitoring, and priority-chain recovery.

**Architecture:** DeepAgents' `SubAgentMiddleware` provides the `task` tool for spawning ephemeral sub-agents, but they return a single result and exit. We layer a `SubAgentRegistry` on top that tracks long-running background agents (asyncio.Tasks), their state (SPAWNING/READY/RUNNING/BLOCKED/FINISHED/FAILED), heartbeat, cost, and artifacts. Orchestration tools operate on the registry. Health monitor runs as a background task checking heartbeats and triggering recovery. Recovery chain: retry → escalate → reassign → abort.

**Tech Stack:** asyncio, LangGraph BaseStore (InMemoryStore for dev, SQLite for prod), DeepAgents, Pydantic v2 for config, StreamEvent for broadcasting agent lifecycle

**Spec Reference:** `docs/superpowers/specs/2026-04-15-langagent-platform-design.md` — Sections 4.4, 7.3, 8, GAPs 1-4

**Prerequisites:** Phase 1B complete (665 tests passing, Dream memory, Management API, WebSocket EventHub)

---

## File Structure

### New files

```
src/subagent/
  __init__.py                   # Package init
  state.py                      # SubAgentState enum + AgentInfo dataclass
  registry.py                   # SubAgentRegistry — tracks active sub-agents
  store.py                      # BaseStore namespace helpers for agent communication
  health.py                     # HealthMonitor — heartbeat/timeout/iteration detection
  recovery.py                   # RecoveryChain — retry/escalate/reassign/abort
  context_recovery.py           # GAP-1 — build role-scoped recovery prompt
  tools.py                      # Orchestration tools: spawn_agent, recall_agent, etc.

tests/test_subagent_state.py    # State enum + AgentInfo tests
tests/test_subagent_registry.py # Registry tests
tests/test_subagent_store.py    # BaseStore helpers tests
tests/test_subagent_health.py   # Health monitor tests
tests/test_subagent_recovery.py # Recovery chain tests
tests/test_subagent_tools.py    # Orchestration tool tests
tests/test_subagent_context_recovery.py  # Recovery context builder tests
```

### Modified files

```
src/agent.py                    # Pass subagent registry to create_deep_agent
src/config.py                   # Add SubAgentConfig
src/main.py                     # Initialize SubAgentRegistry + HealthMonitor
config.yaml                     # Add subagent config defaults
```

---

### Task 1: Define SubAgentState enum and AgentInfo dataclass

**Files:**
- Create: `src/subagent/__init__.py`
- Create: `src/subagent/state.py`
- Create: `tests/test_subagent_state.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_subagent_state.py
"""Test SubAgentState enum and AgentInfo dataclass."""
import pytest


def test_state_imports():
    from src.subagent.state import SubAgentState, AgentInfo
    assert SubAgentState is not None
    assert AgentInfo is not None


def test_state_values():
    from src.subagent.state import SubAgentState
    assert SubAgentState.SPAWNING == "spawning"
    assert SubAgentState.READY == "ready"
    assert SubAgentState.RUNNING == "running"
    assert SubAgentState.BLOCKED == "blocked"
    assert SubAgentState.FINISHED == "finished"
    assert SubAgentState.FAILED == "failed"


def test_agent_info_creation():
    from src.subagent.state import AgentInfo, SubAgentState
    info = AgentInfo(
        agent_id="agent-abc",
        name="researcher",
        role="executor",
        task="Research topic X",
        tier="standard",
        tools=["web_search", "web_fetch"],
        skills=["summarize"],
    )
    assert info.agent_id == "agent-abc"
    assert info.state == SubAgentState.SPAWNING
    assert info.iteration == 0
    assert info.cost_cents == 0.0
    assert info.retry_count == 0


def test_agent_info_to_dict():
    from src.subagent.state import AgentInfo
    info = AgentInfo(
        agent_id="agent-abc",
        name="researcher",
        role="executor",
        task="Research",
        tier="standard",
        tools=["web_search"],
        skills=[],
    )
    d = info.to_dict()
    assert d["agent_id"] == "agent-abc"
    assert d["state"] == "spawning"
    assert d["cost_cents"] == 0.0


def test_agent_info_state_transitions():
    from src.subagent.state import AgentInfo, SubAgentState
    info = AgentInfo(
        agent_id="agent-abc",
        name="researcher",
        role="executor",
        task="Research",
        tier="standard",
        tools=[],
        skills=[],
    )
    assert info.state == SubAgentState.SPAWNING
    info.state = SubAgentState.RUNNING
    assert info.state == SubAgentState.RUNNING
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_subagent_state.py -v
```

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement state module**

```python
# src/subagent/__init__.py
"""Sub-agent system — registry, orchestration tools, health monitoring, recovery."""
```

```python
# src/subagent/state.py
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
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_subagent_state.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/subagent/__init__.py src/subagent/state.py tests/test_subagent_state.py
git commit -m "feat: add SubAgentState enum and AgentInfo dataclass"
```

---

### Task 2: BaseStore namespace helpers

**Files:**
- Create: `src/subagent/store.py`
- Create: `tests/test_subagent_store.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_subagent_store.py
"""Test BaseStore namespace helpers for agent communication."""
import pytest
from langgraph.store.memory import InMemoryStore


@pytest.mark.asyncio
async def test_store_imports():
    from src.subagent.store import AgentStore
    assert AgentStore is not None


@pytest.mark.asyncio
async def test_write_and_read_config():
    from src.subagent.store import AgentStore
    store = InMemoryStore()
    agent_store = AgentStore(store)

    await agent_store.write_config("agent-1", {"role": "executor", "tier": "standard", "task": "foo"})
    config = await agent_store.read_config("agent-1")
    assert config["role"] == "executor"
    assert config["tier"] == "standard"


@pytest.mark.asyncio
async def test_heartbeat():
    from src.subagent.store import AgentStore
    store = InMemoryStore()
    agent_store = AgentStore(store)

    await agent_store.write_heartbeat("agent-1", iteration=5, status="running")
    hb = await agent_store.read_heartbeat("agent-1")
    assert hb["iteration"] == 5
    assert hb["status"] == "running"
    assert "timestamp" in hb


@pytest.mark.asyncio
async def test_progress():
    from src.subagent.store import AgentStore
    store = InMemoryStore()
    agent_store = AgentStore(store)

    await agent_store.write_progress("agent-1", message="Analyzed 3/5 files", cost=0.5)
    p = await agent_store.read_progress("agent-1")
    assert p["message"] == "Analyzed 3/5 files"
    assert p["cost"] == 0.5


@pytest.mark.asyncio
async def test_result():
    from src.subagent.store import AgentStore
    store = InMemoryStore()
    agent_store = AgentStore(store)

    await agent_store.write_result("agent-1", status="success", output="Done!", cost_total=1.5)
    r = await agent_store.read_result("agent-1")
    assert r["status"] == "success"
    assert r["output"] == "Done!"


@pytest.mark.asyncio
async def test_directive():
    from src.subagent.store import AgentStore
    store = InMemoryStore()
    agent_store = AgentStore(store)

    await agent_store.write_directive("agent-1", action="shutdown", params={})
    d = await agent_store.read_directive("agent-1")
    assert d["action"] == "shutdown"


@pytest.mark.asyncio
async def test_read_nonexistent_returns_none():
    from src.subagent.store import AgentStore
    store = InMemoryStore()
    agent_store = AgentStore(store)
    assert await agent_store.read_config("missing") is None
    assert await agent_store.read_heartbeat("missing") is None


@pytest.mark.asyncio
async def test_inbox_send_and_receive():
    from src.subagent.store import AgentStore
    store = InMemoryStore()
    agent_store = AgentStore(store)

    await agent_store.send_inbox("agent-1", sender="master", message="Hello")
    await agent_store.send_inbox("agent-1", sender="master", message="World")
    msgs = await agent_store.drain_inbox("agent-1")
    assert len(msgs) == 2
    assert msgs[0]["message"] == "Hello"
    assert msgs[1]["message"] == "World"
    # After drain, inbox should be empty
    msgs2 = await agent_store.drain_inbox("agent-1")
    assert msgs2 == []
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_subagent_store.py -v
```

Expected: FAIL

- [ ] **Step 3: Implement store helpers**

```python
# src/subagent/store.py
"""BaseStore namespace helpers for master ↔ sub-agent communication.

Namespaces:
    ("agents", "{agent_id}") — Per-agent data (config, heartbeat, progress, result, inbox, directive)
    ("teams", "{team_id}")    — Per-team data (config, task_board, cost) — Phase 2A

All methods are async and use LangGraph's BaseStore (InMemoryStore for dev,
SQLite/Postgres-backed in production).
"""
from __future__ import annotations

import time
from typing import Any

from langgraph.store.base import BaseStore


class AgentStore:
    """Typed wrapper over BaseStore for sub-agent communication."""

    def __init__(self, store: BaseStore):
        self._store = store

    # ── Config (written by master at spawn) ──

    async def write_config(self, agent_id: str, config: dict) -> None:
        await self._store.aput(("agents", agent_id), "config", config)

    async def read_config(self, agent_id: str) -> dict | None:
        item = await self._store.aget(("agents", agent_id), "config")
        return item.value if item else None

    # ── Heartbeat (written by sub-agent periodically) ──

    async def write_heartbeat(self, agent_id: str, iteration: int = 0, status: str = "running") -> None:
        await self._store.aput(("agents", agent_id), "heartbeat", {
            "timestamp": time.time(),
            "iteration": iteration,
            "status": status,
        })

    async def read_heartbeat(self, agent_id: str) -> dict | None:
        item = await self._store.aget(("agents", agent_id), "heartbeat")
        return item.value if item else None

    # ── Progress (written by sub-agent after each step) ──

    async def write_progress(self, agent_id: str, message: str, cost: float = 0.0) -> None:
        await self._store.aput(("agents", agent_id), "progress", {
            "timestamp": time.time(),
            "message": message,
            "cost": cost,
        })

    async def read_progress(self, agent_id: str) -> dict | None:
        item = await self._store.aget(("agents", agent_id), "progress")
        return item.value if item else None

    # ── Result (written by sub-agent on completion) ──

    async def write_result(self, agent_id: str, status: str, output: str, cost_total: float = 0.0) -> None:
        await self._store.aput(("agents", agent_id), "result", {
            "timestamp": time.time(),
            "status": status,
            "output": output,
            "cost_total": cost_total,
        })

    async def read_result(self, agent_id: str) -> dict | None:
        item = await self._store.aget(("agents", agent_id), "result")
        return item.value if item else None

    # ── Directive (master → agent, e.g., shutdown, change_tier) ──

    async def write_directive(self, agent_id: str, action: str, params: dict | None = None) -> None:
        await self._store.aput(("agents", agent_id), "directive", {
            "timestamp": time.time(),
            "action": action,
            "params": params or {},
        })

    async def read_directive(self, agent_id: str) -> dict | None:
        item = await self._store.aget(("agents", agent_id), "directive")
        return item.value if item else None

    async def clear_directive(self, agent_id: str) -> None:
        await self._store.adelete(("agents", agent_id), "directive")

    # ── Inbox (master/agents → this agent) ──

    async def send_inbox(self, agent_id: str, sender: str, message: str) -> None:
        """Append a message to the agent's inbox."""
        current = await self._store.aget(("agents", agent_id), "inbox")
        messages = current.value if current else []
        messages.append({
            "timestamp": time.time(),
            "from": sender,
            "message": message,
        })
        await self._store.aput(("agents", agent_id), "inbox", messages)

    async def drain_inbox(self, agent_id: str) -> list[dict]:
        """Read and clear the agent's inbox."""
        current = await self._store.aget(("agents", agent_id), "inbox")
        messages = current.value if current else []
        if messages:
            await self._store.aput(("agents", agent_id), "inbox", [])
        return messages
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_subagent_store.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/subagent/store.py tests/test_subagent_store.py
git commit -m "feat: add AgentStore for BaseStore-based agent communication"
```

---

### Task 3: SubAgentRegistry

**Files:**
- Create: `src/subagent/registry.py`
- Create: `tests/test_subagent_registry.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_subagent_registry.py
"""Test SubAgentRegistry — tracks active sub-agents."""
import asyncio
import pytest
from langgraph.store.memory import InMemoryStore


@pytest.mark.asyncio
async def test_registry_imports():
    from src.subagent.registry import SubAgentRegistry
    assert SubAgentRegistry is not None


@pytest.mark.asyncio
async def test_registry_empty():
    from src.subagent.registry import SubAgentRegistry
    store = InMemoryStore()
    registry = SubAgentRegistry(store)
    assert registry.list_agents() == []
    assert registry.get_agent("missing") is None


@pytest.mark.asyncio
async def test_register_and_get():
    from src.subagent.registry import SubAgentRegistry
    from src.subagent.state import AgentInfo, SubAgentState

    store = InMemoryStore()
    registry = SubAgentRegistry(store)

    async def dummy_task():
        await asyncio.sleep(0.01)

    task = asyncio.create_task(dummy_task())
    info = AgentInfo(
        agent_id="agent-1", name="researcher", role="executor",
        task="Test", tier="standard", tools=[], skills=[],
    )
    registry.register(info, task)

    got = registry.get_agent("agent-1")
    assert got is info

    await task  # Clean up


@pytest.mark.asyncio
async def test_list_agents():
    from src.subagent.registry import SubAgentRegistry
    from src.subagent.state import AgentInfo

    store = InMemoryStore()
    registry = SubAgentRegistry(store)

    async def dummy():
        await asyncio.sleep(0.01)

    t1 = asyncio.create_task(dummy())
    t2 = asyncio.create_task(dummy())

    info1 = AgentInfo(agent_id="a1", name="n1", role="executor", task="t1", tier="standard", tools=[], skills=[])
    info2 = AgentInfo(agent_id="a2", name="n2", role="planner", task="t2", tier="advanced", tools=[], skills=[])
    registry.register(info1, t1)
    registry.register(info2, t2)

    agents = registry.list_agents()
    assert len(agents) == 2
    assert {a.agent_id for a in agents} == {"a1", "a2"}

    await asyncio.gather(t1, t2)


@pytest.mark.asyncio
async def test_update_state():
    from src.subagent.registry import SubAgentRegistry
    from src.subagent.state import AgentInfo, SubAgentState

    store = InMemoryStore()
    registry = SubAgentRegistry(store)

    async def dummy():
        await asyncio.sleep(0.01)

    t = asyncio.create_task(dummy())
    info = AgentInfo(agent_id="a1", name="n1", role="executor", task="t", tier="standard", tools=[], skills=[])
    registry.register(info, t)

    registry.update_state("a1", SubAgentState.RUNNING)
    assert registry.get_agent("a1").state == SubAgentState.RUNNING

    await t


@pytest.mark.asyncio
async def test_deregister_cancels_task():
    from src.subagent.registry import SubAgentRegistry
    from src.subagent.state import AgentInfo

    store = InMemoryStore()
    registry = SubAgentRegistry(store)

    async def long_running():
        await asyncio.sleep(10)

    t = asyncio.create_task(long_running())
    info = AgentInfo(agent_id="a1", name="n1", role="executor", task="t", tier="standard", tools=[], skills=[])
    registry.register(info, t)

    await registry.deregister("a1")
    # Give time for cancellation
    await asyncio.sleep(0.05)
    assert registry.get_agent("a1") is None
    assert t.cancelled() or t.done()


@pytest.mark.asyncio
async def test_deregister_nonexistent():
    from src.subagent.registry import SubAgentRegistry
    store = InMemoryStore()
    registry = SubAgentRegistry(store)
    # Should not raise
    await registry.deregister("missing")


@pytest.mark.asyncio
async def test_filter_by_state():
    from src.subagent.registry import SubAgentRegistry
    from src.subagent.state import AgentInfo, SubAgentState

    store = InMemoryStore()
    registry = SubAgentRegistry(store)

    async def dummy():
        await asyncio.sleep(0.01)

    for i in range(3):
        t = asyncio.create_task(dummy())
        info = AgentInfo(agent_id=f"a{i}", name=f"n{i}", role="executor", task="t", tier="standard", tools=[], skills=[])
        registry.register(info, t)

    registry.update_state("a0", SubAgentState.RUNNING)
    registry.update_state("a1", SubAgentState.FINISHED)
    # a2 stays SPAWNING

    running = registry.filter_by_state(SubAgentState.RUNNING)
    assert len(running) == 1
    assert running[0].agent_id == "a0"

    finished = registry.filter_by_state(SubAgentState.FINISHED)
    assert len(finished) == 1

    # Clean up all tasks
    await asyncio.sleep(0.05)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_subagent_registry.py -v
```

Expected: FAIL

- [ ] **Step 3: Implement registry**

```python
# src/subagent/registry.py
"""SubAgentRegistry — tracks active sub-agents and their asyncio tasks."""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from langgraph.store.base import BaseStore

from .state import AgentInfo, SubAgentState
from .store import AgentStore

logger = logging.getLogger(__name__)


class SubAgentRegistry:
    """Registry of active sub-agents.

    Tracks AgentInfo (state, cost, iteration) and the backing asyncio.Task
    for each sub-agent. Also wraps an AgentStore for BaseStore communication.
    """

    def __init__(self, store: BaseStore):
        self._store = store
        self._agent_store = AgentStore(store)
        self._agents: dict[str, AgentInfo] = {}
        self._tasks: dict[str, asyncio.Task] = {}

    @property
    def agent_store(self) -> AgentStore:
        return self._agent_store

    def register(self, info: AgentInfo, task: asyncio.Task) -> None:
        """Register a new sub-agent and its backing task."""
        self._agents[info.agent_id] = info
        self._tasks[info.agent_id] = task
        logger.info("Registered sub-agent %s (name=%s, role=%s)", info.agent_id, info.name, info.role)

    def get_agent(self, agent_id: str) -> Optional[AgentInfo]:
        return self._agents.get(agent_id)

    def get_task(self, agent_id: str) -> Optional[asyncio.Task]:
        return self._tasks.get(agent_id)

    def list_agents(self) -> list[AgentInfo]:
        return list(self._agents.values())

    def filter_by_state(self, state: SubAgentState) -> list[AgentInfo]:
        return [a for a in self._agents.values() if a.state == state]

    def filter_by_role(self, role: str) -> list[AgentInfo]:
        return [a for a in self._agents.values() if a.role == role]

    def update_state(self, agent_id: str, new_state: SubAgentState) -> None:
        info = self._agents.get(agent_id)
        if info:
            old = info.state
            info.state = new_state
            logger.debug("Sub-agent %s state: %s → %s", agent_id, old, new_state)

    def update_cost(self, agent_id: str, cost_cents: float) -> None:
        info = self._agents.get(agent_id)
        if info:
            info.cost_cents = cost_cents

    def increment_iteration(self, agent_id: str) -> None:
        info = self._agents.get(agent_id)
        if info:
            info.iteration += 1

    async def deregister(self, agent_id: str) -> None:
        """Cancel the agent's task and remove from registry."""
        task = self._tasks.pop(agent_id, None)
        info = self._agents.pop(agent_id, None)
        if task and not task.done():
            task.cancel()
            try:
                await asyncio.wait_for(task, timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
        if info:
            logger.info("Deregistered sub-agent %s", agent_id)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_subagent_registry.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/subagent/registry.py tests/test_subagent_registry.py
git commit -m "feat: add SubAgentRegistry for tracking active sub-agents"
```

---

### Task 4: Context Recovery Builder (GAP-1)

**Files:**
- Create: `src/subagent/context_recovery.py`
- Create: `tests/test_subagent_context_recovery.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_subagent_context_recovery.py
"""Test context recovery prompt builder (GAP-1)."""
import pytest
from langgraph.store.memory import InMemoryStore


@pytest.mark.asyncio
async def test_context_recovery_imports():
    from src.subagent.context_recovery import build_recovery_context
    assert build_recovery_context is not None


@pytest.mark.asyncio
async def test_build_recovery_context_with_progress():
    from src.subagent.context_recovery import build_recovery_context
    from src.subagent.store import AgentStore

    store = InMemoryStore()
    agent_store = AgentStore(store)

    await agent_store.write_config("a1", {"role": "executor", "task": "Build REST API"})
    await agent_store.write_progress("a1", message="Designed schema, 3/5 endpoints done", cost=1.2)

    ctx = await build_recovery_context(
        agent_id="a1",
        role="executor",
        store=store,
    )
    assert "executor" in ctx
    assert "3/5 endpoints" in ctx


@pytest.mark.asyncio
async def test_build_recovery_no_data():
    from src.subagent.context_recovery import build_recovery_context

    store = InMemoryStore()
    ctx = await build_recovery_context(agent_id="nonexistent", role="executor", store=store)
    # Should still return a string, not crash
    assert "executor" in ctx
    assert isinstance(ctx, str)


@pytest.mark.asyncio
async def test_build_recovery_includes_iteration():
    from src.subagent.context_recovery import build_recovery_context
    from src.subagent.store import AgentStore

    store = InMemoryStore()
    agent_store = AgentStore(store)
    await agent_store.write_heartbeat("a1", iteration=12, status="running")

    ctx = await build_recovery_context(agent_id="a1", role="executor", store=store)
    assert "12" in ctx or "iteration" in ctx.lower()


@pytest.mark.asyncio
async def test_evaluator_sees_team_status():
    """Evaluators see all agents' status, executors only their own."""
    from src.subagent.context_recovery import build_recovery_context
    from src.subagent.store import AgentStore

    store = InMemoryStore()
    agent_store = AgentStore(store)
    await agent_store.write_config("a1", {"role": "evaluator", "task": "Review code"})

    # Seed other agents' progress
    await agent_store.write_progress("other-1", message="Worker 1 done", cost=0)
    await agent_store.write_progress("other-2", message="Worker 2 running", cost=0)

    ctx = await build_recovery_context(
        agent_id="a1",
        role="evaluator",
        store=store,
        all_agent_ids=["other-1", "other-2"],
    )
    assert "Team status" in ctx or "other-1" in ctx or "Worker" in ctx
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_subagent_context_recovery.py -v
```

Expected: FAIL

- [ ] **Step 3: Implement context recovery**

```python
# src/subagent/context_recovery.py
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
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_subagent_context_recovery.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/subagent/context_recovery.py tests/test_subagent_context_recovery.py
git commit -m "feat: add context recovery prompt builder (GAP-1)"
```

---

### Task 5: Health Monitor (3-layer detection)

**Files:**
- Create: `src/subagent/health.py`
- Create: `tests/test_subagent_health.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_subagent_health.py
"""Test HealthMonitor — 3-layer failure detection."""
import asyncio
import pytest
import time
from langgraph.store.memory import InMemoryStore


@pytest.mark.asyncio
async def test_health_imports():
    from src.subagent.health import HealthMonitor, FailureReason
    assert HealthMonitor is not None
    assert FailureReason is not None


@pytest.mark.asyncio
async def test_detect_stale_heartbeat():
    """Heartbeat older than threshold triggers STALE_HEARTBEAT."""
    from src.subagent.health import HealthMonitor, FailureReason
    from src.subagent.registry import SubAgentRegistry
    from src.subagent.state import AgentInfo

    store = InMemoryStore()
    registry = SubAgentRegistry(store)

    async def dummy():
        await asyncio.sleep(10)

    task = asyncio.create_task(dummy())
    info = AgentInfo(
        agent_id="a1", name="n1", role="executor", task="t",
        tier="standard", tools=[], skills=[],
    )
    # Simulate a stale heartbeat (set last_heartbeat to 200s ago)
    info.last_heartbeat = time.time() - 200
    registry.register(info, task)

    monitor = HealthMonitor(registry, heartbeat_timeout=120, task_timeout=1800, max_iterations=50)
    failure = monitor.check_agent("a1")
    assert failure == FailureReason.STALE_HEARTBEAT

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_detect_iteration_limit():
    from src.subagent.health import HealthMonitor, FailureReason
    from src.subagent.registry import SubAgentRegistry
    from src.subagent.state import AgentInfo

    store = InMemoryStore()
    registry = SubAgentRegistry(store)

    async def dummy():
        await asyncio.sleep(10)

    task = asyncio.create_task(dummy())
    info = AgentInfo(
        agent_id="a1", name="n1", role="executor", task="t",
        tier="standard", tools=[], skills=[],
    )
    info.iteration = 60  # Over default limit
    info.last_heartbeat = time.time()  # Fresh heartbeat
    registry.register(info, task)

    monitor = HealthMonitor(registry, heartbeat_timeout=120, task_timeout=1800, max_iterations=50)
    failure = monitor.check_agent("a1")
    assert failure == FailureReason.ITERATION_LIMIT

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_detect_task_timeout():
    from src.subagent.health import HealthMonitor, FailureReason
    from src.subagent.registry import SubAgentRegistry
    from src.subagent.state import AgentInfo

    store = InMemoryStore()
    registry = SubAgentRegistry(store)

    async def dummy():
        await asyncio.sleep(10)

    task = asyncio.create_task(dummy())
    info = AgentInfo(
        agent_id="a1", name="n1", role="executor", task="t",
        tier="standard", tools=[], skills=[],
    )
    info.created_at = time.time() - 2000  # Over task_timeout
    info.last_heartbeat = time.time()
    info.iteration = 1
    registry.register(info, task)

    monitor = HealthMonitor(registry, heartbeat_timeout=120, task_timeout=1800, max_iterations=50)
    failure = monitor.check_agent("a1")
    assert failure == FailureReason.TASK_TIMEOUT

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_healthy_agent_returns_none():
    from src.subagent.health import HealthMonitor
    from src.subagent.registry import SubAgentRegistry
    from src.subagent.state import AgentInfo

    store = InMemoryStore()
    registry = SubAgentRegistry(store)

    async def dummy():
        await asyncio.sleep(10)

    task = asyncio.create_task(dummy())
    info = AgentInfo(
        agent_id="a1", name="n1", role="executor", task="t",
        tier="standard", tools=[], skills=[],
    )
    info.last_heartbeat = time.time()  # Fresh
    info.iteration = 5                  # Under limit
    info.created_at = time.time()       # Just created
    registry.register(info, task)

    monitor = HealthMonitor(registry, heartbeat_timeout=120, task_timeout=1800, max_iterations=50)
    failure = monitor.check_agent("a1")
    assert failure is None

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_check_all():
    """check_all returns dict mapping agent_id → failure_reason (only for unhealthy)."""
    from src.subagent.health import HealthMonitor
    from src.subagent.registry import SubAgentRegistry
    from src.subagent.state import AgentInfo

    store = InMemoryStore()
    registry = SubAgentRegistry(store)

    async def dummy():
        await asyncio.sleep(10)

    # Healthy
    t1 = asyncio.create_task(dummy())
    i1 = AgentInfo(agent_id="a1", name="n1", role="executor", task="t", tier="standard", tools=[], skills=[])
    i1.last_heartbeat = time.time()
    registry.register(i1, t1)

    # Stale
    t2 = asyncio.create_task(dummy())
    i2 = AgentInfo(agent_id="a2", name="n2", role="executor", task="t", tier="standard", tools=[], skills=[])
    i2.last_heartbeat = time.time() - 500
    registry.register(i2, t2)

    monitor = HealthMonitor(registry, heartbeat_timeout=120, task_timeout=1800, max_iterations=50)
    results = monitor.check_all()
    assert "a1" not in results
    assert "a2" in results

    t1.cancel()
    t2.cancel()
    try:
        await asyncio.gather(t1, t2)
    except asyncio.CancelledError:
        pass
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_subagent_health.py -v
```

Expected: FAIL

- [ ] **Step 3: Implement HealthMonitor**

```python
# src/subagent/health.py
"""HealthMonitor — 3-layer failure detection for sub-agents.

Layers:
- Heartbeat: stale heartbeat (>120s by default)
- Task timeout: asyncio.Task running too long (>30min by default)
- Iteration limit: too many tool-call cycles (>50 by default)
"""
from __future__ import annotations

import logging
import time
from enum import Enum

from .registry import SubAgentRegistry
from .state import SubAgentState

logger = logging.getLogger(__name__)


class FailureReason(str, Enum):
    STALE_HEARTBEAT = "stale_heartbeat"
    TASK_TIMEOUT = "task_timeout"
    ITERATION_LIMIT = "iteration_limit"


class HealthMonitor:
    """Detect failing sub-agents via heartbeat, timeout, and iteration limits."""

    def __init__(
        self,
        registry: SubAgentRegistry,
        heartbeat_timeout: float = 120.0,     # seconds
        task_timeout: float = 1800.0,          # seconds (30 min)
        max_iterations: int = 50,
    ):
        self._registry = registry
        self._heartbeat_timeout = heartbeat_timeout
        self._task_timeout = task_timeout
        self._max_iterations = max_iterations

    def check_agent(self, agent_id: str) -> FailureReason | None:
        """Check one agent. Returns failure reason or None if healthy."""
        info = self._registry.get_agent(agent_id)
        if info is None:
            return None

        # Skip terminal states
        if info.state in (SubAgentState.FINISHED, SubAgentState.FAILED):
            return None

        now = time.time()

        # Iteration limit check
        if info.iteration > self._max_iterations:
            return FailureReason.ITERATION_LIMIT

        # Task timeout check
        if (now - info.created_at) > self._task_timeout:
            return FailureReason.TASK_TIMEOUT

        # Heartbeat check (only applies if agent is past SPAWNING)
        if info.state != SubAgentState.SPAWNING:
            if (now - info.last_heartbeat) > self._heartbeat_timeout:
                return FailureReason.STALE_HEARTBEAT

        return None

    def check_all(self) -> dict[str, FailureReason]:
        """Check all registered agents. Returns dict of unhealthy agents."""
        results: dict[str, FailureReason] = {}
        for info in self._registry.list_agents():
            reason = self.check_agent(info.agent_id)
            if reason is not None:
                results[info.agent_id] = reason
        return results
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_subagent_health.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/subagent/health.py tests/test_subagent_health.py
git commit -m "feat: add HealthMonitor with 3-layer failure detection"
```

---

### Task 6: Recovery Chain

**Files:**
- Create: `src/subagent/recovery.py`
- Create: `tests/test_subagent_recovery.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_subagent_recovery.py
"""Test RecoveryChain — priority-chain recovery."""
import pytest
from langgraph.store.memory import InMemoryStore


def test_recovery_imports():
    from src.subagent.recovery import RecoveryChain, RecoveryAction
    assert RecoveryChain is not None
    assert RecoveryAction is not None


def test_recovery_action_values():
    from src.subagent.recovery import RecoveryAction
    assert RecoveryAction.RETRY == "retry"
    assert RecoveryAction.ESCALATE == "escalate"
    assert RecoveryAction.REASSIGN == "reassign"
    assert RecoveryAction.ABORT == "abort"


def test_next_tier():
    from src.subagent.recovery import next_tier
    assert next_tier("lite") == "standard"
    assert next_tier("standard") == "advanced"
    assert next_tier("advanced") == "expert"
    assert next_tier("expert") is None  # Top tier


def test_decide_action_first_retry():
    """First failure → RETRY."""
    from src.subagent.recovery import RecoveryChain
    from src.subagent.state import AgentInfo

    chain = RecoveryChain(max_retries=1)
    info = AgentInfo(agent_id="a1", name="n", role="executor", task="t", tier="standard", tools=[], skills=[])
    info.retry_count = 0
    action = chain.decide_action(info)
    assert action.value == "retry"


def test_decide_action_after_retries_escalate():
    """After max retries at same tier → ESCALATE."""
    from src.subagent.recovery import RecoveryChain
    from src.subagent.state import AgentInfo

    chain = RecoveryChain(max_retries=1)
    info = AgentInfo(agent_id="a1", name="n", role="executor", task="t", tier="standard", tools=[], skills=[])
    info.retry_count = 1  # Already retried once
    action = chain.decide_action(info)
    assert action.value == "escalate"


def test_decide_action_expert_tier_reassign():
    """At expert tier with retries exhausted → REASSIGN."""
    from src.subagent.recovery import RecoveryChain
    from src.subagent.state import AgentInfo

    chain = RecoveryChain(max_retries=1)
    info = AgentInfo(agent_id="a1", name="n", role="executor", task="t", tier="expert", tools=[], skills=[])
    info.retry_count = 1
    action = chain.decide_action(info)
    assert action.value == "reassign"


def test_decide_action_after_reassign_abort():
    """After 3+ failure cycles → ABORT."""
    from src.subagent.recovery import RecoveryChain
    from src.subagent.state import AgentInfo

    chain = RecoveryChain(max_retries=1)
    info = AgentInfo(agent_id="a1", name="n", role="executor", task="t", tier="expert", tools=[], skills=[])
    info.retry_count = 5  # Way over
    action = chain.decide_action(info)
    assert action.value == "abort"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_subagent_recovery.py -v
```

Expected: FAIL

- [ ] **Step 3: Implement recovery**

```python
# src/subagent/recovery.py
"""RecoveryChain — priority-chain failure recovery for sub-agents.

Chain:
  1. RETRY (same tier, new attempt with recovery context)
  2. ESCALATE (higher tier, if available)
  3. REASSIGN (different agent, different role/skills)
  4. ABORT (give up, notify user)
"""
from __future__ import annotations

import logging
from enum import Enum

from .state import AgentInfo

logger = logging.getLogger(__name__)

_TIER_ORDER = ["lite", "standard", "advanced", "expert"]


class RecoveryAction(str, Enum):
    RETRY = "retry"
    ESCALATE = "escalate"
    REASSIGN = "reassign"
    ABORT = "abort"


def next_tier(current_tier: str) -> str | None:
    """Return the next higher tier, or None if already at top."""
    try:
        idx = _TIER_ORDER.index(current_tier)
    except ValueError:
        return None
    if idx + 1 < len(_TIER_ORDER):
        return _TIER_ORDER[idx + 1]
    return None


class RecoveryChain:
    """Decide recovery action based on agent history."""

    def __init__(self, max_retries: int = 1):
        self._max_retries = max_retries

    def decide_action(self, info: AgentInfo) -> RecoveryAction:
        """Decide what action to take for a failed agent.

        Logic:
          - retry_count < max_retries → RETRY
          - Otherwise, if higher tier available → ESCALATE
          - Otherwise, if retry_count < max_retries * 3 → REASSIGN
          - Otherwise → ABORT
        """
        retries = info.retry_count

        # First failure at current tier → retry
        if retries < self._max_retries:
            return RecoveryAction.RETRY

        # Retries exhausted at this tier → try escalation
        higher = next_tier(info.tier)
        if higher is not None and retries < self._max_retries * 2:
            return RecoveryAction.ESCALATE

        # No higher tier or escalation also failed → reassign
        if retries < self._max_retries * 3:
            return RecoveryAction.REASSIGN

        # Give up
        return RecoveryAction.ABORT
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_subagent_recovery.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/subagent/recovery.py tests/test_subagent_recovery.py
git commit -m "feat: add RecoveryChain with retry→escalate→reassign→abort logic"
```

---

### Task 7: Orchestration Tools

**Files:**
- Create: `src/subagent/tools.py`
- Create: `tests/test_subagent_tools.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_subagent_tools.py
"""Test orchestration tools: spawn_agent, recall_agent, monitor_agents, etc."""
import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock
from langgraph.store.memory import InMemoryStore


def test_tools_imports():
    from src.subagent.tools import (
        init_orchestration_tools,
        spawn_agent,
        recall_agent,
        monitor_agents,
        assign_task,
        switch_agent_model,
        review_cost,
    )
    assert spawn_agent is not None


@pytest.mark.asyncio
async def test_spawn_agent_registers():
    """spawn_agent should create an AgentInfo and register it."""
    from src.subagent.registry import SubAgentRegistry
    from src.subagent.state import SubAgentState
    from src.subagent.tools import init_orchestration_tools, spawn_agent

    store = InMemoryStore()
    registry = SubAgentRegistry(store)

    # Mock the spawner that creates the actual asyncio task
    async def mock_spawner(info, **kwargs):
        async def dummy():
            await asyncio.sleep(0.01)
        return asyncio.create_task(dummy())

    init_orchestration_tools(registry=registry, spawner=mock_spawner, cost_tracker=None)

    result = await spawn_agent.ainvoke({
        "name": "researcher",
        "role": "executor",
        "task": "Research topic X",
        "tools": ["web_search"],
        "tier": "standard",
    })

    assert "agent-" in result  # Returns the agent_id
    agents = registry.list_agents()
    assert len(agents) == 1
    assert agents[0].name == "researcher"
    assert agents[0].role == "executor"

    # Clean up
    await registry.deregister(agents[0].agent_id)


@pytest.mark.asyncio
async def test_monitor_agents_returns_status():
    from src.subagent.registry import SubAgentRegistry
    from src.subagent.state import AgentInfo
    from src.subagent.tools import init_orchestration_tools, monitor_agents

    store = InMemoryStore()
    registry = SubAgentRegistry(store)

    async def dummy():
        await asyncio.sleep(0.01)

    t = asyncio.create_task(dummy())
    info = AgentInfo(
        agent_id="a1", name="researcher", role="executor",
        task="Research", tier="standard", tools=["web_search"], skills=[],
    )
    registry.register(info, t)

    init_orchestration_tools(registry=registry, spawner=None, cost_tracker=None)
    result = await monitor_agents.ainvoke({})
    assert "researcher" in result
    assert "a1" in result or "executor" in result

    await t


@pytest.mark.asyncio
async def test_recall_agent():
    from src.subagent.registry import SubAgentRegistry
    from src.subagent.state import AgentInfo
    from src.subagent.tools import init_orchestration_tools, recall_agent

    store = InMemoryStore()
    registry = SubAgentRegistry(store)

    async def dummy():
        await asyncio.sleep(10)

    t = asyncio.create_task(dummy())
    info = AgentInfo(
        agent_id="a1", name="researcher", role="executor",
        task="Research", tier="standard", tools=[], skills=[],
    )
    registry.register(info, t)

    init_orchestration_tools(registry=registry, spawner=None, cost_tracker=None)
    result = await recall_agent.ainvoke({"agent_id": "a1"})
    assert "recalled" in result.lower() or "a1" in result
    await asyncio.sleep(0.1)
    assert registry.get_agent("a1") is None


@pytest.mark.asyncio
async def test_switch_agent_model():
    from src.subagent.registry import SubAgentRegistry
    from src.subagent.state import AgentInfo
    from src.subagent.tools import init_orchestration_tools, switch_agent_model

    store = InMemoryStore()
    registry = SubAgentRegistry(store)

    async def dummy():
        await asyncio.sleep(10)

    t = asyncio.create_task(dummy())
    info = AgentInfo(
        agent_id="a1", name="researcher", role="executor",
        task="Research", tier="standard", tools=[], skills=[],
    )
    registry.register(info, t)

    init_orchestration_tools(registry=registry, spawner=None, cost_tracker=None)
    result = await switch_agent_model.ainvoke({"agent_id": "a1", "tier": "advanced"})
    assert "advanced" in result
    assert registry.get_agent("a1").tier == "advanced"

    t.cancel()
    try:
        await t
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_review_cost():
    from src.observability.cost import CostTracker
    from src.subagent.registry import SubAgentRegistry
    from src.subagent.tools import init_orchestration_tools, review_cost

    store = InMemoryStore()
    registry = SubAgentRegistry(store)
    tracker = CostTracker()
    tracker.record(provider="anthropic", model="claude-sonnet-4-6",
                   prompt_tokens=1000, completion_tokens=500,
                   user_id="u1", tier="standard")

    init_orchestration_tools(registry=registry, spawner=None, cost_tracker=tracker)
    result = await review_cost.ainvoke({})
    assert "cost" in result.lower() or "tokens" in result.lower()


@pytest.mark.asyncio
async def test_assign_task():
    from src.subagent.registry import SubAgentRegistry
    from src.subagent.state import AgentInfo
    from src.subagent.tools import init_orchestration_tools, assign_task

    store = InMemoryStore()
    registry = SubAgentRegistry(store)

    async def dummy():
        await asyncio.sleep(10)

    t = asyncio.create_task(dummy())
    info = AgentInfo(
        agent_id="a1", name="researcher", role="executor",
        task="Research", tier="standard", tools=[], skills=[],
    )
    registry.register(info, t)

    init_orchestration_tools(registry=registry, spawner=None, cost_tracker=None)
    result = await assign_task.ainvoke({"agent_id": "a1", "task": "New task"})
    assert "a1" in result or "assigned" in result.lower()

    # Inbox should have the message
    inbox = await registry.agent_store.drain_inbox("a1")
    assert len(inbox) == 1
    assert "New task" in inbox[0]["message"]

    t.cancel()
    try:
        await t
    except asyncio.CancelledError:
        pass
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_subagent_tools.py -v
```

Expected: FAIL

- [ ] **Step 3: Implement orchestration tools**

```python
# src/subagent/tools.py
"""Orchestration tools — spawn_agent, recall_agent, monitor_agents, etc.

These tools are given to the master agent so it can manage sub-agents.
The tools operate on a module-level SubAgentRegistry set by init_orchestration_tools.
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Callable, Optional

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
                 signature: async spawner(info: AgentInfo, **kwargs) → asyncio.Task
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
        lines.append(
            f"  - {info.agent_id} [{info.name}/{info.role}/{info.tier}] "
            f"state={info.state.value if hasattr(info.state, 'value') else info.state} "
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
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_subagent_tools.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/subagent/tools.py tests/test_subagent_tools.py
git commit -m "feat: add orchestration tools (spawn, recall, monitor, assign, switch, review_cost)"
```

---

### Task 8: Wire subagent system into main.py

**Files:**
- Modify: `src/agent.py`
- Modify: `src/main.py`
- Modify: `src/config.py`
- Modify: `config.yaml`

- [ ] **Step 1: Add SubAgentConfig to config.py**

Read `src/config.py` first. Then add a `SubAgentConfig` Pydantic BaseModel:

```python
class SubAgentConfig(BaseModel):
    enabled: bool = True
    heartbeat_timeout: float = 120.0
    task_timeout: float = 1800.0
    max_iterations: int = 50
    max_retries: int = 1
    health_check_interval: float = 30.0  # How often HealthMonitor runs
```

Add as field on `AppConfig`:
```python
subagent: SubAgentConfig = Field(default_factory=SubAgentConfig)
```

- [ ] **Step 2: Add subagent section to config.yaml**

```yaml
subagent:
  enabled: true
  heartbeat_timeout: 120.0
  task_timeout: 1800.0
  max_iterations: 50
  max_retries: 1
  health_check_interval: 30.0
```

- [ ] **Step 3: Modify src/agent.py to add orchestration tools**

Read `src/agent.py` to find where custom_tools is built. Add the orchestration tools when subagent is enabled. Before the `create_deep_agent` call:

```python
    # Orchestration tools (sub-agent management)
    from langgraph.store.memory import InMemoryStore
    subagent_registry = None
    if config.subagent.enabled:
        from .subagent.registry import SubAgentRegistry
        from .subagent.tools import (
            init_orchestration_tools,
            spawn_agent, recall_agent, monitor_agents,
            assign_task, switch_agent_model, review_cost,
        )
        subagent_store = InMemoryStore()
        subagent_registry = SubAgentRegistry(subagent_store)
        init_orchestration_tools(
            registry=subagent_registry,
            spawner=None,  # Phase 2A will wire actual DeepAgents-based spawner
            cost_tracker=None,  # Phase 2A
        )
        custom_tools.extend([
            spawn_agent, recall_agent, monitor_agents,
            assign_task, switch_agent_model, review_cost,
        ])
        logger.info("Orchestration tools enabled (6 tools)")
```

Return `subagent_registry` from `create_agent` — update the return tuple:
```python
    return agent, checkpointer, mcp_client, subagent_registry
```

- [ ] **Step 4: Update main.py to consume subagent_registry**

Read `src/main.py`. Update the `create_agent()` call to unpack 4 values:
```python
    agent, checkpointer, mcp_client, subagent_registry = await create_agent(config)
```

Then start the HealthMonitor as a background task if enabled:
```python
    # Health monitor background task
    health_task = None
    if config.subagent.enabled and subagent_registry:
        from .subagent.health import HealthMonitor
        monitor = HealthMonitor(
            registry=subagent_registry,
            heartbeat_timeout=config.subagent.heartbeat_timeout,
            task_timeout=config.subagent.task_timeout,
            max_iterations=config.subagent.max_iterations,
        )
        async def health_loop():
            interval = config.subagent.health_check_interval
            while True:
                await asyncio.sleep(interval)
                try:
                    unhealthy = monitor.check_all()
                    if unhealthy:
                        logger.warning("Unhealthy sub-agents: %s", unhealthy)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error("Health monitor error: %s", e)
        health_task = asyncio.create_task(health_loop())
        logger.info("Health monitor started (interval: %.1fs)", config.subagent.health_check_interval)
```

In the cleanup section, cancel health_task:
```python
    if health_task:
        health_task.cancel()
        try:
            await health_task
        except asyncio.CancelledError:
            pass
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_config.py tests/test_subagent_tools.py -v --tb=short 2>&1 | tail -15
```

Expected: All pass.

- [ ] **Step 6: Run full test suite**

```bash
pytest tests/ -q --tb=line --ignore=tests/test_middleware_bridge.py --ignore=tests/test_middleware_full.py 2>&1 | tail -5
```

Expected: Same 6 pre-existing failures, no new failures.

- [ ] **Step 7: Commit**

```bash
git add src/agent.py src/main.py src/config.py config.yaml
git commit -m "feat: wire SubAgentRegistry, HealthMonitor, and orchestration tools"
```

---

### Task 9: Final verification and tag

- [ ] **Step 1: Run full test suite**

```bash
pytest tests/ -v --tb=short --ignore=tests/test_middleware_bridge.py --ignore=tests/test_middleware_full.py 2>&1 | tail -20
```

Expected: All pass (except 6 pre-existing failures).

- [ ] **Step 2: Verify all modules import**

```bash
python3 -c "
from src.subagent.state import SubAgentState, AgentInfo
print('State OK')
from src.subagent.store import AgentStore
print('Store OK')
from src.subagent.registry import SubAgentRegistry
print('Registry OK')
from src.subagent.context_recovery import build_recovery_context
print('ContextRecovery OK')
from src.subagent.health import HealthMonitor, FailureReason
print('Health OK')
from src.subagent.recovery import RecoveryChain, RecoveryAction, next_tier
print('Recovery OK')
from src.subagent.tools import spawn_agent, recall_agent, monitor_agents, assign_task, switch_agent_model, review_cost
print('Tools OK (6 orchestration tools)')
print('All Phase 1C modules verified!')
"
```

- [ ] **Step 3: Commit and tag**

```bash
git add -A
git commit --allow-empty -m "chore: Phase 1C complete — sub-agent system"
git tag v0.3.0-phase1c
git push origin feature/implementation-plans --tags
```

---

## Exit Criteria

- [ ] `SubAgentState` enum with 6 states (SPAWNING/READY/RUNNING/BLOCKED/FINISHED/FAILED)
- [ ] `AgentInfo` dataclass with all fields from spec
- [ ] `AgentStore` namespace helpers (config, heartbeat, progress, result, directive, inbox)
- [ ] `SubAgentRegistry` tracks agents + asyncio.Tasks
- [ ] `build_recovery_context()` role-scoped recovery prompt (GAP-1)
- [ ] `HealthMonitor` with 3-layer detection (heartbeat, timeout, iteration)
- [ ] `FailureReason` enum (STALE_HEARTBEAT, TASK_TIMEOUT, ITERATION_LIMIT)
- [ ] `RecoveryChain` with RETRY → ESCALATE → REASSIGN → ABORT decision logic
- [ ] `next_tier()` helper for tier escalation
- [ ] 6 orchestration tools: spawn_agent, recall_agent, monitor_agents, assign_task, switch_agent_model, review_cost
- [ ] `init_orchestration_tools()` wires registry/spawner/cost_tracker to tools
- [ ] SubAgentConfig added to config.py
- [ ] subagent section in config.yaml
- [ ] Orchestration tools included in agent's tool list
- [ ] HealthMonitor background task started in main.py
- [ ] All new tests pass + existing tests unchanged
- [ ] Tagged as v0.3.0-phase1c

## What's deferred to Phase 2A

- **Actual DeepAgents-based spawner** — current `init_orchestration_tools(spawner=None)` uses a placeholder. Phase 2A wires a real spawner that creates a child DeepAgents instance per sub-agent.
- **Recovery execution** — RecoveryChain decides actions but doesn't execute them. Phase 2A adds a RecoveryExecutor that actually retries/escalates/reassigns.
- **StreamEvent broadcasting for agent lifecycle** — agent_spawn/progress/complete/failed events via EventHub. Requires spawner integration.
- **Budget enforcement** — CostTracker integration with automatic tier downgrade when over budget.
- **Git worktree isolation** — per-agent git worktree creation/merge/cleanup.
- **Dead agent task rebalancing (GAP-4)** — reassign dead agent's pending work to other compatible agents.
- **Team templates and harness phases** — multi-agent coordination patterns.
