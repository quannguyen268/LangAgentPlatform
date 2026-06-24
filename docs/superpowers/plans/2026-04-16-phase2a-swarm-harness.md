# Phase 2A: Swarm & Harness — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the sub-agent skeleton from Phase 1C actually functional — wire a real DeepAgents-based spawner, execute the recovery chain, broadcast lifecycle events over the WebSocket EventHub, enforce cost budgets, isolate agents in git worktrees, detect merge conflicts, launch teams from TOML templates, and gate phase transitions.

**Architecture:** A `DeepAgentsSpawner` adapter produces one compiled DeepAgents agent per sub-agent and wraps its `ainvoke()` loop in an asyncio.Task that writes heartbeats + progress + results to BaseStore. A `RecoveryExecutor` polls `HealthMonitor.check_all()`, asks `RecoveryChain.decide_action()` for each failure, and actually performs the retry/escalate/reassign/abort. A `Swarm` coordinator launches teams from TOML templates and runs them through a phased state machine (`discuss → plan → execute → verify → ship`) with pluggable `PhaseGate`s. A `WorktreeManager` gives code agents isolated git branches and detects overlapping hunks before `recall_agent` merges them back.

**Tech Stack:** Python 3.11+, DeepAgents (`create_deep_agent`), LangGraph (AsyncSqliteSaver), asyncio, subprocess (git), tomllib (Python 3.11+ stdlib), Pydantic v2 for template schemas

**Spec Reference:** `docs/superpowers/specs/2026-04-15-langagent-platform-design.md` — Section 8 (Sub-Agent System), Section 8.5 (Budget Enforcement), Section 8.6 (Git Worktree), GAPs 3, 4, 5, 6

**Prerequisites:** Phase 1C complete (722 tests pass). Depends on `src.subagent` public API (SubAgentRegistry, AgentInfo, RecoveryChain, HealthMonitor, build_recovery_context), `src.observability.cost.CostTracker`, `src.api.websocket.EventHub`, `src.core.streaming` factory functions (agent_spawn_event, agent_progress_event, agent_complete_event, agent_failed_event — the last four already exist in `EventType` but have no factory functions yet; Task 3 adds them).

---

## File Structure

### New files

```
src/subagent/spawner.py             # DeepAgentsSpawner — real sub-agent runtime
src/subagent/broadcaster.py         # EventBroadcaster — StreamEvent fan-out helper
src/subagent/budget.py              # BudgetEnforcer — per-agent/session budget checks + downgrade
src/subagent/worktree.py            # WorktreeManager — per-agent git worktree lifecycle
src/subagent/conflicts.py           # ConflictDetector — line-level diff overlap (GAP-6)
src/subagent/recovery_executor.py   # RecoveryExecutor — run RecoveryChain decisions
src/subagent/rebalance.py           # TaskRebalancer — dead-agent task redistribution (GAP-4)

src/swarm/__init__.py               # Package init with public API re-exports
src/swarm/templates.py              # TOML team template loader (Pydantic schemas)
src/swarm/phases.py                 # PhaseGate ABC + ArtifactRequiredGate, AllTasksCompleteGate, HumanApprovalGate
src/swarm/harness.py                # HarnessRunner — phase state machine
src/swarm/coordinator.py            # Swarm — top-level team launch orchestrator

templates/software-dev.toml         # Example team template
templates/research.toml              # Example team template

tests/test_spawner.py
tests/test_broadcaster.py
tests/test_budget.py
tests/test_worktree.py
tests/test_conflicts.py
tests/test_recovery_executor.py
tests/test_rebalance.py
tests/test_swarm_templates.py
tests/test_swarm_phases.py
tests/test_swarm_harness.py
tests/test_swarm_coordinator.py
```

### Modified files

```
src/core/streaming.py               # Add 4 factory functions (agent_spawn_event, etc.)
src/subagent/__init__.py            # Export new types (DeepAgentsSpawner, RecoveryExecutor, ...)
src/observability/cost.py           # Add budget-check methods (session_over_budget, agent_over_budget)
src/subagent/tools.py               # Pass recovery-context string into spawner (respawn path)
src/config.py                       # Add SwarmConfig, extend CostConfig with budget fields
src/agent.py                        # Wire DeepAgentsSpawner into init_orchestration_tools
src/main.py                         # Start RecoveryExecutor background task
config.yaml                         # Swarm and budget defaults
```

---

### Task 1: Add StreamEvent factory functions for agent lifecycle

**Files:**
- Modify: `src/core/streaming.py`
- Create: `tests/test_streaming_agent_events.py`

`EventType.AGENT_SPAWN`, `AGENT_PROGRESS`, `AGENT_COMPLETE`, `AGENT_FAILED` already exist but have no factory helpers. Other lifecycle events (`token`, `tool_call_start`, `cost_update`, etc.) do. Add the four missing factories to keep the module's API consistent.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_streaming_agent_events.py
"""Test StreamEvent factory helpers for agent lifecycle events."""
from src.core.streaming import (
    agent_spawn_event,
    agent_progress_event,
    agent_complete_event,
    agent_failed_event,
    EventType,
)


def test_agent_spawn_event_shape():
    ev = agent_spawn_event(agent_id="agent-abc", name="researcher", role="executor", tier="standard")
    assert ev.type == EventType.AGENT_SPAWN
    assert ev.data["name"] == "researcher"
    assert ev.data["role"] == "executor"
    assert ev.data["tier"] == "standard"
    assert ev.agent_id == "agent-abc"


def test_agent_progress_event_shape():
    ev = agent_progress_event(agent_id="agent-abc", message="Step 2/5", cost_cents=1.5)
    assert ev.type == EventType.AGENT_PROGRESS
    assert ev.data["message"] == "Step 2/5"
    assert ev.data["cost_cents"] == 1.5


def test_agent_complete_event_shape():
    ev = agent_complete_event(agent_id="agent-abc", result="Done!", cost_total_cents=5.0)
    assert ev.type == EventType.AGENT_COMPLETE
    assert ev.data["result"] == "Done!"
    assert ev.data["cost_total_cents"] == 5.0


def test_agent_failed_event_shape():
    ev = agent_failed_event(agent_id="agent-abc", reason="stale_heartbeat", action="retry")
    assert ev.type == EventType.AGENT_FAILED
    assert ev.data["reason"] == "stale_heartbeat"
    assert ev.data["action"] == "retry"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_streaming_agent_events.py -v
```

Expected: FAIL — `ImportError: cannot import name 'agent_spawn_event' from 'src.core.streaming'`

- [ ] **Step 3: Add the 4 factory functions to `src/core/streaming.py`**

Append to the end of the file (after `done_event`):

```python
def agent_spawn_event(
    agent_id: str, name: str, role: str, tier: str,
    user_id: str = "",
) -> StreamEvent:
    return StreamEvent(
        type=EventType.AGENT_SPAWN,
        data={"name": name, "role": role, "tier": tier},
        agent_id=agent_id,
        user_id=user_id,
    )


def agent_progress_event(
    agent_id: str, message: str, cost_cents: float = 0.0,
    user_id: str = "",
) -> StreamEvent:
    return StreamEvent(
        type=EventType.AGENT_PROGRESS,
        data={"message": message, "cost_cents": cost_cents},
        agent_id=agent_id,
        user_id=user_id,
    )


def agent_complete_event(
    agent_id: str, result: str, cost_total_cents: float = 0.0,
    user_id: str = "",
) -> StreamEvent:
    return StreamEvent(
        type=EventType.AGENT_COMPLETE,
        data={"result": result, "cost_total_cents": cost_total_cents},
        agent_id=agent_id,
        user_id=user_id,
    )


def agent_failed_event(
    agent_id: str, reason: str, action: str,
    user_id: str = "",
) -> StreamEvent:
    return StreamEvent(
        type=EventType.AGENT_FAILED,
        data={"reason": reason, "action": action},
        agent_id=agent_id,
        user_id=user_id,
    )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_streaming_agent_events.py -v
```

Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/core/streaming.py tests/test_streaming_agent_events.py
git commit -m "feat(streaming): add agent lifecycle event factories (spawn/progress/complete/failed)"
```

---

### Task 2: EventBroadcaster — wrapper that emits StreamEvents to an EventHub

**Files:**
- Create: `src/subagent/broadcaster.py`
- Create: `tests/test_broadcaster.py`

We'll use this from the spawner, recovery executor, and conflict detector. Keeps event-emission logic in one place. The `EventHub` from `src/api/websocket.py` has a synchronous `broadcast(event)` method — see `src/api/websocket.py` if you need to confirm the signature.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_broadcaster.py
"""Test EventBroadcaster helper around EventHub."""
import pytest
from src.api.websocket import EventHub
from src.subagent.broadcaster import EventBroadcaster


@pytest.mark.asyncio
async def test_broadcaster_spawn_emits_event():
    hub = EventHub()
    b = EventBroadcaster(hub)
    received = []

    async def sub():
        async for ev in hub.subscribe():
            received.append(ev)
            break

    import asyncio
    t = asyncio.create_task(sub())
    await asyncio.sleep(0.05)

    b.agent_spawned(agent_id="a1", name="n1", role="executor", tier="standard")
    await asyncio.wait_for(t, timeout=2.0)

    assert len(received) == 1
    assert received[0].type == "agent_spawn"
    assert received[0].data["name"] == "n1"


def test_broadcaster_handles_none_hub():
    """If hub is None, methods should be no-ops, not raise."""
    b = EventBroadcaster(None)
    # Any of these would fail if the hub was required
    b.agent_spawned("a1", "n1", "executor", "standard")
    b.agent_progress("a1", "working", 0.5)
    b.agent_completed("a1", "result", 1.0)
    b.agent_failed("a1", "timeout", "retry")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_broadcaster.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'src.subagent.broadcaster'`

- [ ] **Step 3: Implement broadcaster**

```python
# src/subagent/broadcaster.py
"""EventBroadcaster — thin facade over EventHub for sub-agent lifecycle events.

Every path that creates, updates, completes, or fails a sub-agent goes through
this class. Consolidating emission here keeps event shape consistent and makes
it trivial to stub in tests (pass None for the hub).
"""
from __future__ import annotations

