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
