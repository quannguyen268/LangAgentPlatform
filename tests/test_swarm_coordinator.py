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


def _make_swarm():
    registry = SubAgentRegistry(InMemoryStore())
    broadcaster = EventBroadcaster(None)
    spawner = MagicMock()

    async def spawn_stub(info, recovery_context=None):
        async def noop():
            await asyncio.sleep(0.01)
        return asyncio.create_task(noop())

    spawner.spawn = AsyncMock(side_effect=spawn_stub)
    swarm = Swarm(registry=registry, broadcaster=broadcaster,
                  spawner=spawner, workspace="/tmp")
    return swarm, registry, spawner


@pytest.mark.asyncio
async def test_launch_rejects_unknown_gate_before_spawning():
    """Gate validation must happen BEFORE any spawn so a typo can't leave
    half-launched teams behind."""
    from src.swarm.phases import HumanApprovalGate
    swarm, registry, spawner = _make_swarm()

    with pytest.raises(ValueError, match="unknown phases"):
        await swarm.launch(
            _make_template(),
            gates={"paln": HumanApprovalGate(key="x")},  # typo
        )

    spawner.spawn.assert_not_awaited()
    assert registry.list_agents() == []


@pytest.mark.asyncio
async def test_launch_rolls_back_on_partial_failure():
    """If spawner.spawn fails on the 2nd agent, the 1st must be deregistered."""
    registry = SubAgentRegistry(InMemoryStore())
    broadcaster = EventBroadcaster(None)
    spawner = MagicMock()

    call = {"n": 0}

    async def spawn_stub(info, recovery_context=None):
        call["n"] += 1
        if call["n"] == 2:
            raise RuntimeError("spawn boom on #2")

        async def noop():
            await asyncio.sleep(0.01)
        return asyncio.create_task(noop())

    spawner.spawn = AsyncMock(side_effect=spawn_stub)
    swarm = Swarm(registry=registry, broadcaster=broadcaster,
                  spawner=spawner, workspace="/tmp")

    with pytest.raises(RuntimeError, match="spawn boom"):
        await swarm.launch(_make_template())

    # Rollback: first agent deregistered, no harness recorded
    assert registry.list_agents() == []
    assert swarm.get_harness("team-any") is None


@pytest.mark.asyncio
async def test_get_harness_returns_none_for_unknown():
    swarm, _, _ = _make_swarm()
    assert swarm.get_harness("team-ghost") is None


@pytest.mark.asyncio
async def test_two_launches_produce_distinct_team_ids():
    swarm, _, _ = _make_swarm()
    t1 = await swarm.launch(_make_template())
    t2 = await swarm.launch(_make_template())
    assert t1 != t2
    assert swarm.get_harness(t1) is not None
    assert swarm.get_harness(t2) is not None


@pytest.mark.asyncio
async def test_launch_records_team_agents_mapping():
    """After launch, swarm.get_team_agents(team_id) returns the launched agent_ids."""
    swarm, registry, spawner = _make_swarm()
    tmpl = _make_template()

    team_id = await swarm.launch(tmpl)

    agent_ids = swarm.get_team_agents(team_id)
    assert isinstance(agent_ids, list)
    assert len(agent_ids) == len(tmpl.agents)
    # Each ID must correspond to a registered agent
    for aid in agent_ids:
        assert registry.get_agent(aid) is not None


@pytest.mark.asyncio
async def test_get_team_agents_returns_empty_list_for_unknown():
    swarm, _, _ = _make_swarm()
    assert swarm.get_team_agents("team-ghost") == []


@pytest.mark.asyncio
async def test_rollback_clears_team_agents_mapping():
    """Failed launch must not leave a partial _team_agents entry behind."""
    registry = SubAgentRegistry(InMemoryStore())
    broadcaster = EventBroadcaster(None)
    spawner = MagicMock()
    call = {"n": 0}

    async def spawn_stub(info, recovery_context=None):
        call["n"] += 1
        if call["n"] == 2:
            raise RuntimeError("spawn boom")
        async def noop():
            await asyncio.sleep(0.01)
        return asyncio.create_task(noop())

    spawner.spawn = AsyncMock(side_effect=spawn_stub)
    swarm = Swarm(registry=registry, broadcaster=broadcaster,
                  spawner=spawner, workspace="/tmp")

    with pytest.raises(RuntimeError):
        await swarm.launch(_make_template())

    # No team_id was returned, so nothing should be in _team_agents
    assert swarm._team_agents == {}
    assert swarm._team_templates == {}
    assert swarm._team_goals == {}
    assert swarm._team_approvals == {}


# ---------------------------------------------------------------------------
# WS4 Task 2: phase-aware launch + activate_phase
# ---------------------------------------------------------------------------

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
    assert len(spawner.spawned) == 2
    assert len(swarm.get_team_agents(team_id)) == 2


@pytest.mark.asyncio
async def test_phased_launch_defaults_gate_for_agent_phases():
    from src.swarm.phases import HarnessContext
    registry = SubAgentRegistry(InMemoryStore())
    spawner = _FakeSpawner()
    swarm = Swarm(registry=registry, broadcaster=EventBroadcaster(None),
                  spawner=spawner, workspace="/tmp/ws")
    team_id = await swarm.launch(_phased_template())
    runner = swarm.get_harness(team_id)
    ctx = HarnessContext(workspace="/tmp/ws", registry=registry)
    advanced = await runner.try_advance(ctx)   # plan agent unfinished → blocked
    assert advanced is False
    assert runner.current_phase == "plan"


@pytest.mark.asyncio
async def test_legacy_launch_spawns_all_at_once():
    registry = SubAgentRegistry(InMemoryStore())
    spawner = _FakeSpawner()
    swarm = Swarm(registry=registry, broadcaster=EventBroadcaster(None),
                  spawner=spawner, workspace="/tmp/ws")
    tmpl = TeamTemplate(name="t", goal="g", phases=["plan", "execute"],
                        agents=[AgentTemplate(name="a", role="executor", tier="standard",
                                              task_prompt="x", tools=[], skills=[]),
                                AgentTemplate(name="b", role="executor", tier="standard",
                                              task_prompt="y", tools=[], skills=[])])
    team_id = await swarm.launch(tmpl)
    assert len(spawner.spawned) == 2
    assert len(swarm.get_team_agents(team_id)) == 2


@pytest.mark.asyncio
async def test_activate_phase_unknown_team_raises():
    registry = SubAgentRegistry(InMemoryStore())
    swarm = Swarm(registry=registry, broadcaster=EventBroadcaster(None),
                  spawner=_FakeSpawner(), workspace="/tmp/ws")
    with pytest.raises(ValueError):
        await swarm.activate_phase("no-such-team", "plan")