import logging
from typing import Optional

from ..api.websocket import EventHub
from ..core.streaming import (
    agent_spawn_event,
    agent_progress_event,
    agent_complete_event,
    agent_failed_event,
)

logger = logging.getLogger(__name__)


class EventBroadcaster:
    """Emit sub-agent lifecycle events to an EventHub (or no-op if hub is None)."""

    def __init__(self, hub: Optional[EventHub]):
        self._hub = hub

    def _emit(self, event) -> None:
        if self._hub is None:
            return
        try:
            self._hub.broadcast(event)
        except Exception as e:
            logger.warning("EventBroadcaster: broadcast failed: %s", e)

    def agent_spawned(self, agent_id: str, name: str, role: str, tier: str, user_id: str = "") -> None:
        self._emit(agent_spawn_event(agent_id=agent_id, name=name, role=role, tier=tier, user_id=user_id))

    def agent_progress(self, agent_id: str, message: str, cost_cents: float = 0.0, user_id: str = "") -> None:
        self._emit(agent_progress_event(agent_id=agent_id, message=message, cost_cents=cost_cents, user_id=user_id))

    def agent_completed(self, agent_id: str, result: str, cost_total_cents: float = 0.0, user_id: str = "") -> None:
        self._emit(agent_complete_event(agent_id=agent_id, result=result, cost_total_cents=cost_total_cents, user_id=user_id))

    def agent_failed(self, agent_id: str, reason: str, action: str, user_id: str = "") -> None:
        self._emit(agent_failed_event(agent_id=agent_id, reason=reason, action=action, user_id=user_id))
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_broadcaster.py -v
```

Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/subagent/broadcaster.py tests/test_broadcaster.py
git commit -m "feat(subagent): add EventBroadcaster facade over EventHub"
```

---

### Task 3: BudgetEnforcer — per-agent & per-session budget checks

**Files:**
- Create: `src/subagent/budget.py`
- Create: `tests/test_budget.py`

Consumes the existing `CostTracker`. `AgentInfo.cost_cents` is the authoritative per-agent running cost (Phase 1C); `CostTracker.record(..., user_id=...)` gives per-user totals. `BudgetEnforcer.check_agent(info)` returns a decision: `OK`, `WARN`, or `OVER`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_budget.py
"""Test BudgetEnforcer — per-agent and per-session budget checks."""
from src.subagent.budget import BudgetEnforcer, BudgetDecision
from src.subagent.state import AgentInfo


def _info(cost: float) -> AgentInfo:
    i = AgentInfo(
        agent_id="a1", name="n1", role="executor", task="t",
        tier="standard", tools=[], skills=[],
    )
    i.cost_cents = cost
    return i


def test_budget_ok_under_warn_threshold():
    enforcer = BudgetEnforcer(agent_budget_cents=100.0, warn_threshold=0.8)
    assert enforcer.check_agent(_info(50.0)) == BudgetDecision.OK


def test_budget_warn_between_warn_and_hard():
    enforcer = BudgetEnforcer(agent_budget_cents=100.0, warn_threshold=0.8)
    # 80.0 is the warn threshold (0.8 * 100)
    assert enforcer.check_agent(_info(85.0)) == BudgetDecision.WARN


def test_budget_over_at_or_above_hard():
    enforcer = BudgetEnforcer(agent_budget_cents=100.0, warn_threshold=0.8)
    assert enforcer.check_agent(_info(100.0)) == BudgetDecision.OVER
    assert enforcer.check_agent(_info(200.0)) == BudgetDecision.OVER


def test_budget_disabled_returns_ok():
    """None budget means no enforcement — always OK."""
    enforcer = BudgetEnforcer(agent_budget_cents=None, warn_threshold=0.8)
    assert enforcer.check_agent(_info(9999.0)) == BudgetDecision.OK
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_budget.py -v
```

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement budget enforcer**

```python
# src/subagent/budget.py
"""BudgetEnforcer — per-agent budget checks with warn/hard thresholds."""
from __future__ import annotations

from enum import Enum
from typing import Optional

from .state import AgentInfo


class BudgetDecision(str, Enum):
    OK = "ok"          # Under warn threshold
    WARN = "warn"      # At or above warn threshold, below hard limit
    OVER = "over"      # At or above hard limit


class BudgetEnforcer:
    """Compare an agent's running cost against a hard budget + warn threshold.

    Args:
        agent_budget_cents: hard limit in cents. ``None`` disables enforcement.
        warn_threshold: fraction of the hard limit (0.0–1.0). Cost at or above
            ``agent_budget_cents * warn_threshold`` → WARN.
    """

    def __init__(
        self,
        agent_budget_cents: Optional[float],
        warn_threshold: float = 0.8,
    ):
        self._agent_budget = agent_budget_cents
        self._warn_threshold = warn_threshold

    def check_agent(self, info: AgentInfo) -> BudgetDecision:
        if self._agent_budget is None:
            return BudgetDecision.OK
        if info.cost_cents >= self._agent_budget:
            return BudgetDecision.OVER
        if info.cost_cents >= self._agent_budget * self._warn_threshold:
            return BudgetDecision.WARN
        return BudgetDecision.OK
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_budget.py -v
```

Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/subagent/budget.py tests/test_budget.py
git commit -m "feat(subagent): add BudgetEnforcer with warn/hard thresholds"
```

---

### Task 4: WorktreeManager — per-agent git worktree lifecycle

**Files:**
- Create: `src/subagent/worktree.py`
- Create: `tests/test_worktree.py`

Uses `subprocess` for git commands. Each agent gets a branch `agent/{agent_id}` and a worktree under `/tmp/langagent-worktrees/{agent_id}`. Merge on recall is best-effort — on conflict we surface the error for the conflict detector (Task 5) to report.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_worktree.py
"""Test WorktreeManager — per-agent git worktree isolation."""
import pytest
import subprocess
from pathlib import Path
from src.subagent.worktree import WorktreeManager


@pytest.fixture
def git_repo(tmp_path):
    """Create a real git repo with one initial commit."""
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("initial\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True)
    return tmp_path


def test_create_and_cleanup(git_repo, tmp_path):
    mgr = WorktreeManager(base_repo=str(git_repo), worktree_root=str(tmp_path / "wt"))
    path = mgr.create("agent-1")
    assert Path(path).exists()
    # Branch should exist
    result = subprocess.run(
        ["git", "branch", "--list", "agent/agent-1"],
        cwd=git_repo, capture_output=True, text=True,
    )
    assert "agent/agent-1" in result.stdout

    mgr.cleanup("agent-1")
    assert not Path(path).exists()


def test_list_agents(git_repo, tmp_path):
    mgr = WorktreeManager(base_repo=str(git_repo), worktree_root=str(tmp_path / "wt"))
    mgr.create("a1")
    mgr.create("a2")
    agents = mgr.list_agents()
    assert set(agents) == {"a1", "a2"}
    mgr.cleanup("a1")
    mgr.cleanup("a2")


def test_merge_clean(git_repo, tmp_path):
    mgr = WorktreeManager(base_repo=str(git_repo), worktree_root=str(tmp_path / "wt"))
    path = mgr.create("a1")
    # Make a commit in the worktree
    (Path(path) / "hello.txt").write_text("hi\n")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "add hello"], cwd=path, check=True, capture_output=True)

    merged = mgr.merge("a1")
    assert merged is True
    # File should appear in base repo
    assert (git_repo / "hello.txt").exists()
    mgr.cleanup("a1")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_worktree.py -v
