# WS4 — Autonomous Swarm Phase Advancement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a launched swarm team advance `plan → execute → verify` on its own — activating each phase's agents, waiting on that phase's gate, and advancing when it passes — instead of requiring a caller to step `HarnessRunner.try_advance` manually.

**Architecture:** Agents are bound to phases via a new optional `AgentTemplate.phase`. `Swarm.launch` spawns only the **first** phase's agents (phased mode) and registers a `HarnessRunner`. A single background `SwarmDriver` loop (mirroring the existing `HealthMonitor` loop in `main.py`) ticks all teams: for each, it builds a `HarnessContext` and calls `runner.try_advance`; when a phase's gate passes it advances and the driver **activates the next phase's agents** via `Swarm.activate_phase`. A phase with agents but no explicit gate defaults to `AllTasksCompleteGate`, so advancement waits for that phase's agents to finish. A `FAILED` agent keeps `AllTasksCompleteGate` closed — the phase blocks and the existing `HealthMonitor`+`RecoveryChain` handle the agent; the driver never wedges or crashes.

**Tech Stack:** Python 3.13, the existing `HarnessRunner`/`PhaseGate`/`HarnessContext` (`src/swarm/`), `SubAgentRegistry`, the `DeepAgentsSpawner`, `EventBroadcaster`/`StreamEvent` (`src/core/streaming.py`), pytest + pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-06-23-orchestration-completion-scope.md` §4 WS4, §6.1 (option a — phase-per-agent activation). Depends on WS1–WS3 (merged on this branch).

### Design decisions
1. **Phase-per-agent activation (scope §6.1 option a).** `AgentTemplate.phase: str | None`. A template is "phased" iff **any** agent declares a `phase`. Phased mode activates agents phase-by-phase; legacy mode (no agent declares a phase) keeps the current "spawn all at launch" behavior, with no driver involvement.
2. **Sequential activation.** `launch` activates phase[0] only. The driver activates phase[N] when the harness advances into it. Prior-phase agents stay `FINISHED` in the registry.
3. **Default gating.** In phased mode, any declared phase that has agents and no explicit gate gets an `AllTasksCompleteGate`. (It checks all registered agents; since prior phases are already `FINISHED`, it effectively gates on the current phase's agents.) Without this default a gateless phase would advance immediately and spawn the next phase's agents while the current ones are still running.
4. **Single driver loop.** One `SwarmDriver` (not per-team tasks), ticking `swarm.iter_teams()` each interval — mirrors `HealthMonitor` for simple lifecycle/cancellation in `main.py`.
5. **FAILED-safe, no wedge.** A `FAILED` agent keeps `AllTasksCompleteGate` closed; the phase stays blocked and `HealthMonitor`+`RecoveryChain` act on the agent out-of-band. If recovery cannot resolve it the phase stays blocked (an operator/timeout intervenes) — the driver itself never crashes or busy-fails. Logged.
6. **Activates the dormant Swarm fields.** `Swarm._workspace` → `HarnessContext.workspace`; `Swarm._broadcaster` → a new `team_phase` lifecycle event (added to `streaming.py` + `EventBroadcaster`).
7. **`create_team` agent tool stays deferred** (per approved scope §8). WS4 is the engine, driven via `Swarm.launch`; exposing team launch to the master agent / API is a separate follow-up. Tests drive `Swarm.launch` directly.

---

## File Structure

| File | Responsibility | Change |
|------|----------------|--------|
| `src/swarm/templates.py` | Team/agent template schema | Modify — add `AgentTemplate.phase`, `TeamTemplate.is_phased`, `.agents_for_phase()`, cross-field phase validation |
| `src/swarm/coordinator.py` | Team launch + per-team state + phase activation | Modify — phase-aware `launch`, `activate_phase`, store template/goal/approvals per team, default gating |
| `src/swarm/driver.py` | Autonomous phase-advancement loop | **Create** — `SwarmDriver.tick()` |
| `src/core/streaming.py` | Event types/factories | Modify — add `TEAM_PHASE` + `team_phase_event` |
| `src/subagent/broadcaster.py` | Lifecycle event facade | Modify — add `team_phase(...)` |
| `src/main.py` | Background-task wiring | Modify — start a `swarm_driver` loop when `config.swarm.enabled` |
| `tests/test_swarm_templates.py`, `tests/test_swarm_coordinator.py`, `tests/test_swarm_driver.py` | Tests | Modify/Create |

---

## Task 1: Phase field + template helpers

**Files:**
- Modify: `src/swarm/templates.py`
- Test: `tests/test_swarm_templates.py` (create if absent; otherwise append)

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from pydantic import ValidationError
from src.swarm.templates import TeamTemplate, AgentTemplate


def _agent(name, phase=None):
    return {"name": name, "role": "executor", "tier": "standard",
            "task_prompt": "do x", "tools": [], "skills": [],
            **({"phase": phase} if phase is not None else {})}


def test_agent_template_phase_defaults_none():
    a = AgentTemplate(**_agent("a"))
    assert a.phase is None


def test_team_is_phased_true_when_any_agent_has_phase():
    t = TeamTemplate(name="t", goal="g", phases=["plan", "execute"],
                     agents=[AgentTemplate(**_agent("a", "plan"))])
    assert t.is_phased is True


def test_team_is_phased_false_when_no_phases():
    t = TeamTemplate(name="t", goal="g", phases=["plan", "execute"],
                     agents=[AgentTemplate(**_agent("a"))])
    assert t.is_phased is False


def test_agents_for_phase_filters():
    t = TeamTemplate(name="t", goal="g", phases=["plan", "execute"],
                     agents=[AgentTemplate(**_agent("a", "plan")),
                             AgentTemplate(**_agent("b", "execute")),
                             AgentTemplate(**_agent("c", "plan"))])
    assert [a.name for a in t.agents_for_phase("plan")] == ["a", "c"]
    assert [a.name for a in t.agents_for_phase("execute")] == ["b"]


def test_unknown_agent_phase_rejected():
    with pytest.raises(ValidationError):
        TeamTemplate(name="t", goal="g", phases=["plan", "execute"],
                     agents=[AgentTemplate(**_agent("a", "bogus"))])
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_swarm_templates.py -k "phase or phased" -v`
Expected: FAIL — `AgentTemplate` has no `phase`; no `is_phased`/`agents_for_phase`; no cross-field validation.

