"""Tests for SwarmDriver — autonomous phase advancement."""
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


def _finish(registry, agent_ids):
    for aid in agent_ids:
        registry.update_state(aid, SubAgentState.FINISHED)


@pytest.mark.asyncio
async def test_driver_advances_when_phase_agents_finish():
    registry = SubAgentRegistry(InMemoryStore())
    spawner = _FakeSpawner()
    swarm = Swarm(registry=registry, broadcaster=EventBroadcaster(None),
                  spawner=spawner, workspace="/tmp/ws")
    driver = SwarmDriver(swarm=swarm, registry=registry,
                         broadcaster=EventBroadcaster(None), workspace="/tmp/ws")
    team_id = await swarm.launch(_phased_template())

    await driver.tick()                                   # plan agent unfinished -> no advance
    assert swarm.get_harness(team_id).current_phase == "plan"
    assert len(spawner.spawned) == 1

    _finish(registry, swarm.get_team_agents(team_id))     # finish plan
    await driver.tick()                                   # advance -> execute, activate dev
    assert swarm.get_harness(team_id).current_phase == "execute"
    assert len(spawner.spawned) == 2

    _finish(registry, swarm.get_team_agents(team_id))     # finish execute
    await driver.tick()                                   # advance past last -> finished
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

    team_id = await swarm.launch(_phased_template())
    _finish(registry, swarm.get_team_agents(team_id)); await driver.tick()  # -> execute (active)
    _finish(registry, swarm.get_team_agents(team_id)); await driver.tick()  # -> finished (complete)
    await asyncio.wait_for(sub_task, timeout=2.0)

    te = [e for e in events if e.type == "team_phase"]
    assert any(e.data["status"] == "active" and e.data["phase"] == "execute" for e in te)
    assert any(e.data["status"] == "complete" for e in te)


@pytest.mark.asyncio
async def test_driver_does_not_advance_on_failed_agent():
    registry = SubAgentRegistry(InMemoryStore())
    spawner = _FakeSpawner()
    swarm = Swarm(registry=registry, broadcaster=EventBroadcaster(None),
                  spawner=spawner, workspace="/tmp/ws")
    driver = SwarmDriver(swarm=swarm, registry=registry,
                         broadcaster=EventBroadcaster(None), workspace="/tmp/ws")
    team_id = await swarm.launch(_phased_template())
    for aid in swarm.get_team_agents(team_id):
        registry.update_state(aid, SubAgentState.FAILED)
    await driver.tick()
    assert swarm.get_harness(team_id).current_phase == "plan"
    assert swarm.get_harness(team_id).is_finished is False


@pytest.mark.asyncio
async def test_driver_teams_independent():
    """Finishing team A's phase advances A but not B (gate is team-scoped — I1)."""
    registry = SubAgentRegistry(InMemoryStore())
    spawner = _FakeSpawner()
    swarm = Swarm(registry=registry, broadcaster=EventBroadcaster(None),
                  spawner=spawner, workspace="/tmp/ws")
    driver = SwarmDriver(swarm=swarm, registry=registry,
                         broadcaster=EventBroadcaster(None), workspace="/tmp/ws")
    team_a = await swarm.launch(_phased_template())
    team_b = await swarm.launch(_phased_template())

    # Finish ONLY team A's (plan) agents.
    _finish(registry, swarm.get_team_agents(team_a))
    await driver.tick()

    assert swarm.get_harness(team_a).current_phase == "execute"   # A advanced
    assert swarm.get_harness(team_b).current_phase == "plan"      # B did NOT


@pytest.mark.asyncio
async def test_all_tasks_complete_gate_scopes_to_agent_ids():
    from src.swarm.phases import AllTasksCompleteGate, HarnessContext
    from src.subagent.registry import SubAgentRegistry
    from src.subagent.state import AgentInfo, SubAgentState
    from langgraph.store.memory import InMemoryStore
    registry = SubAgentRegistry(InMemoryStore())
    a = AgentInfo(agent_id="a", name="a", role="x", task="t", tier="standard", tools=[], skills=[])
    b = AgentInfo(agent_id="b", name="b", role="x", task="t", tier="standard", tools=[], skills=[])
    registry.register(a, asyncio.create_task(asyncio.sleep(0)))
    registry.register(b, asyncio.create_task(asyncio.sleep(0)))
    registry.update_state("a", SubAgentState.FINISHED)
    gate = AllTasksCompleteGate()
    # Scoped to team A ("a" only) -> passes despite b unfinished
    assert (await gate.check(HarnessContext(workspace="/tmp", registry=registry, agent_ids={"a"}))).passed is True
    # Unscoped (legacy) -> blocks because b is unfinished
    assert (await gate.check(HarnessContext(workspace="/tmp", registry=registry))).passed is False