```

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement WorktreeManager**

```python
# src/subagent/worktree.py
"""WorktreeManager — per-agent git worktree lifecycle.

Each sub-agent that works on code gets its own branch ``agent/{agent_id}`` and
a worktree under ``worktree_root/{agent_id}``. On ``recall_agent`` the master
asks the manager to ``merge()`` and then ``cleanup()``.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


class WorktreeManager:
    """Manage git worktrees for sub-agents."""

    def __init__(self, base_repo: str, worktree_root: str, base_branch: str = "main"):
        self._base_repo = Path(base_repo).resolve()
        self._worktree_root = Path(worktree_root).resolve()
        self._worktree_root.mkdir(parents=True, exist_ok=True)
        self._base_branch = base_branch

    def _branch(self, agent_id: str) -> str:
        return f"agent/{agent_id}"

    def _path(self, agent_id: str) -> Path:
        return self._worktree_root / agent_id

    def create(self, agent_id: str) -> str:
        """Create a worktree with a fresh branch off base_branch. Returns the path."""
        path = self._path(agent_id)
        if path.exists():
            logger.warning("Worktree for %s already exists at %s", agent_id, path)
            return str(path)
        branch = self._branch(agent_id)
        subprocess.run(
            ["git", "worktree", "add", "-b", branch, str(path), self._base_branch],
            cwd=self._base_repo, check=True, capture_output=True,
        )
        logger.info("Created worktree %s on branch %s", path, branch)
        return str(path)

    def merge(self, agent_id: str) -> bool:
        """Merge the agent's branch back into base_branch.

        Returns True on clean merge, False if git reports conflicts. The caller
        (typically recall_agent) can then inspect the base repo state or invoke
        ConflictDetector for diagnostics.
        """
        branch = self._branch(agent_id)
        try:
            subprocess.run(
                ["git", "merge", "--no-edit", branch],
                cwd=self._base_repo, check=True, capture_output=True,
            )
            logger.info("Merged %s into %s", branch, self._base_branch)
            return True
        except subprocess.CalledProcessError as e:
            logger.warning("Merge of %s failed: %s", branch, e.stderr.decode("utf-8", "replace"))
            # Abort so the base repo is left clean
            subprocess.run(["git", "merge", "--abort"], cwd=self._base_repo, capture_output=True)
            return False

    def cleanup(self, agent_id: str) -> None:
        """Remove the worktree and delete the branch."""
        path = self._path(agent_id)
        branch = self._branch(agent_id)
        if path.exists():
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(path)],
                cwd=self._base_repo, capture_output=True,
            )
            # Belt-and-suspenders: remove dir if git didn't
            if path.exists():
                shutil.rmtree(path, ignore_errors=True)
        # Delete the branch (may fail if branch is current — that's OK)
        subprocess.run(
            ["git", "branch", "-D", branch],
            cwd=self._base_repo, capture_output=True,
        )
        logger.info("Cleaned up worktree for %s", agent_id)

    def list_agents(self) -> list[str]:
        """List agent_ids with active worktrees."""
        if not self._worktree_root.exists():
            return []
        return [p.name for p in self._worktree_root.iterdir() if p.is_dir()]

    def path_for(self, agent_id: str) -> str | None:
        """Return the worktree path for an agent, or None if no worktree."""
        path = self._path(agent_id)
        return str(path) if path.exists() else None
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_worktree.py -v
```

Expected: PASS (3 tests). If git is not on PATH the tests will error — that's acceptable (git is a hard requirement for this module).

- [ ] **Step 5: Commit**

```bash
git add src/subagent/worktree.py tests/test_worktree.py
git commit -m "feat(subagent): add WorktreeManager for per-agent git isolation"
```

---

### Task 5: ConflictDetector — line-level diff overlap (GAP-6)

**Files:**
- Create: `src/subagent/conflicts.py`
- Create: `tests/test_conflicts.py`

Uses `git diff --name-only` + `git diff -U0` to find file-level then line-level overlaps between worktrees. Returns a list of `Conflict(file, agent_a, agent_b, severity)` where severity is `"high"` (same lines) or `"medium"` (same file, different lines).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_conflicts.py
"""Test ConflictDetector — overlap between agent worktrees."""
import pytest
import subprocess
from pathlib import Path
from src.subagent.conflicts import ConflictDetector, Conflict
from src.subagent.worktree import WorktreeManager


@pytest.fixture
def git_repo(tmp_path):
    """Create a real git repo with a multi-line file."""
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    (tmp_path / "file.py").write_text("line1\nline2\nline3\nline4\nline5\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True)
    return tmp_path


def test_no_overlap_when_disjoint(git_repo, tmp_path):
    mgr = WorktreeManager(base_repo=str(git_repo), worktree_root=str(tmp_path / "wt"))
    p_a = Path(mgr.create("a"))
    p_b = Path(mgr.create("b"))
    # a edits file.py line 1, b edits unrelated.py
    (p_a / "file.py").write_text("LINE1_NEW\nline2\nline3\nline4\nline5\n")
    (p_b / "unrelated.py").write_text("different file\n")
    for p in (p_a, p_b):
        subprocess.run(["git", "add", "."], cwd=p, check=True)
        subprocess.run(["git", "commit", "-m", "edit"], cwd=p, check=True, capture_output=True)

    detector = ConflictDetector(base_repo=str(git_repo), base_branch="main")
    conflicts = detector.detect({"a": str(p_a), "b": str(p_b)})
    assert conflicts == []


def test_same_file_different_lines_is_medium(git_repo, tmp_path):
    mgr = WorktreeManager(base_repo=str(git_repo), worktree_root=str(tmp_path / "wt"))
    p_a = Path(mgr.create("a"))
    p_b = Path(mgr.create("b"))
    # a edits line 1, b edits line 5 — same file, different hunks
    (p_a / "file.py").write_text("LINE1_NEW\nline2\nline3\nline4\nline5\n")
    (p_b / "file.py").write_text("line1\nline2\nline3\nline4\nLINE5_NEW\n")
    for p in (p_a, p_b):
        subprocess.run(["git", "add", "."], cwd=p, check=True)
        subprocess.run(["git", "commit", "-m", "edit"], cwd=p, check=True, capture_output=True)

    detector = ConflictDetector(base_repo=str(git_repo), base_branch="main")
    conflicts = detector.detect({"a": str(p_a), "b": str(p_b)})
    assert len(conflicts) == 1
    assert conflicts[0].file == "file.py"
    assert conflicts[0].severity == "medium"
    assert {conflicts[0].agent_a, conflicts[0].agent_b} == {"a", "b"}


def test_same_lines_is_high(git_repo, tmp_path):
    mgr = WorktreeManager(base_repo=str(git_repo), worktree_root=str(tmp_path / "wt"))
    p_a = Path(mgr.create("a"))
    p_b = Path(mgr.create("b"))
    # both edit line 3
    (p_a / "file.py").write_text("line1\nline2\nA_EDIT\nline4\nline5\n")
    (p_b / "file.py").write_text("line1\nline2\nB_EDIT\nline4\nline5\n")
    for p in (p_a, p_b):
        subprocess.run(["git", "add", "."], cwd=p, check=True)
        subprocess.run(["git", "commit", "-m", "edit"], cwd=p, check=True, capture_output=True)

    detector = ConflictDetector(base_repo=str(git_repo), base_branch="main")
    conflicts = detector.detect({"a": str(p_a), "b": str(p_b)})
    assert len(conflicts) == 1
    assert conflicts[0].severity == "high"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_conflicts.py -v
```

Expected: FAIL

- [ ] **Step 3: Implement ConflictDetector**

```python
# src/subagent/conflicts.py
"""ConflictDetector — detect overlapping changes across agent worktrees (GAP-6).

Runs ``git diff`` for each worktree against the base branch, then compares the
changed-line ranges pairwise:
  - same lines modified by both agents → severity="high"
  - same file modified by both but disjoint hunks → severity="medium"
"""
from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass
from itertools import combinations

logger = logging.getLogger(__name__)

# Matches "@@ -L,S +L,S @@" hunk headers
_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


@dataclass
class Conflict:
    file: str
    agent_a: str
    agent_b: str
    severity: str  # "high" | "medium"


def _changed_files(worktree: str, base_branch: str) -> set[str]:
    """Return the set of files changed in worktree vs base_branch."""
    result = subprocess.run(
        ["git", "diff", "--name-only", base_branch, "HEAD"],
        cwd=worktree, capture_output=True, text=True, check=False,
    )
    return {f.strip() for f in result.stdout.splitlines() if f.strip()}


def _changed_line_ranges(worktree: str, base_branch: str, file: str) -> list[tuple[int, int]]:
    """Return list of (start_line, line_count) tuples for changed regions in file."""
    result = subprocess.run(
        ["git", "diff", "-U0", base_branch, "HEAD", "--", file],
        cwd=worktree, capture_output=True, text=True, check=False,
    )
    ranges: list[tuple[int, int]] = []
    for line in result.stdout.splitlines():
        m = _HUNK_RE.match(line)
        if not m:
            continue
        start = int(m.group(1))
        count = int(m.group(2)) if m.group(2) else 1
        ranges.append((start, count))
    return ranges


def _ranges_overlap(a: list[tuple[int, int]], b: list[tuple[int, int]]) -> bool:
    for (a_start, a_count) in a:
        a_end = a_start + a_count - 1
        for (b_start, b_count) in b:
            b_end = b_start + b_count - 1
            if not (a_end < b_start or b_end < a_start):
                return True
    return False


class ConflictDetector:
    """Pairwise comparison of git diffs across agent worktrees."""

    def __init__(self, base_repo: str, base_branch: str = "main"):
        self._base_repo = base_repo
        self._base_branch = base_branch

    def detect(self, worktrees: dict[str, str]) -> list[Conflict]:
        """Analyze pairwise conflicts across worktrees.

        Args:
            worktrees: mapping of agent_id → worktree path

        Returns:
            List of Conflict records. Empty list means no overlaps.
        """
        # Collect changed files per agent
        files_by_agent: dict[str, set[str]] = {
            aid: _changed_files(path, self._base_branch) for aid, path in worktrees.items()
        }

        conflicts: list[Conflict] = []
        for (agent_a, files_a), (agent_b, files_b) in combinations(files_by_agent.items(), 2):
            overlap_files = files_a & files_b
            for f in overlap_files:
                ranges_a = _changed_line_ranges(worktrees[agent_a], self._base_branch, f)
                ranges_b = _changed_line_ranges(worktrees[agent_b], self._base_branch, f)
                severity = "high" if _ranges_overlap(ranges_a, ranges_b) else "medium"
                conflicts.append(Conflict(file=f, agent_a=agent_a, agent_b=agent_b, severity=severity))
        return conflicts
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_conflicts.py -v
```

Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/subagent/conflicts.py tests/test_conflicts.py
git commit -m "feat(subagent): add ConflictDetector for pairwise worktree overlap (GAP-6)"
```

---

### Task 6: DeepAgentsSpawner — real sub-agent runtime

**Files:**
- Create: `src/subagent/spawner.py`
- Create: `tests/test_spawner.py`

This is the heart of Phase 2A: swap the `None` spawner placeholder for an adapter that actually runs a DeepAgents sub-agent as an `asyncio.Task`, writing heartbeats + progress + result to `AgentStore` and emitting `StreamEvent`s to the broadcaster.

The spawner returns an `asyncio.Task` (matching the signature `init_orchestration_tools(spawner=...)` expects — `async (info: AgentInfo) -> asyncio.Task`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_spawner.py
"""Test DeepAgentsSpawner — wires create_deep_agent into the sub-agent runtime."""
import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock
from langgraph.store.memory import InMemoryStore
from langchain_core.messages import AIMessage

from src.api.websocket import EventHub
from src.subagent.broadcaster import EventBroadcaster
from src.subagent.registry import SubAgentRegistry
from src.subagent.spawner import DeepAgentsSpawner
from src.subagent.state import AgentInfo, SubAgentState


@pytest.mark.asyncio
async def test_spawner_writes_heartbeat_and_result(monkeypatch):
    """Spawner runs the inner agent and writes heartbeat + result to the store."""
    store = InMemoryStore()
    registry = SubAgentRegistry(store)
    hub = EventHub()
    broadcaster = EventBroadcaster(hub)

    # Patch create_deep_agent to return a mock whose ainvoke produces a single message
    inner = MagicMock()
    inner.ainvoke = AsyncMock(return_value={
        "messages": [AIMessage(content="done")],
    })
    monkeypatch.setattr("src.subagent.spawner.create_deep_agent", lambda **kwargs: inner)

    spawner = DeepAgentsSpawner(
        registry=registry,
        broadcaster=broadcaster,
        base_model=MagicMock(),
        tools_by_name={},
    )

    info = AgentInfo(
        agent_id="a1", name="n1", role="executor", task="do stuff",
        tier="standard", tools=[], skills=[],
    )
    registry.register(info, asyncio.create_task(asyncio.sleep(0)))  # placeholder; will be replaced

    task = await spawner.spawn(info)
    registry._tasks["a1"] = task  # connect to registry
    await asyncio.wait_for(task, timeout=5.0)

    # Heartbeat was written
    hb = await registry.agent_store.read_heartbeat("a1")
    assert hb is not None
    # Result was written
    result = await registry.agent_store.read_result("a1")
    assert result is not None
    assert result["status"] == "success"
    # Final state should be FINISHED
    assert registry.get_agent("a1").state == SubAgentState.FINISHED


@pytest.mark.asyncio
async def test_spawner_emits_spawn_and_complete(monkeypatch):
    """Spawner emits agent_spawn and agent_complete events via broadcaster."""
    store = InMemoryStore()
    registry = SubAgentRegistry(store)
    hub = EventHub()
    broadcaster = EventBroadcaster(hub)

    events = []

    async def sub():
        async for ev in hub.subscribe():
            events.append(ev)
            if ev.type == "agent_complete":
                break

    sub_task = asyncio.create_task(sub())
    await asyncio.sleep(0.05)

    inner = MagicMock()
    inner.ainvoke = AsyncMock(return_value={"messages": [AIMessage(content="ok")]})
    monkeypatch.setattr("src.subagent.spawner.create_deep_agent", lambda **kwargs: inner)

    spawner = DeepAgentsSpawner(
        registry=registry,
        broadcaster=broadcaster,
        base_model=MagicMock(),
        tools_by_name={},
    )
    info = AgentInfo(
        agent_id="a1", name="n1", role="executor", task="t",
        tier="standard", tools=[], skills=[],
    )
    registry.register(info, asyncio.create_task(asyncio.sleep(0)))
    task = await spawner.spawn(info)
    registry._tasks["a1"] = task
    await asyncio.wait_for(task, timeout=5.0)
    await asyncio.wait_for(sub_task, timeout=2.0)

    types = [e.type for e in events]
    assert "agent_spawn" in types
    assert "agent_complete" in types


@pytest.mark.asyncio
async def test_spawner_handles_inner_failure(monkeypatch):
    """If the inner agent raises, state becomes FAILED and an error is recorded."""
    store = InMemoryStore()
    registry = SubAgentRegistry(store)
    broadcaster = EventBroadcaster(None)

    inner = MagicMock()
    inner.ainvoke = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr("src.subagent.spawner.create_deep_agent", lambda **kwargs: inner)

    spawner = DeepAgentsSpawner(
        registry=registry, broadcaster=broadcaster,
        base_model=MagicMock(), tools_by_name={},
    )
    info = AgentInfo(
        agent_id="a1", name="n1", role="executor", task="t",
        tier="standard", tools=[], skills=[],
    )
    registry.register(info, asyncio.create_task(asyncio.sleep(0)))
    task = await spawner.spawn(info)
    registry._tasks["a1"] = task
    await asyncio.wait_for(task, timeout=5.0)

    assert registry.get_agent("a1").state == SubAgentState.FAILED
    assert "boom" in (registry.get_agent("a1").error or "")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_spawner.py -v
```

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement DeepAgentsSpawner**

```python
# src/subagent/spawner.py
"""DeepAgentsSpawner — create and run a real sub-agent as an asyncio.Task.