- [ ] **Step 3: Implement**

In `src/swarm/templates.py`:

(a) Add `phase` to `AgentTemplate` (after `task_prompt`):
```python
    task_prompt: str = Field(min_length=1)
    phase: Optional[str] = None
```

(b) Add a phase strip-or-none validator on `AgentTemplate`:
```python
    @field_validator("phase")
    @classmethod
    def _strip_phase(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v2 = v.strip()
        return v2 or None
```

(c) Add cross-field validation + helpers to `TeamTemplate`. Add the import `from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator` (add `model_validator`), then:
```python
    @model_validator(mode="after")
    def _validate_agent_phases(self) -> "TeamTemplate":
        known = set(self.phases)
        for a in self.agents:
            if a.phase is not None and a.phase not in known:
                raise ValueError(
                    f"agent {a.name!r} references unknown phase {a.phase!r}; "
                    f"known phases: {self.phases}"
                )
        return self

    @property
    def is_phased(self) -> bool:
        """True iff any agent is bound to a phase (enables phased activation)."""
        return any(a.phase is not None for a in self.agents)

    def agents_for_phase(self, phase: str) -> list["AgentTemplate"]:
        """Agents declared for a given phase (order-preserving)."""
        return [a for a in self.agents if a.phase == phase]
```

- [ ] **Step 4: Run the new tests + full template suite**

Run: `python -m pytest tests/test_swarm_templates.py -v`
Expected: PASS — new tests + any existing template tests (the `phase` field defaults to None, so existing templates without it are unaffected; the built-in `research.toml`/`software-dev.toml` declare no `phase`, so `load_builtin` still works and they remain legacy/non-phased).

- [ ] **Step 5: Commit**