@pytest.mark.asyncio
async def test_driver_ignores_legacy_team():
    """A non-phased team is not advanced or touched by the driver."""
    registry = SubAgentRegistry(InMemoryStore())
    spawner = _FakeSpawner()
    swarm = Swarm(registry=registry, broadcaster=EventBroadcaster(None),
                  spawner=spawner, workspace="/tmp/ws")
    driver = SwarmDriver(swarm=swarm, registry=registry,
                         broadcaster=EventBroadcaster(None), workspace="/tmp/ws")
    tmpl = TeamTemplate(name="t", goal="g", phases=["plan", "execute"],
                        agents=[AgentTemplate(name="a", role="executor", tier="standard",
                                              task_prompt="x", tools=[], skills=[])])
    team_id = await swarm.launch(tmpl)            # legacy (no phase)
    before = len(spawner.spawned)
    await driver.tick()
    assert swarm.get_harness(team_id).current_phase == "plan"   # untouched
    assert len(spawner.spawned) == before                        # no activation


@pytest.mark.asyncio
async def test_driver_parks_team_on_activation_failure():
    """If activating the next phase fails, the team parks instead of skipping ahead."""
    class _FlakySpawner:
        def __init__(self, fail_after):
            self.n = 0; self.fail_after = fail_after
        async def spawn(self, info, recovery_context=None):
            self.n += 1
            if self.n > self.fail_after:
                raise RuntimeError("spawn failed")
            return asyncio.create_task(asyncio.sleep(0))

    registry = SubAgentRegistry(InMemoryStore())
    spawner = _FlakySpawner(fail_after=1)   # phase[0] ok, phase[1] activation fails
    swarm = Swarm(registry=registry, broadcaster=EventBroadcaster(None),
                  spawner=spawner, workspace="/tmp/ws")
    driver = SwarmDriver(swarm=swarm, registry=registry,
                         broadcaster=EventBroadcaster(None), workspace="/tmp/ws")
    team_id = await swarm.launch(_phased_template())
    _finish(registry, swarm.get_team_agents(team_id))   # finish plan
    await driver.tick()                                  # advance -> activate execute -> FAILS

    assert team_id in driver._errored
    # Parked at execute, not silently skipped to verify/finished on the next tick.
    await driver.tick()
    assert swarm.get_harness(team_id).is_finished is False


@pytest.mark.asyncio
async def test_driver_complete_is_idempotent():
    """Ticking again after completion emits no second complete event and re-spawns nothing."""
    from src.api.websocket import EventHub
    registry = SubAgentRegistry(InMemoryStore())
    spawner = _FakeSpawner()
    hub = EventHub(); bc = EventBroadcaster(hub)
    swarm = Swarm(registry=registry, broadcaster=bc, spawner=spawner, workspace="/tmp/ws")
    driver = SwarmDriver(swarm=swarm, registry=registry, broadcaster=bc, workspace="/tmp/ws")
    team_id = await swarm.launch(_phased_template())
    _finish(registry, swarm.get_team_agents(team_id)); await driver.tick()   # -> execute
    _finish(registry, swarm.get_team_agents(team_id)); await driver.tick()    # -> finished

    events = []
    async def sub():
        async for ev in hub.subscribe():
            events.append(ev)
    sub_task = asyncio.create_task(sub()); await asyncio.sleep(0.05)
    spawned_before = len(spawner.spawned)
    await driver.tick(); await driver.tick()          # extra ticks after completion
    await asyncio.sleep(0.05); sub_task.cancel()
    assert len(spawner.spawned) == spawned_before     # no re-spawn
    assert not [e for e in events if e.type == "team_phase" and e.data.get("status") == "complete"]