For each ``AgentInfo`` passed to ``spawn()``, the spawner:
  1. Builds a DeepAgents instance with that agent's tool subset.
  2. Writes an initial heartbeat and emits ``agent_spawn``.
  3. Invokes the agent with ``info.task`` (optionally augmented by recovery context).
  4. Writes progress + final result to AgentStore and emits ``agent_complete`` /
     ``agent_failed`` to the broadcaster.
  5. Updates SubAgentRegistry state transitions (SPAWNING → RUNNING → FINISHED / FAILED).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from deepagents import create_deep_agent
from langchain_core.messages import AIMessage, HumanMessage

from .broadcaster import EventBroadcaster
from .registry import SubAgentRegistry
from .state import AgentInfo, SubAgentState

logger = logging.getLogger(__name__)


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
    ):
        self._registry = registry
        self._broadcaster = broadcaster
        self._base_model = base_model
        self._tools_by_name = tools_by_name

    async def spawn(self, info: AgentInfo, recovery_context: Optional[str] = None) -> asyncio.Task:
        """Create the asyncio.Task that runs this sub-agent."""
        task = asyncio.create_task(self._run(info, recovery_context))
        return task

    async def _run(self, info: AgentInfo, recovery_context: Optional[str]) -> None:
        agent_id = info.agent_id
        store = self._registry.agent_store

        try:
            # Resolve tools
            tools = [self._tools_by_name[n] for n in info.tools if n in self._tools_by_name]

            # Emit spawn + heartbeat
            self._broadcaster.agent_spawned(
                agent_id=agent_id, name=info.name, role=info.role, tier=info.tier,
            )
            await store.write_heartbeat(agent_id, iteration=0, status="starting")

            # Build inner agent (Phase 2A: no nested middleware; keep it simple)
            inner = create_deep_agent(
                model=self._base_model,
                tools=tools,
            )

            self._registry.update_state(agent_id, SubAgentState.RUNNING)

            # Compose initial message — prepend recovery context if this is a respawn
            task_text = info.task
            if recovery_context:
                task_text = f"{recovery_context}\n\n---\n\nTask: {info.task}"
            state = {"messages": [HumanMessage(content=task_text)]}

            await store.write_heartbeat(agent_id, iteration=1, status="running")
            result = await inner.ainvoke(state)

            # Extract output
            output = _extract_last_text(result.get("messages", []))
            await store.write_result(
                agent_id, status="success", output=output, cost_total=info.cost_cents,
            )
            info.result = output
            info.finished_at = asyncio.get_running_loop().time()
            self._registry.update_state(agent_id, SubAgentState.FINISHED)
            self._broadcaster.agent_completed(
                agent_id=agent_id, result=output, cost_total_cents=info.cost_cents,
            )
            logger.info("Sub-agent %s completed", agent_id)

        except asyncio.CancelledError:
            logger.info("Sub-agent %s cancelled", agent_id)
            raise
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            info.error = err
            self._registry.update_state(agent_id, SubAgentState.FAILED)
            try:
                await store.write_result(
                    agent_id, status="failed", output=err, cost_total=info.cost_cents,
                )
            except Exception:
                pass
            self._broadcaster.agent_failed(agent_id=agent_id, reason="exception", action="pending")
            logger.exception("Sub-agent %s failed", agent_id)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_spawner.py -v
```

Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/subagent/spawner.py tests/test_spawner.py
git commit -m "feat(subagent): add DeepAgentsSpawner — real sub-agent runtime"
```

---

### Task 7: RecoveryExecutor — actually run RecoveryChain decisions

**Files:**
- Create: `src/subagent/recovery_executor.py`
- Create: `tests/test_recovery_executor.py`

Phase 1C's `RecoveryChain` only decides (returns `RecoveryAction`). This task executes the decision: for `RETRY` / `ESCALATE` / `REASSIGN`, respawn with a fresh asyncio.Task via the spawner; for `ABORT`, deregister and notify.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_recovery_executor.py
"""Test RecoveryExecutor — actually perform retry/escalate/reassign/abort."""
import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock
from langgraph.store.memory import InMemoryStore

from src.subagent.broadcaster import EventBroadcaster
from src.subagent.recovery import RecoveryChain, RecoveryAction
from src.subagent.recovery_executor import RecoveryExecutor
from src.subagent.registry import SubAgentRegistry
from src.subagent.state import AgentInfo, SubAgentState


def _spawner_stub():
    """A spawn() that immediately returns a finished task."""
    async def spawn(info, recovery_context=None):
        async def noop():
            return
        return asyncio.create_task(noop())
    m = MagicMock()
    m.spawn = AsyncMock(side_effect=spawn)
    return m


@pytest.mark.asyncio
async def test_recovery_retry_increments_retry_count():
    store = InMemoryStore()
    registry = SubAgentRegistry(store)
    spawner = _spawner_stub()
    executor = RecoveryExecutor(
        registry=registry,
        chain=RecoveryChain(max_retries=1),
        spawner=spawner,
        broadcaster=EventBroadcaster(None),
    )

    async def placeholder():
        await asyncio.sleep(0.01)

    t = asyncio.create_task(placeholder())
    info = AgentInfo(
        agent_id="a1", name="n1", role="executor", task="t",
        tier="standard", tools=[], skills=[],
    )
    info.retry_count = 0
    registry.register(info, t)

    await executor.handle_failure("a1", reason="stale_heartbeat")
    assert registry.get_agent("a1").retry_count == 1
    spawner.spawn.assert_awaited()


@pytest.mark.asyncio
async def test_recovery_escalate_bumps_tier():
    store = InMemoryStore()
    registry = SubAgentRegistry(store)
    spawner = _spawner_stub()
    executor = RecoveryExecutor(
        registry=registry,
        chain=RecoveryChain(max_retries=1),
        spawner=spawner,
        broadcaster=EventBroadcaster(None),
    )

    async def placeholder():
        await asyncio.sleep(0.01)

    t = asyncio.create_task(placeholder())
    info = AgentInfo(
        agent_id="a1", name="n1", role="executor", task="t",
        tier="standard", tools=[], skills=[],
    )
    info.retry_count = 1  # → ESCALATE per RecoveryChain logic
    registry.register(info, t)

    await executor.handle_failure("a1", reason="iteration_limit")
    assert registry.get_agent("a1").tier == "advanced"