```bash
git add src/swarm/templates.py tests/test_swarm_templates.py
git commit -m "feat(swarm): add per-agent phase field + is_phased/agents_for_phase helpers"
```

---

## Task 2: Phase-aware `Swarm.launch` + `activate_phase`

Refactor launch so phased templates activate only the first phase, store per-team state for the driver, and default-gate phases-with-agents. Legacy (non-phased) templates keep current behavior.

**Files:**
- Modify: `src/swarm/coordinator.py`
- Test: `tests/test_swarm_coordinator.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_swarm_coordinator.py` (match the file's existing fake-spawner style; this assumes a spawner whose `.spawn(info)` returns a completed asyncio.Task):

```python
import asyncio
import pytest
from langgraph.store.memory import InMemoryStore
from src.swarm.coordinator import Swarm
from src.swarm.templates import TeamTemplate, AgentTemplate
from src.subagent.registry import SubAgentRegistry
from src.subagent.broadcaster import EventBroadcaster
from src.subagent.state import SubAgentState


class _FakeSpawner:
    def __init__(self):
        self.spawned = []
    async def spawn(self, info, recovery_context=None):
        self.spawned.append(info.agent_id)
        return asyncio.create_task(asyncio.sleep(0))


def _phased_template():
    return TeamTemplate(
        name="t", goal="g", phases=["plan", "execute"],
        agents=[
            AgentTemplate(name="architect", role="planner", tier="standard",
                          task_prompt="plan it", tools=[], skills=[], phase="plan"),
            AgentTemplate(name="dev", role="executor", tier="standard",
                          task_prompt="build it", tools=[], skills=[], phase="execute"),
        ],
    )


@pytest.mark.asyncio
async def test_phased_launch_activates_only_first_phase():
    registry = SubAgentRegistry(InMemoryStore())
    spawner = _FakeSpawner()
    swarm = Swarm(registry=registry, broadcaster=EventBroadcaster(None),
                  spawner=spawner, workspace="/tmp/ws")
    team_id = await swarm.launch(_phased_template())

    # Only the "plan" phase agent spawned at launch.
    assert len(spawner.spawned) == 1
    assert len(swarm.get_team_agents(team_id)) == 1
    assert swarm.get_harness(team_id).current_phase == "plan"


@pytest.mark.asyncio
async def test_activate_phase_spawns_that_phases_agents():
    registry = SubAgentRegistry(InMemoryStore())
    spawner = _FakeSpawner()
    swarm = Swarm(registry=registry, broadcaster=EventBroadcaster(None),
                  spawner=spawner, workspace="/tmp/ws")
    team_id = await swarm.launch(_phased_template())

    new_ids = await swarm.activate_phase(team_id, "execute")
    assert len(new_ids) == 1
    assert len(spawner.spawned) == 2          # plan + execute
    assert len(swarm.get_team_agents(team_id)) == 2


@pytest.mark.asyncio
async def test_phased_launch_defaults_gate_for_agent_phases():
    registry = SubAgentRegistry(InMemoryStore())
    spawner = _FakeSpawner()
    swarm = Swarm(registry=registry, broadcaster=EventBroadcaster(None),
                  spawner=spawner, workspace="/tmp/ws")
    team_id = await swarm.launch(_phased_template())
    runner = swarm.get_harness(team_id)

    # "plan" has an agent → gets a default AllTasksCompleteGate → does NOT
    # advance while that agent is unfinished.
    from src.swarm.phases import HarnessContext
    ctx = HarnessContext(workspace="/tmp/ws", registry=registry)
    advanced = await runner.try_advance(ctx)
    assert advanced is False
    assert runner.current_phase == "plan"


@pytest.mark.asyncio
async def test_legacy_launch_spawns_all_at_once():
    registry = SubAgentRegistry(InMemoryStore())
    spawner = _FakeSpawner()
    swarm = Swarm(registry=registry, broadcaster=EventBroadcaster(None),
                  spawner=spawner, workspace="/tmp/ws")
    # No agent declares a phase → legacy mode.
    tmpl = TeamTemplate(name="t", goal="g", phases=["plan", "execute"],
                        agents=[AgentTemplate(name="a", role="executor", tier="standard",
                                              task_prompt="x", tools=[], skills=[]),
                                AgentTemplate(name="b", role="executor", tier="standard",
                                              task_prompt="y", tools=[], skills=[])])
    team_id = await swarm.launch(tmpl)
    assert len(spawner.spawned) == 2          # both at launch
    assert len(swarm.get_team_agents(team_id)) == 2
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_swarm_coordinator.py -k "phased or activate or legacy" -v`
Expected: FAIL — `launch` spawns all agents regardless of phase; no `activate_phase`.

- [ ] **Step 3: Implement**

In `src/swarm/coordinator.py`:

(a) Add imports near the top:
```python
from .phases import AllTasksCompleteGate, PhaseGate
```
(Keep the existing `from .phases import PhaseGate` — merge into one import line.)

(b) Add per-team state in `__init__` (alongside `_teams`/`_team_agents`):
```python
        self._teams: dict[str, HarnessRunner] = {}
        self._team_agents: dict[str, list[str]] = {}
        self._team_templates: dict[str, TeamTemplate] = {}
        self._team_goals: dict[str, str] = {}
        self._team_approvals: dict[str, set[str]] = {}
```

(c) Extract the single-agent spawn into a helper (used by both launch and activate_phase):
```python
    async def _spawn_one(self, team_id: str, agent_tpl, goal: str) -> str:
        """Spawn + register one agent for a team. Returns the agent_id."""
        agent_id = self._new_agent_id()
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
        self._team_agents[team_id].append(agent_id)
        logger.info("Spawned team member %s (agent_id=%s, role=%s, phase=%s)",
                    agent_tpl.name, agent_id, agent_tpl.role, agent_tpl.phase)
        return agent_id
```

(d) Replace `launch` with the phase-aware version:
```python
    async def launch(
        self,
        template: TeamTemplate,
        goal_override: str | None = None,
        gates: dict[str, PhaseGate] | None = None,
    ) -> str:
        """Launch a team. Phased templates activate only the first phase; the
        SwarmDriver activates later phases. Legacy templates spawn all agents.

        Raises ValueError if ``gates`` reference unknown phases. Spawn failures
        roll back any agents already registered for this team before re-raising.
        """
        gates = dict(gates or {})
        unknown_gates = set(gates) - set(template.phases)
        if unknown_gates:
            raise ValueError(
                f"Swarm.launch: gates reference unknown phases: {sorted(unknown_gates)}"
            )

        # Default-gate phases that have agents and no explicit gate, so the
        # driver waits for each phase's agents before advancing.
        if template.is_phased:
            for ph in template.phases:
                if ph not in gates and template.agents_for_phase(ph):
                    gates[ph] = AllTasksCompleteGate()

        team_id = self._new_team_id()
        goal = goal_override or template.goal
        self._team_agents[team_id] = []
        self._team_templates[team_id] = template
        self._team_goals[team_id] = goal
        self._team_approvals[team_id] = set()

        try:
            if template.is_phased:
                first_phase = template.phases[0]
                for agent_tpl in template.agents_for_phase(first_phase):
                    await self._spawn_one(team_id, agent_tpl, goal)
            else:
                for agent_tpl in template.agents:
                    await self._spawn_one(team_id, agent_tpl, goal)
        except Exception:
            logger.exception("Team %s launch failed; rolling back", team_id)
            await self._rollback(self._team_agents.get(team_id, []))
            self._team_agents.pop(team_id, None)
            self._team_templates.pop(team_id, None)
            self._team_goals.pop(team_id, None)
            self._team_approvals.pop(team_id, None)
            raise

        self._teams[team_id] = HarnessRunner(phases=template.phases, gates=gates)
        logger.info(
            "Team %s launched (%s mode) with %d agent(s); phases=%s",
            team_id, "phased" if template.is_phased else "legacy",
            len(self._team_agents[team_id]), template.phases,
        )
        return team_id

    async def activate_phase(self, team_id: str, phase: str) -> list[str]:
        """Spawn the agents declared for ``phase``. Returns their agent_ids.

        Returns [] for an unknown team or a phase with no declared agents.
        """
        template = self._team_templates.get(team_id)
        if template is None:
            return []
        goal = self._team_goals.get(team_id, template.goal)
        new_ids: list[str] = []
        for agent_tpl in template.agents_for_phase(phase):
            new_ids.append(await self._spawn_one(team_id, agent_tpl, goal))
        if new_ids:
            logger.info("Team %s activated phase %s with %d agent(s)",
                        team_id, phase, len(new_ids))
        return new_ids

    def get_approvals(self, team_id: str) -> set[str]:
        """The mutable approvals set for a team (consumed by HumanApprovalGate)."""
        return self._team_approvals.setdefault(team_id, set())
```

(e) Keep `_rollback`, `get_harness`, `get_team_agents`, `iter_teams`, `_new_team_id`, `_new_agent_id` as they are. Update `get_team_agents` only if it reads `_team_agents` (it does — leave it).

- [ ] **Step 4: Run the new tests + full coordinator suite**

Run: `python -m pytest tests/test_swarm_coordinator.py -v`
Expected: PASS — new tests + existing coordinator tests. (Existing tests use non-phased templates → legacy path → spawn-all behavior preserved. If an existing test asserted launch spawns all agents of a phased template, update it to the phased expectation — but the built-in templates declare no phase, so they stay legacy.)

- [ ] **Step 5: Commit**

```bash
git add src/swarm/coordinator.py tests/test_swarm_coordinator.py
git commit -m "feat(swarm): phase-aware launch + activate_phase + default per-phase gating"
```

---

## Task 3: `SwarmDriver` + team lifecycle event

**Files:**
- Create: `src/swarm/driver.py`
- Modify: `src/core/streaming.py`, `src/subagent/broadcaster.py`
- Test: `tests/test_swarm_driver.py` (create)

- [ ] **Step 1: Add the team event type + factory + broadcaster method**

In `src/core/streaming.py`, add to `EventType`:
```python
    TEAM_PHASE = "team_phase"
```
and a factory (near the other `*_event` functions):
```python
def team_phase_event(team_id: str, phase: str, status: str, user_id: str = "", agent_id: str = "master") -> StreamEvent:
    return StreamEvent(type=EventType.TEAM_PHASE, data={"team_id": team_id, "phase": phase, "status": status}, agent_id=agent_id, user_id=user_id)
```

In `src/subagent/broadcaster.py`, add the import and method:
```python
from ..core.streaming import (
    agent_spawn_event,
    agent_progress_event,
    agent_complete_event,
    agent_failed_event,
    team_phase_event,
)
```
```python
    def team_phase(self, team_id: str, phase: str, status: str) -> None:
        """status: 'active' (phase agents spawned) | 'complete' (team finished)."""
        self._emit(team_phase_event(team_id=team_id, phase=phase, status=status))
```

- [ ] **Step 2: Write the failing driver tests**

Create `tests/test_swarm_driver.py`:
```python
import asyncio
import pytest
from langgraph.store.memory import InMemoryStore
from src.swarm.coordinator import Swarm
from src.swarm.driver import SwarmDriver
from src.swarm.templates import TeamTemplate, AgentTemplate
from src.subagent.registry import SubAgentRegistry
from src.subagent.broadcaster import EventBroadcaster
from src.subagent.state import SubAgentState


class _FakeSpawner:
    def __init__(self):
        self.spawned = []
    async def spawn(self, info, recovery_context=None):
        self.spawned.append(info.agent_id)
        return asyncio.create_task(asyncio.sleep(0))


def _phased_template():
    return TeamTemplate(
        name="t", goal="g", phases=["plan", "execute"],
        agents=[
            AgentTemplate(name="architect", role="planner", tier="standard",
                          task_prompt="plan", tools=[], skills=[], phase="plan"),
            AgentTemplate(name="dev", role="executor", tier="standard",
                          task_prompt="build", tools=[], skills=[], phase="execute"),
        ],
    )


def _finish_all(registry):
    for info in registry.list_agents():
        registry.update_state(info.agent_id, SubAgentState.FINISHED)


@pytest.mark.asyncio
async def test_driver_advances_when_phase_agents_finish():
    registry = SubAgentRegistry(InMemoryStore())
    spawner = _FakeSpawner()
    swarm = Swarm(registry=registry, broadcaster=EventBroadcaster(None),
                  spawner=spawner, workspace="/tmp/ws")
    driver = SwarmDriver(swarm=swarm, registry=registry,
                         broadcaster=EventBroadcaster(None), workspace="/tmp/ws")
    team_id = await swarm.launch(_phased_template())

    # Phase "plan" agents not finished → tick does not advance.
    await driver.tick()
    assert swarm.get_harness(team_id).current_phase == "plan"
    assert len(spawner.spawned) == 1

    # Finish "plan" agent → tick advances to "execute" and activates its agent.
    _finish_all(registry)
    await driver.tick()
    assert swarm.get_harness(team_id).current_phase == "execute"
    assert len(spawner.spawned) == 2

    # Finish "execute" agent → tick advances past the last phase → finished.
    _finish_all(registry)
    await driver.tick()
    assert swarm.get_harness(team_id).is_finished is True


@pytest.mark.asyncio
async def test_driver_emits_team_phase_events():
    from src.api.websocket import EventHub
    registry = SubAgentRegistry(InMemoryStore())
    spawner = _FakeSpawner()
    hub = EventHub()
    bc = EventBroadcaster(hub)
    swarm = Swarm(registry=registry, broadcaster=bc, spawner=spawner, workspace="/tmp/ws")
    driver = SwarmDriver(swarm=swarm, registry=registry, broadcaster=bc, workspace="/tmp/ws")

    events = []
    async def sub():
        async for ev in hub.subscribe():
            events.append(ev)
            if ev.type == "team_phase" and ev.data.get("status") == "complete":
                break
    sub_task = asyncio.create_task(sub())
    await asyncio.sleep(0.05)

    await swarm.launch(_phased_template())
    _finish_all(registry); await driver.tick()   # plan → execute (activate)
    _finish_all(registry); await driver.tick()    # execute → finished (complete)
    await asyncio.wait_for(sub_task, timeout=2.0)

    team_events = [e for e in events if e.type == "team_phase"]
    assert any(e.data["status"] == "active" and e.data["phase"] == "execute" for e in team_events)
    assert any(e.data["status"] == "complete" for e in team_events)


@pytest.mark.asyncio
async def test_driver_does_not_advance_on_failed_agent():
    registry = SubAgentRegistry(InMemoryStore())
    spawner = _FakeSpawner()
    swarm = Swarm(registry=registry, broadcaster=EventBroadcaster(None),
                  spawner=spawner, workspace="/tmp/ws")
    driver = SwarmDriver(swarm=swarm, registry=registry,
                         broadcaster=EventBroadcaster(None), workspace="/tmp/ws")
    team_id = await swarm.launch(_phased_template())

    # A FAILED agent keeps AllTasksCompleteGate closed — phase stays blocked.
    for info in registry.list_agents():
        registry.update_state(info.agent_id, SubAgentState.FAILED)
    await driver.tick()
    assert swarm.get_harness(team_id).current_phase == "plan"
    assert swarm.get_harness(team_id).is_finished is False
```

- [ ] **Step 3: Run to verify they fail**

Run: `python -m pytest tests/test_swarm_driver.py -v`
Expected: FAIL — `src/swarm/driver.py` does not exist.

- [ ] **Step 4: Implement `SwarmDriver`**

Create `src/swarm/driver.py`:
```python
"""SwarmDriver — autonomously advances launched teams through their phases.

A single background loop ticks every team registered in the Swarm. For each
unfinished team it builds a HarnessContext and calls ``HarnessRunner.try_advance``;
when a phase's gate passes it advances and activates the next phase's agents via
``Swarm.activate_phase``. A team is reported ``complete`` exactly once when its
harness finishes. The driver never crashes on a single team's error — it logs and
moves on, so one wedged team cannot stall the others.
"""
from __future__ import annotations

import logging
from typing import Any

from ..subagent.broadcaster import EventBroadcaster
from ..subagent.registry import SubAgentRegistry
from .phases import HarnessContext

logger = logging.getLogger(__name__)


class SwarmDriver:
    """Drives autonomous phase advancement across all teams in a Swarm."""

    def __init__(
        self,
        swarm: Any,
        registry: SubAgentRegistry,
        broadcaster: EventBroadcaster,
        workspace: str,
    ):
        self._swarm = swarm
        self._registry = registry
        self._broadcaster = broadcaster
        self._workspace = workspace
        self._completed: set[str] = set()

    async def tick(self) -> None:
        """Advance every team one step where its current phase's gate allows."""
        for team_id, runner in list(self._swarm.iter_teams()):
            try:
                await self._tick_team(team_id, runner)
            except Exception as e:
                logger.error("SwarmDriver: team %s tick failed: %s", team_id, e)

    async def _tick_team(self, team_id: str, runner) -> None:
        if runner.is_finished:
            if team_id not in self._completed:
                self._completed.add(team_id)
                self._broadcaster.team_phase(team_id, phase="", status="complete")
                logger.info("Team %s finished all phases", team_id)
            return

        ctx = HarnessContext(
            workspace=self._workspace,
            registry=self._registry,
            approvals=self._swarm.get_approvals(team_id),
        )
        advanced = await runner.try_advance(ctx)
        if not advanced:
            return

        if runner.is_finished:
            self._completed.add(team_id)
            self._broadcaster.team_phase(team_id, phase="", status="complete")
            logger.info("Team %s finished all phases", team_id)
            return

        new_phase = runner.current_phase
        await self._swarm.activate_phase(team_id, new_phase)
        self._broadcaster.team_phase(team_id, phase=new_phase, status="active")
```

- [ ] **Step 5: Run the driver tests + the streaming/broadcaster suites**

Run: `python -m pytest tests/test_swarm_driver.py tests/test_broadcaster.py tests/test_swarm_coordinator.py -v`
Expected: PASS — driver advances on finish, emits `active`/`complete` events, and stays blocked on a FAILED agent.

- [ ] **Step 6: Commit**

```bash
git add src/swarm/driver.py src/core/streaming.py src/subagent/broadcaster.py tests/test_swarm_driver.py
git commit -m "feat(swarm): SwarmDriver autonomous phase advancement + team_phase event"
```

---

## Task 4: Wire `SwarmDriver` into `main.py`

**Files:**
- Modify: `src/main.py`
- Test: `tests/test_main_swarm_driver.py` (create) — a focused loop/wiring test

- [ ] **Step 1: Write the failing test**

The driver loop is structured like `health_loop`; test the loop body's lifecycle, not `main()` end-to-end. Create `tests/test_main_swarm_driver.py`:
```python
import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock
from src.main import _run_swarm_driver_once  # helper extracted in Step 3


@pytest.mark.asyncio
async def test_run_swarm_driver_once_calls_tick():
    driver = MagicMock()
    driver.tick = AsyncMock()
    await _run_swarm_driver_once(driver)
    driver.tick.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_swarm_driver_once_swallows_errors():
    driver = MagicMock()
    driver.tick = AsyncMock(side_effect=RuntimeError("boom"))
    # Must not raise — a driver error should not kill the loop.
    await _run_swarm_driver_once(driver)
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_main_swarm_driver.py -v`
Expected: FAIL — `_run_swarm_driver_once` does not exist.

- [ ] **Step 3: Implement the loop in `main.py`**

In `src/main.py`, add the helper near the other background-loop code:
```python
async def _run_swarm_driver_once(driver) -> None:
    """One swarm-driver tick, error-isolated so the loop survives failures."""
    try:
        await driver.tick()
    except Exception as e:
        logger.error("Swarm driver error: %s", e)
```

Then, after the health-monitor wiring (and only when swarm + driver deps exist), start the loop. Place alongside the existing `health_task` setup:
```python
    swarm_task = None
    if config.swarm.enabled and bundle.swarm is not None and bundle.subagent_registry is not None:
        from .swarm.driver import SwarmDriver
        swarm_driver = SwarmDriver(
            swarm=bundle.swarm,
            registry=bundle.subagent_registry,
            broadcaster=bundle.broadcaster,
            workspace=config.swarm.workspace,
        )

        async def swarm_loop():
            interval = getattr(config.swarm, "poll_interval", 5.0)
            while True:
                await asyncio.sleep(interval)
                await _run_swarm_driver_once(swarm_driver)

        swarm_task = asyncio.create_task(swarm_loop())
        logger.info("Swarm driver started")
```

And in the shutdown section (where `health_task` is cancelled), add:
```python
    if swarm_task:
        swarm_task.cancel()
        try:
            await swarm_task
        except asyncio.CancelledError:
            pass
```

If `SwarmConfig` has no `poll_interval`, the `getattr(..., 5.0)` default covers it; optionally add `poll_interval: float = 5.0` to `SwarmConfig` in `src/config.py` for explicit configuration (do this if you also add a test asserting the default).

- [ ] **Step 4: Run the wiring test + broad regression sweep**

Run: `python -m pytest tests/test_main_swarm_driver.py -v && python -m pytest tests/ -k "swarm or subagent or spawn or agent_swarm or config or harness or phase or coordinator or driver or broadcaster" -q`
Expected: PASS — loop helper tested; no regressions.

- [ ] **Step 5: Commit**

```bash
git add src/main.py tests/test_main_swarm_driver.py
git commit -m "feat(swarm): wire SwarmDriver background loop into main"
```

---

## Self-Review

**Spec coverage (scope doc §4 WS4):**
- "add optional `phase` field to AgentTemplate; phased mode activates agents per phase; backward-compatible legacy mode" → Task 1 (field/helpers) + Task 2 (phased vs legacy launch). ✅
- "SwarmDriver background task that builds HarnessContext, calls try_advance on completion, activates next phase's agents" → Task 3 (`SwarmDriver._tick_team`) + Task 4 (loop). ✅
- "activate the dormant Swarm._broadcaster / _workspace" → Task 2 stores workspace per launch; Task 3 driver feeds `_workspace` into `HarnessContext` and emits `team_phase` via the broadcaster. ✅
- "FAILED agents treated as a gate input, deferred to RecoveryChain; driver doesn't wedge" → Decision §5; `test_driver_does_not_advance_on_failed_agent`; `_tick_team` wrapped in try/except so one team can't stall others. ✅
- Decision §6.1 option a (phase-per-agent activation) honored. Out of scope (correctly absent): the `create_team` agent tool (deferred §8); per-user cost threading (WS3 future work).

**Placeholder scan:** None. Gate-defaulting, activation, and event emission are all fully specified with code.

**Type consistency:** `AgentTemplate.phase`/`TeamTemplate.is_phased`/`.agents_for_phase()` defined in Task 1 and used in Task 2 + Task 3 tests; `Swarm.activate_phase`/`get_approvals`/`_spawn_one` defined in Task 2 and called by `SwarmDriver` in Task 3; `HarnessContext(workspace, registry, approvals)` matches `phases.py`; `team_phase_event`/`EventType.TEAM_PHASE`/`EventBroadcaster.team_phase` defined in Task 3 and consumed by the driver; `_run_swarm_driver_once` defined and tested in Task 4; `runner.try_advance(ctx)`/`.current_phase`/`.is_finished` match `harness.py`; `registry.list_agents()`/`update_state()` match `registry.py`.

**Known limitations (logged, not silently dropped):** a phase gated only by `HumanApprovalGate` blocks until something populates `Swarm.get_approvals(team_id)` — there is no API to do so yet (future work, consistent with the deferred `create_team`/management-write surface). A team whose phase is permanently blocked by an unrecoverable FAILED agent stays parked (no auto-timeout at the team level) — the per-agent `task_timeout`/recovery still applies; team-level timeout is future work.