@pytest.mark.asyncio
async def test_recovery_abort_removes_agent():
    store = InMemoryStore()
    registry = SubAgentRegistry(store)
    spawner = _spawner_stub()
    executor = RecoveryExecutor(
        registry=registry,
        chain=RecoveryChain(max_retries=1),
        spawner=spawner,
        broadcaster=EventBroadcaster(None),
    )

    async def placeholder():
        await asyncio.sleep(0.01)

    t = asyncio.create_task(placeholder())
    info = AgentInfo(
        agent_id="a1", name="n1", role="executor", task="t",
        tier="expert", tools=[], skills=[],
    )
    info.retry_count = 10  # → ABORT
    registry.register(info, t)

    await executor.handle_failure("a1", reason="task_timeout")
    assert registry.get_agent("a1") is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_recovery_executor.py -v
```

Expected: FAIL

- [ ] **Step 3: Implement RecoveryExecutor**

```python
# src/subagent/recovery_executor.py
"""RecoveryExecutor — carry out RecoveryChain decisions.

Bridges the gap between ``RecoveryChain.decide_action()`` (pure decision logic)
and actually performing the retry / escalate / reassign / abort.
"""
from __future__ import annotations

import logging

from .broadcaster import EventBroadcaster
from .context_recovery import build_recovery_context
from .recovery import RecoveryAction, RecoveryChain, next_tier
from .registry import SubAgentRegistry
from .state import AgentInfo, SubAgentState

logger = logging.getLogger(__name__)


class RecoveryExecutor:
    """Execute recovery actions decided by RecoveryChain."""

    def __init__(
        self,
        registry: SubAgentRegistry,
        chain: RecoveryChain,
        spawner,
        broadcaster: EventBroadcaster,
    ):
        self._registry = registry
        self._chain = chain
        self._spawner = spawner
        self._broadcaster = broadcaster

    async def handle_failure(self, agent_id: str, reason: str) -> None:
        """Decide + perform recovery for a failed agent."""
        info = self._registry.get_agent(agent_id)
        if info is None:
            return
        action = self._chain.decide_action(info)
        logger.info("Recovery: agent=%s reason=%s → %s", agent_id, reason, action.value)
        self._broadcaster.agent_failed(agent_id=agent_id, reason=reason, action=action.value)

        if action == RecoveryAction.RETRY:
            await self._respawn(info, recovery=True)
        elif action == RecoveryAction.ESCALATE:
            higher = next_tier(info.tier)
            if higher:
                info.tier = higher
            await self._respawn(info, recovery=True)
        elif action == RecoveryAction.REASSIGN:
            # Phase 2A treats REASSIGN like RETRY with role annotation. Phase 2B
            # will introduce actual cross-role reassignment via team templates.
            await self._respawn(info, recovery=True)
        elif action == RecoveryAction.ABORT:
            await self._abort(info)

    async def _respawn(self, info: AgentInfo, *, recovery: bool) -> None:
        """Cancel the old task, build a recovery context, and spawn a new one."""
        # Cancel the old task without fully deregistering — keep AgentInfo around
        old_task = self._registry.get_task(info.agent_id)
        if old_task and not old_task.done():
            old_task.cancel()

        info.retry_count += 1
        info.state = SubAgentState.SPAWNING
        info.error = None

        context = None
        if recovery:
            context = await build_recovery_context(
                agent_id=info.agent_id,
                role=info.role,
                store=self._registry._store,
            )

        new_task = await self._spawner.spawn(info, recovery_context=context)
        self._registry._tasks[info.agent_id] = new_task

    async def _abort(self, info: AgentInfo) -> None:
        info.state = SubAgentState.FAILED
        await self._registry.deregister(info.agent_id)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_recovery_executor.py -v
```

Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/subagent/recovery_executor.py tests/test_recovery_executor.py
git commit -m "feat(subagent): add RecoveryExecutor to run RecoveryChain decisions"
```

---

### Task 8: TaskRebalancer — dead-agent task redistribution (GAP-4)

**Files:**
- Create: `src/subagent/rebalance.py`
- Create: `tests/test_rebalance.py`

When an agent is aborted, any tasks it was actively assigned (read from the `inbox` namespace in BaseStore) should move to the highest-retry-count-available compatible agent in the same role. For Phase 2A we redistribute to any other agent with the same role; the richer matching (skills/tools intersection) is Phase 3.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_rebalance.py
"""Test TaskRebalancer — redistribute pending inbox tasks from dead agents."""
import asyncio
import pytest
from langgraph.store.memory import InMemoryStore

from src.subagent.rebalance import TaskRebalancer
from src.subagent.registry import SubAgentRegistry
from src.subagent.state import AgentInfo


@pytest.mark.asyncio
async def test_rebalances_to_same_role():
    store = InMemoryStore()
    registry = SubAgentRegistry(store)
    rebalancer = TaskRebalancer(registry)

    async def placeholder():
        await asyncio.sleep(0.01)

    # Dead executor
    t_dead = asyncio.create_task(placeholder())
    dead = AgentInfo(
        agent_id="dead", name="n", role="executor", task="t",
        tier="standard", tools=[], skills=[],
    )
    registry.register(dead, t_dead)
    await registry.agent_store.send_inbox("dead", sender="master", message="task 1")
    await registry.agent_store.send_inbox("dead", sender="master", message="task 2")

    # Live executor
    t_live = asyncio.create_task(placeholder())
    live = AgentInfo(
        agent_id="live", name="n2", role="executor", task="t",
        tier="standard", tools=[], skills=[],
    )
    registry.register(live, t_live)

    moved = await rebalancer.rebalance_from("dead")
    assert moved == 2
    # Live inbox should now have both tasks
    inbox = await registry.agent_store.drain_inbox("live")
    assert len(inbox) == 2


@pytest.mark.asyncio
async def test_no_compatible_agent_returns_zero():
    store = InMemoryStore()
    registry = SubAgentRegistry(store)
    rebalancer = TaskRebalancer(registry)

    async def placeholder():
        await asyncio.sleep(0.01)

    t = asyncio.create_task(placeholder())
    dead = AgentInfo(
        agent_id="dead", name="n", role="planner", task="t",
        tier="standard", tools=[], skills=[],
    )
    registry.register(dead, t)
    await registry.agent_store.send_inbox("dead", sender="master", message="task 1")

    moved = await rebalancer.rebalance_from("dead")
    assert moved == 0


@pytest.mark.asyncio
async def test_empty_inbox_is_noop():
    store = InMemoryStore()
    registry = SubAgentRegistry(store)
    rebalancer = TaskRebalancer(registry)

    async def placeholder():
        await asyncio.sleep(0.01)

    t = asyncio.create_task(placeholder())
    dead = AgentInfo(
        agent_id="dead", name="n", role="executor", task="t",
        tier="standard", tools=[], skills=[],
    )
    registry.register(dead, t)

    moved = await rebalancer.rebalance_from("dead")
    assert moved == 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_rebalance.py -v
```

Expected: FAIL

- [ ] **Step 3: Implement TaskRebalancer**

```python
# src/subagent/rebalance.py
"""TaskRebalancer — redistribute dead agent's inbox to compatible survivors (GAP-4).

When ``RecoveryExecutor`` aborts an agent, its pending inbox messages are not
lost — they move to another agent in the same role. Phase 2A uses role-only
matching; Phase 3 may add skills/tools overlap scoring.
"""
from __future__ import annotations

import logging

from .registry import SubAgentRegistry

logger = logging.getLogger(__name__)


class TaskRebalancer:
    """Move inbox messages from a dead agent to compatible survivors."""

    def __init__(self, registry: SubAgentRegistry):
        self._registry = registry

    async def rebalance_from(self, dead_agent_id: str) -> int:
        """Drain the dead agent's inbox and redistribute to same-role agents.

        Returns:
            Number of messages moved. Zero if no messages, no compatible
            recipient, or dead agent unknown.
        """
        dead = self._registry.get_agent(dead_agent_id)
        if dead is None:
            return 0

        # Candidate recipients: same role, not the dead agent itself
        candidates = [
            a for a in self._registry.list_agents()
            if a.role == dead.role and a.agent_id != dead_agent_id
        ]
        if not candidates:
            logger.info("No compatible agent to rebalance %s's tasks", dead_agent_id)
            return 0

        messages = await self._registry.agent_store.drain_inbox(dead_agent_id)
        if not messages:
            return 0

        # Round-robin distribute
        for idx, msg in enumerate(messages):
            recipient = candidates[idx % len(candidates)]
            await self._registry.agent_store.send_inbox(
                recipient.agent_id,
                sender=f"rebalanced-from:{dead_agent_id}",
                message=msg.get("message", ""),
            )

        logger.info(
            "Rebalanced %d tasks from %s across %d survivors",
            len(messages), dead_agent_id, len(candidates),
        )
        return len(messages)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_rebalance.py -v
```

Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/subagent/rebalance.py tests/test_rebalance.py
git commit -m "feat(subagent): add TaskRebalancer for dead-agent task redistribution (GAP-4)"
```

---

### Task 9: Swarm — team templates (TOML)

**Files:**
- Create: `src/swarm/__init__.py`
- Create: `src/swarm/templates.py`
- Create: `templates/software-dev.toml`
- Create: `templates/research.toml`
- Create: `tests/test_swarm_templates.py`

Pydantic models load `.toml` templates describing a team: goal, phases, and agents (each with name, role, tier, tools, skills, task_prompt).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_swarm_templates.py
"""Test TOML team template loader."""
import pytest
from pathlib import Path
from src.swarm.templates import TeamTemplate, load_template


def _write(path: Path, body: str) -> Path:
    path.write_text(body.strip() + "\n")
    return path


def test_parses_valid_template(tmp_path):
    t = _write(tmp_path / "t.toml", """
name = "example"
goal = "Build an API"
phases = ["plan", "execute", "verify"]

[[agents]]
name = "architect"
role = "planner"
tier = "advanced"
tools = ["read_file", "write_file"]
skills = ["plan"]
task_prompt = "Design the API schema."

[[agents]]
name = "backend"
role = "executor"
tier = "standard"
tools = ["read_file", "write_file", "exec"]
skills = []
task_prompt = "Implement endpoints."
""")
    tmpl = load_template(str(t))
    assert isinstance(tmpl, TeamTemplate)
    assert tmpl.name == "example"
    assert tmpl.goal == "Build an API"
    assert tmpl.phases == ["plan", "execute", "verify"]
    assert len(tmpl.agents) == 2
    assert tmpl.agents[0].role == "planner"
    assert tmpl.agents[1].tier == "standard"


def test_rejects_invalid_tier(tmp_path):
    t = _write(tmp_path / "bad.toml", """
name = "bad"
goal = "x"
phases = ["plan"]

[[agents]]
name = "x"
role = "executor"
tier = "megamind"
tools = []
skills = []
task_prompt = "x"
""")
    with pytest.raises(ValueError):
        load_template(str(t))


def test_shipped_templates_parse():
    """Both shipped templates must load without error."""
    for tmpl_file in ["software-dev.toml", "research.toml"]:
        tmpl = load_template(f"templates/{tmpl_file}")
        assert tmpl.name
        assert len(tmpl.agents) > 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_swarm_templates.py -v
```

Expected: FAIL

- [ ] **Step 3: Implement templates**

```python
# src/swarm/__init__.py
"""Swarm coordination — team templates, phase gates, harness runner."""
```

```python
# src/swarm/templates.py
"""TOML team template loader (Pydantic v2 schema)."""
from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class AgentTemplate(BaseModel):
    name: str
    role: str
    tier: Literal["lite", "standard", "advanced", "expert"]
    tools: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    task_prompt: str


class TeamTemplate(BaseModel):
    name: str
    goal: str
    phases: list[str] = Field(default_factory=lambda: ["plan", "execute", "verify"])
    agents: list[AgentTemplate]

    @field_validator("agents")
    @classmethod
    def _nonempty(cls, v):
        if not v:
            raise ValueError("team template must define at least one agent")
        return v


def load_template(path: str) -> TeamTemplate:
    """Load a TOML team template from a file path."""
    p = Path(path)
    with open(p, "rb") as f:
        data = tomllib.load(f)
    return TeamTemplate(**data)
```

```toml
# templates/software-dev.toml
name = "software-dev"
goal = "Build and verify a software feature"
phases = ["plan", "execute", "verify"]

[[agents]]
name = "architect"
role = "planner"
tier = "advanced"
tools = ["read_file", "write_file", "glob", "grep"]
skills = ["plan", "review"]
task_prompt = "Design the feature: break it into 3-5 concrete subtasks, list impacted files, and write a short plan.md."

[[agents]]
name = "backend-dev"
role = "executor"
tier = "standard"
tools = ["read_file", "write_file", "edit_file", "exec", "grep", "glob"]
skills = ["commit", "debug"]
task_prompt = "Implement the subtasks from plan.md. Commit your changes."

[[agents]]
name = "tester"
role = "evaluator"
tier = "standard"
tools = ["read_file", "exec", "grep"]
skills = ["test"]
task_prompt = "Run the test suite and report results. If tests fail, describe the failures concisely."
```

```toml
# templates/research.toml
name = "research"
goal = "Research a topic and produce a written summary"
phases = ["plan", "execute", "verify"]

[[agents]]
name = "lead-researcher"
role = "planner"
tier = "advanced"
tools = ["web_search", "web_fetch"]
skills = []
task_prompt = "Break the research goal into 3 concrete questions. Write them to research_plan.md."

[[agents]]
name = "researcher"
role = "executor"
tier = "standard"
tools = ["web_search", "web_fetch", "read_file", "write_file"]
skills = []
task_prompt = "Answer each question from research_plan.md with citations."

[[agents]]
name = "editor"
role = "evaluator"
tier = "advanced"
tools = ["read_file", "write_file"]
skills = ["review"]
task_prompt = "Synthesize the research into a single summary.md of about 500 words."
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_swarm_templates.py -v
```

Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/swarm/__init__.py src/swarm/templates.py templates/ tests/test_swarm_templates.py
git commit -m "feat(swarm): add TOML team templates + schema loader"
```

---

### Task 10: Swarm — phase gates

**Files:**
- Create: `src/swarm/phases.py`
- Create: `tests/test_swarm_phases.py`

Three concrete gates:
- `ArtifactRequiredGate(file)` — passes if the artifact file exists in the workspace
- `AllTasksCompleteGate` — passes if all registered sub-agents are in `FINISHED` state
- `HumanApprovalGate` — passes when `approve(key)` has been called (test-only stub; full LangGraph interrupt integration is Phase 2B)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_swarm_phases.py
"""Test phase gates."""
import asyncio
import pytest
from langgraph.store.memory import InMemoryStore

from src.subagent.registry import SubAgentRegistry
from src.subagent.state import AgentInfo, SubAgentState
from src.swarm.phases import (
    ArtifactRequiredGate,
    AllTasksCompleteGate,
    HumanApprovalGate,
    HarnessContext,
)


@pytest.mark.asyncio
async def test_artifact_gate_passes_when_file_exists(tmp_path):
    (tmp_path / "plan.md").write_text("content")
    gate = ArtifactRequiredGate(artifact="plan.md")
    ctx = HarnessContext(workspace=str(tmp_path), registry=None, approvals=set())
    result = await gate.check(ctx)
    assert result.passed is True


@pytest.mark.asyncio
async def test_artifact_gate_fails_when_missing(tmp_path):
    gate = ArtifactRequiredGate(artifact="plan.md")
    ctx = HarnessContext(workspace=str(tmp_path), registry=None, approvals=set())
    result = await gate.check(ctx)
    assert result.passed is False
    assert "plan.md" in result.reason


@pytest.mark.asyncio
async def test_all_tasks_complete_when_all_finished():
    store = InMemoryStore()
    registry = SubAgentRegistry(store)

    async def ph():
        await asyncio.sleep(0.01)

    for i in range(2):
        t = asyncio.create_task(ph())
        info = AgentInfo(
            agent_id=f"a{i}", name=f"n{i}", role="executor", task="t",
            tier="standard", tools=[], skills=[],
        )
        registry.register(info, t)
        registry.update_state(f"a{i}", SubAgentState.FINISHED)

    gate = AllTasksCompleteGate()
    ctx = HarnessContext(workspace="", registry=registry, approvals=set())
    result = await gate.check(ctx)
    assert result.passed is True


@pytest.mark.asyncio
async def test_all_tasks_complete_fails_with_running():
    store = InMemoryStore()
    registry = SubAgentRegistry(store)

    async def ph():
        await asyncio.sleep(0.01)

    t = asyncio.create_task(ph())
    info = AgentInfo(
        agent_id="a1", name="n1", role="executor", task="t",
        tier="standard", tools=[], skills=[],
    )
    registry.register(info, t)
    # Leave in SPAWNING

    gate = AllTasksCompleteGate()
    ctx = HarnessContext(workspace="", registry=registry, approvals=set())
    result = await gate.check(ctx)
    assert result.passed is False


@pytest.mark.asyncio
async def test_human_approval_gate():
    gate = HumanApprovalGate(key="plan")
    ctx = HarnessContext(workspace="", registry=None, approvals=set())
    r1 = await gate.check(ctx)
    assert r1.passed is False

    ctx.approvals.add("plan")
    r2 = await gate.check(ctx)
    assert r2.passed is True
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_swarm_phases.py -v
```

Expected: FAIL

- [ ] **Step 3: Implement phase gates**

```python
# src/swarm/phases.py
"""Phase gates — block phase transitions until conditions are met (GAP-5)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..subagent.registry import SubAgentRegistry
from ..subagent.state import SubAgentState


@dataclass
class GateResult:
    passed: bool
    reason: str = ""


@dataclass
class HarnessContext:
    """Context passed to each PhaseGate.check()."""
    workspace: str
    registry: Optional[SubAgentRegistry]
    approvals: set[str] = field(default_factory=set)


class PhaseGate(ABC):
    @abstractmethod
    async def check(self, ctx: HarnessContext) -> GateResult: ...


class ArtifactRequiredGate(PhaseGate):
    """Passes iff an artifact file exists in the workspace."""

    def __init__(self, artifact: str):
        self._artifact = artifact

    async def check(self, ctx: HarnessContext) -> GateResult:
        p = Path(ctx.workspace) / self._artifact
        if p.exists():
            return GateResult(True)
        return GateResult(False, f"Required artifact missing: {self._artifact}")


class AllTasksCompleteGate(PhaseGate):
    """Passes iff every registered agent is FINISHED."""

    async def check(self, ctx: HarnessContext) -> GateResult:
        if ctx.registry is None:
            return GateResult(True, "No registry — treating as complete")
        agents = ctx.registry.list_agents()
        if not agents:
            return GateResult(True, "No agents registered")
        pending = [a for a in agents if a.state != SubAgentState.FINISHED]
        if pending:
            return GateResult(
                False,
                f"{len(pending)} agent(s) not finished: " + ", ".join(a.agent_id for a in pending),
            )
        return GateResult(True)


class HumanApprovalGate(PhaseGate):
    """Passes once ``ctx.approvals`` contains the configured key."""

    def __init__(self, key: str):
        self._key = key

    async def check(self, ctx: HarnessContext) -> GateResult:
        if self._key in ctx.approvals:
            return GateResult(True)
        return GateResult(False, f"Awaiting human approval for '{self._key}'")
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_swarm_phases.py -v
```

Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/swarm/phases.py tests/test_swarm_phases.py
git commit -m "feat(swarm): add PhaseGate ABC + Artifact/AllTasksComplete/HumanApproval gates (GAP-5)"
```

---

### Task 11: Swarm — HarnessRunner (phase state machine)

**Files:**
- Create: `src/swarm/harness.py`
- Create: `tests/test_swarm_harness.py`

A small state machine that walks through a phase list; each phase has an associated gate that must pass before advancing.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_swarm_harness.py
"""Test HarnessRunner — phase state machine."""
import pytest
from src.swarm.harness import HarnessRunner
from src.swarm.phases import (
    ArtifactRequiredGate,
    HumanApprovalGate,
    HarnessContext,
)


@pytest.mark.asyncio
async def test_advances_when_gate_passes(tmp_path):
    (tmp_path / "plan.md").write_text("ok")
    runner = HarnessRunner(
        phases=["plan", "execute"],
        gates={"plan": ArtifactRequiredGate("plan.md")},
    )
    ctx = HarnessContext(workspace=str(tmp_path), registry=None, approvals=set())

    assert runner.current_phase == "plan"
    advanced = await runner.try_advance(ctx)
    assert advanced is True
    assert runner.current_phase == "execute"


@pytest.mark.asyncio
async def test_blocks_when_gate_fails(tmp_path):
    runner = HarnessRunner(
        phases=["plan", "execute"],
        gates={"plan": ArtifactRequiredGate("plan.md")},
    )
    ctx = HarnessContext(workspace=str(tmp_path), registry=None, approvals=set())
    advanced = await runner.try_advance(ctx)
    assert advanced is False
    assert runner.current_phase == "plan"


@pytest.mark.asyncio
async def test_is_finished_after_last_phase(tmp_path):
    runner = HarnessRunner(
        phases=["a", "b"],
        gates={"a": HumanApprovalGate(key="a"), "b": HumanApprovalGate(key="b")},
    )
    ctx = HarnessContext(workspace=str(tmp_path), registry=None, approvals={"a", "b"})

    await runner.try_advance(ctx)  # a → b
    await runner.try_advance(ctx)  # b → finished
    assert runner.is_finished


@pytest.mark.asyncio
async def test_no_gate_means_always_advance(tmp_path):
    """A phase without a configured gate advances freely."""
    runner = HarnessRunner(phases=["a", "b"], gates={})
    ctx = HarnessContext(workspace=str(tmp_path), registry=None, approvals=set())
    advanced = await runner.try_advance(ctx)
    assert advanced is True
    assert runner.current_phase == "b"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_swarm_harness.py -v
```

Expected: FAIL

- [ ] **Step 3: Implement HarnessRunner**

```python
# src/swarm/harness.py
"""HarnessRunner — walks a team through a list of phases, gated by PhaseGate."""
from __future__ import annotations

import logging
from typing import Optional

from .phases import HarnessContext, PhaseGate

logger = logging.getLogger(__name__)


class HarnessRunner:
    """Lightweight phase state machine."""

    def __init__(self, phases: list[str], gates: dict[str, PhaseGate]):
        if not phases:
            raise ValueError("HarnessRunner requires at least one phase")
        self._phases = list(phases)
        self._gates = gates
        self._index = 0

    @property
    def current_phase(self) -> Optional[str]:
        if self.is_finished:
            return None
        return self._phases[self._index]

    @property
    def is_finished(self) -> bool:
        return self._index >= len(self._phases)

    async def try_advance(self, ctx: HarnessContext) -> bool:
        """If the current phase's gate passes, advance. Return whether we advanced."""
        if self.is_finished:
            return False
        phase = self._phases[self._index]
        gate = self._gates.get(phase)
        if gate is None:
            # No gate configured — advance freely
            self._index += 1
            logger.info("Harness: advanced past %s (no gate)", phase)
            return True
        result = await gate.check(ctx)
        if result.passed:
            self._index += 1
            logger.info("Harness: advanced past %s", phase)
            return True
        logger.info("Harness: blocked at %s — %s", phase, result.reason)
        return False
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_swarm_harness.py -v
```

Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/swarm/harness.py tests/test_swarm_harness.py
git commit -m "feat(swarm): add HarnessRunner phase state machine"
```

---

### Task 12: Swarm — Coordinator (team launch)

**Files:**
- Create: `src/swarm/coordinator.py`
- Create: `tests/test_swarm_coordinator.py`

Takes a loaded `TeamTemplate`, spawns each agent via the `DeepAgentsSpawner`, registers them, and wraps them in a `HarnessRunner` with default gates. Launching a team is the public API `swarm.launch(template, goal_override=None)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_swarm_coordinator.py
"""Test Swarm — team coordinator."""
import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock
from langgraph.store.memory import InMemoryStore

from src.api.websocket import EventHub
from src.subagent.broadcaster import EventBroadcaster
from src.subagent.registry import SubAgentRegistry
from src.swarm.coordinator import Swarm
from src.swarm.templates import TeamTemplate, AgentTemplate


def _make_template() -> TeamTemplate:
    return TeamTemplate(
        name="t", goal="g", phases=["plan", "execute"],
        agents=[
            AgentTemplate(name="a1", role="planner", tier="standard",
                          tools=[], skills=[], task_prompt="Plan"),
            AgentTemplate(name="a2", role="executor", tier="standard",
                          tools=[], skills=[], task_prompt="Execute"),
        ],
    )


@pytest.mark.asyncio
async def test_launch_spawns_every_agent():
    store = InMemoryStore()
    registry = SubAgentRegistry(store)
    broadcaster = EventBroadcaster(None)

    async def spawn_stub(info, recovery_context=None):
        async def noop():
            await asyncio.sleep(0.01)
        return asyncio.create_task(noop())

    spawner = MagicMock()
    spawner.spawn = AsyncMock(side_effect=spawn_stub)

    swarm = Swarm(registry=registry, broadcaster=broadcaster, spawner=spawner, workspace="/tmp")
    tmpl = _make_template()
    team_id = await swarm.launch(tmpl)

    assert spawner.spawn.await_count == 2
    assert team_id
    agents = registry.list_agents()
    assert {a.name for a in agents} == {"a1", "a2"}


@pytest.mark.asyncio
async def test_launch_respects_goal_override():
    store = InMemoryStore()
    registry = SubAgentRegistry(store)
    broadcaster = EventBroadcaster(None)

    captured = []

    async def spawn_stub(info, recovery_context=None):
        captured.append(info.task)
        async def noop():
            return
        return asyncio.create_task(noop())

    spawner = MagicMock()
    spawner.spawn = AsyncMock(side_effect=spawn_stub)

    swarm = Swarm(registry=registry, broadcaster=broadcaster, spawner=spawner, workspace="/tmp")
    tmpl = _make_template()
    await swarm.launch(tmpl, goal_override="custom goal")

    # Every spawned agent's task should include the override
    for task_prompt in captured:
        assert "custom goal" in task_prompt
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_swarm_coordinator.py -v
```

Expected: FAIL

- [ ] **Step 3: Implement Swarm coordinator**

```python
# src/swarm/coordinator.py
"""Swarm — team-level launch + harness orchestration."""
from __future__ import annotations

import logging
import uuid

from ..subagent.broadcaster import EventBroadcaster
from ..subagent.registry import SubAgentRegistry
from ..subagent.state import AgentInfo
from .harness import HarnessRunner
from .phases import PhaseGate
from .templates import TeamTemplate

logger = logging.getLogger(__name__)


class Swarm:
    """Launch a team from a TeamTemplate, wire its harness, track its state."""

    def __init__(
        self,
        registry: SubAgentRegistry,
        broadcaster: EventBroadcaster,
        spawner,
        workspace: str,
    ):
        self._registry = registry
        self._broadcaster = broadcaster
        self._spawner = spawner
        self._workspace = workspace
        self._teams: dict[str, HarnessRunner] = {}

    async def launch(
        self,
        template: TeamTemplate,
        goal_override: str | None = None,
        gates: dict[str, PhaseGate] | None = None,
    ) -> str:
        """Spawn every agent in the template. Returns a team_id."""
        team_id = f"team-{uuid.uuid4().hex[:8]}"
        goal = goal_override or template.goal

        for agent_tpl in template.agents:
            agent_id = f"agent-{uuid.uuid4().hex[:8]}"
            info = AgentInfo(
                agent_id=agent_id,
                name=agent_tpl.name,
                role=agent_tpl.role,
                task=f"Team goal: {goal}\n\n{agent_tpl.task_prompt}",
                tier=agent_tpl.tier,
                tools=list(agent_tpl.tools),
                skills=list(agent_tpl.skills),
            )
            task = await self._spawner.spawn(info)
            self._registry.register(info, task)
            logger.info("Launched team member %s (agent_id=%s, role=%s)",
                        agent_tpl.name, agent_id, agent_tpl.role)

        # Register a harness for this team (callers manage advancement)
        self._teams[team_id] = HarnessRunner(
            phases=template.phases,
            gates=gates or {},
        )
        logger.info("Team %s launched with %d agents across %d phases",
                    team_id, len(template.agents), len(template.phases))
        return team_id

    def get_harness(self, team_id: str) -> HarnessRunner | None:
        return self._teams.get(team_id)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_swarm_coordinator.py -v
```

Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/swarm/coordinator.py tests/test_swarm_coordinator.py
git commit -m "feat(swarm): add Swarm coordinator for template-based team launch"
```

---

### Task 13: Wire spawner + recovery executor into main.py

**Files:**
- Modify: `src/agent.py` — instantiate DeepAgentsSpawner + RecoveryExecutor and pass spawner to `init_orchestration_tools`
- Modify: `src/main.py` — replace health loop's "log-only" path with actual recovery
- Modify: `src/subagent/__init__.py` — re-export new public API

- [ ] **Step 1: Update `src/subagent/__init__.py` to export new symbols**

Replace the current `__all__` block by adding:

```python
from .broadcaster import EventBroadcaster
from .budget import BudgetEnforcer, BudgetDecision
from .worktree import WorktreeManager
from .conflicts import ConflictDetector, Conflict
from .spawner import DeepAgentsSpawner
from .recovery_executor import RecoveryExecutor
from .rebalance import TaskRebalancer
```

And add these names to `__all__` in alphabetical order alongside the existing ones.

- [ ] **Step 2: Wire DeepAgentsSpawner + RecoveryExecutor into agent.py**

Locate the sub-agent block in `src/agent.py` (around the `init_orchestration_tools` call). Replace:

```python
        init_orchestration_tools(
            registry=subagent_registry,
            spawner=None,    # Phase 2A wires a real DeepAgents-based spawner
            cost_tracker=cost_tracker,
        )
```

with:

```python
        # Phase 2A: real DeepAgents spawner + recovery executor
        from .subagent.broadcaster import EventBroadcaster
        from .subagent.spawner import DeepAgentsSpawner
        from .subagent.recovery_executor import RecoveryExecutor
        from .subagent.recovery import RecoveryChain

        # Note: event_hub is wired in main.py and passed back via set_event_hub() or
        # similar if you want live broadcasts. For now we pass None; main.py wires
        # it after creating the API channel.
        broadcaster = EventBroadcaster(None)
        tools_by_name = {t.name: t for t in custom_tools}
        spawner = DeepAgentsSpawner(
            registry=subagent_registry,
            broadcaster=broadcaster,
            base_model=model,
            tools_by_name=tools_by_name,
        )
        recovery_executor = RecoveryExecutor(
            registry=subagent_registry,
            chain=RecoveryChain(max_retries=config.subagent.max_retries),
            spawner=spawner,
            broadcaster=broadcaster,
        )

        init_orchestration_tools(
            registry=subagent_registry,
            spawner=spawner.spawn,
            cost_tracker=cost_tracker,
        )
```

Then extend the return tuple to include `recovery_executor` (maintain backwards compatibility by appending at the end; the current 5-tuple becomes a 6-tuple). Update the `return` statement at the bottom of `create_agent`:

```python
    return agent, checkpointer, mcp_client, subagent_registry, cost_tracker, recovery_executor
```

Where `recovery_executor` is `None` when sub-agents are disabled.

- [ ] **Step 3: Wire recovery executor into main.py health loop**

In `src/main.py`, update the `create_agent` unpack:

```python
    agent, checkpointer, mcp_client, subagent_registry, cost_tracker, recovery_executor = await create_agent(config)
```

Then in the existing `health_loop` coroutine, change the unhealthy-agent handling from "log only" to "invoke recovery":

Replace this block in main.py:

```python
            try:
                # Pull fresh heartbeat + iteration from BaseStore so the
                # monitor sees what sub-agents have actually written.
                await subagent_registry.sync_from_store()
                unhealthy = monitor.check_all()
                if unhealthy:
                    logger.warning("Unhealthy sub-agents: %s", unhealthy)
```

with:

```python
            try:
                # Pull fresh heartbeat + iteration from BaseStore so the
                # monitor sees what sub-agents have actually written.
                await subagent_registry.sync_from_store()
                unhealthy = monitor.check_all()
                if unhealthy:
                    logger.warning("Unhealthy sub-agents: %s", unhealthy)
                    if recovery_executor is not None:
                        for agent_id, reason in unhealthy.items():
                            try:
                                await recovery_executor.handle_failure(
                                    agent_id, reason=reason.value,
                                )
                            except Exception as re:
                                logger.error("Recovery failed for %s: %s", agent_id, re)
```

- [ ] **Step 4: Run full suite + verify no regressions**

```bash
pytest tests/ -q --tb=line --ignore=tests/test_middleware_bridge.py --ignore=tests/test_middleware_full.py 2>&1 | tail -3
```

Expected: 6 pre-existing failures, zero new failures. New tests (~50) should add to the `passed` count.

- [ ] **Step 5: Commit**

```bash
git add src/agent.py src/main.py src/subagent/__init__.py
git commit -m "feat(subagent): wire DeepAgentsSpawner + RecoveryExecutor into platform"
```

---

### Task 14: Add SwarmConfig + wire Swarm into agent.py for optional autoloading

**Files:**
- Modify: `src/config.py` — add `SwarmConfig`
- Modify: `config.yaml` — add `swarm:` section
- Modify: `src/agent.py` — instantiate `Swarm` if enabled
- Create: `tests/test_config_swarm.py`

Swarm is off by default; enabling it adds a `launch_team` tool to the master agent (that tool is Phase 3 — for now we just validate config wiring).

- [ ] **Step 1: Write failing test**

```python
# tests/test_config_swarm.py
"""Test that SwarmConfig loads from config.yaml."""
def test_swarm_config_defaults():
    from src.config import SwarmConfig
    cfg = SwarmConfig()
    assert cfg.enabled is False
    assert cfg.templates_dir == "templates"
    assert cfg.workspace == "./workspace"


def test_swarm_config_override():
    from src.config import SwarmConfig
    cfg = SwarmConfig(enabled=True, templates_dir="custom/", workspace="/tmp")
    assert cfg.enabled is True
    assert cfg.templates_dir == "custom/"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_config_swarm.py -v
```

Expected: FAIL — `ImportError` on SwarmConfig.

- [ ] **Step 3: Add SwarmConfig to `src/config.py`**

Find where other config classes (e.g. `SubAgentConfig`) are defined and add:

```python
class SwarmConfig(BaseModel):
    enabled: bool = False
    templates_dir: str = "templates"
    workspace: str = "./workspace"
```

Add a field on `AppConfig`:

```python
swarm: SwarmConfig = Field(default_factory=SwarmConfig)
```

- [ ] **Step 4: Add to `config.yaml`**

Append:

```yaml
swarm:
  enabled: false
  templates_dir: "templates"
  workspace: "./workspace"
```

- [ ] **Step 5: Run test to verify it passes**

```bash
pytest tests/test_config_swarm.py -v
```

Expected: PASS (2 tests)

- [ ] **Step 6: Commit**

```bash
git add src/config.py config.yaml tests/test_config_swarm.py
git commit -m "feat(config): add SwarmConfig (enabled/templates_dir/workspace)"
```

---

### Task 15: Final verification and tag

**Files:**
- None modified directly; this is verification only.

- [ ] **Step 1: Run full test suite**

```bash
pytest tests/ -q --tb=line --ignore=tests/test_middleware_bridge.py --ignore=tests/test_middleware_full.py 2>&1 | tail -5
```

Expected: Same 6 pre-existing failures. New passing count should be roughly 722 + ~50 = ~770.

- [ ] **Step 2: Verify public API imports**

```bash
python3 -c "
from src.subagent import (
    SubAgentState, AgentInfo, FailureReason, RecoveryAction,
    AgentStore, SubAgentRegistry, HealthMonitor, RecoveryChain,
    next_tier, build_recovery_context,
    EventBroadcaster, BudgetEnforcer, BudgetDecision,
    WorktreeManager, ConflictDetector, Conflict,
    DeepAgentsSpawner, RecoveryExecutor, TaskRebalancer,
    init_orchestration_tools,
    spawn_agent, recall_agent, monitor_agents,
    assign_task, switch_agent_model, review_cost,
)
from src.swarm.templates import TeamTemplate, AgentTemplate, load_template
from src.swarm.phases import (
    PhaseGate, GateResult, HarnessContext,
    ArtifactRequiredGate, AllTasksCompleteGate, HumanApprovalGate,
)
from src.swarm.harness import HarnessRunner
from src.swarm.coordinator import Swarm
print('Phase 2A public API: OK')
"
```

Expected: `Phase 2A public API: OK`

- [ ] **Step 3: Smoke-load templates**

```bash
python3 -c "
from src.swarm.templates import load_template
for t in ['software-dev.toml', 'research.toml']:
    tmpl = load_template(f'templates/{t}')
    print(f'{tmpl.name}: {len(tmpl.agents)} agents, phases={tmpl.phases}')
"
```

Expected:
```
software-dev: 3 agents, phases=['plan', 'execute', 'verify']
research: 3 agents, phases=['plan', 'execute', 'verify']
```

- [ ] **Step 4: Tag and push**

```bash
git tag v0.4.0-phase2a
git push origin feature/implementation-plans --tags
```

- [ ] **Step 5: Update plan index**

Edit `docs/superpowers/plans/README.md` and mark Phase 2A as DONE. Add v0.4.0-phase2a to the tag table.

```bash
git add docs/superpowers/plans/README.md
git commit -m "docs: mark Phase 2A as DONE"
git push origin feature/implementation-plans
```

---

## Exit Criteria

- [ ] `agent_spawn_event` / `agent_progress_event` / `agent_complete_event` / `agent_failed_event` factories added to `src/core/streaming.py`
- [ ] `EventBroadcaster` in `src/subagent/broadcaster.py`
- [ ] `BudgetEnforcer` + `BudgetDecision` enum in `src/subagent/budget.py`
- [ ] `WorktreeManager` with create/merge/cleanup/list_agents in `src/subagent/worktree.py`
- [ ] `ConflictDetector` with pairwise `detect(worktrees)` in `src/subagent/conflicts.py`
- [ ] `DeepAgentsSpawner` runs inner DeepAgents instance, writes heartbeat/progress/result, emits events, updates state transitions
- [ ] `RecoveryExecutor.handle_failure(agent_id, reason)` executes retry/escalate/reassign/abort
- [ ] `TaskRebalancer.rebalance_from(agent_id)` moves inbox messages to same-role survivors
- [ ] `TeamTemplate`/`AgentTemplate` Pydantic schemas + `load_template(path)` loader
- [ ] Two shipped templates: `software-dev.toml`, `research.toml`
- [ ] `PhaseGate` ABC + three concrete gates (Artifact, AllTasksComplete, HumanApproval)
- [ ] `HarnessRunner` phase state machine with `try_advance` / `current_phase` / `is_finished`
- [ ] `Swarm` coordinator with `launch(template, goal_override, gates)` and `get_harness(team_id)`
- [ ] `SubAgentRegistry` is wired with the real spawner (not `None`) in `src/agent.py`
- [ ] Health loop calls `RecoveryExecutor.handle_failure` for each unhealthy agent
- [ ] `SwarmConfig` added to config, with `config.yaml` defaults
- [ ] Public API exports updated in `src/subagent/__init__.py`
- [ ] All tests pass (~770 total), 6 pre-existing failures unchanged
- [ ] Tagged as `v0.4.0-phase2a`

## What's deferred to Phase 2B / 3

- LangGraph `interrupt()` integration for `HumanApprovalGate` — currently uses a bare `ctx.approvals` set; Phase 2B wires channel-based approval UI
- Web UI for team monitoring — depends on this phase's `Swarm.get_harness` + event broadcasts but the React UI itself is Phase 2B
- Green-level contracts (GAP-7) — requires real test execution in worktrees; Phase 3
- Richer reassignment matching (tools/skills overlap scoring) — Phase 3
- Event hub wiring from the API channel back into the spawner's broadcaster (currently `None` in `agent.py`) — simple follow-up; leaving it as `None` makes tests hermetic and the system still works without live broadcasts
- `launch_team` `@tool` for the master agent to invoke `Swarm.launch` — Phase 3
- Per-session budget enforcement (currently only per-agent) — `CostTracker.session_over_budget` stub — Phase 3
