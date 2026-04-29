"""Test the new (Phase 2B-I) management endpoints: agents, teams, tasks, config."""
import asyncio
import pytest
from aiohttp import web
from langgraph.store.memory import InMemoryStore

from src.subagent.registry import SubAgentRegistry
from src.subagent.state import AgentInfo, SubAgentState


def _make_agent_info(agent_id="a1", **overrides):
    info = AgentInfo(
        agent_id=agent_id, name=f"name-{agent_id}", role="executor", task="t",
        tier="standard", tools=["read_file"], skills=[],
    )
    for k, v in overrides.items():
        setattr(info, k, v)
    return info


@pytest.fixture
def make_app():
    """Factory: build an aiohttp app with the management routes mounted.

    Reusable across all 2B-I endpoint tests (agents/teams/tasks/config).
    Each dependency is keyword-only and defaults to None so callers wire
    only what they need.
    """
    from src.api.management import setup_management_routes

    def _make(*, subagent_registry=None, swarm=None, config=None):
        app = web.Application()
        setup_management_routes(
            app, subagent_registry=subagent_registry, swarm=swarm, config=config,
        )
        return app

    return _make


@pytest.fixture
def app_with_registry(make_app):
    """aiohttp app with management routes wired to a populated registry.

    Uses MagicMock for asyncio.Task so the fixture stays sync (the read
    endpoints only inspect AgentInfo, not the task itself).
    """
    from unittest.mock import MagicMock

    registry = SubAgentRegistry(InMemoryStore())
    info1 = _make_agent_info(agent_id="agent-aaa", state=SubAgentState.RUNNING)
    info2 = _make_agent_info(
        agent_id="agent-bbb", state=SubAgentState.FINISHED,
        retry_count=2, error="prior fail",
    )
    registry.register(info1, MagicMock())
    registry.register(info2, MagicMock())
    return make_app(subagent_registry=registry)


@pytest.fixture
def app_no_registry(make_app):
    """aiohttp app with management routes but no registry (subsystem disabled)."""
    return make_app()


@pytest.mark.asyncio
async def test_get_agents_returns_list(app_with_registry, aiohttp_client):
    client = await aiohttp_client(app_with_registry)
    resp = await client.get("/v1/agents")
    assert resp.status == 200
    data = await resp.json()
    assert "agents" in data
    assert isinstance(data["agents"], list)
    assert len(data["agents"]) == 2
    ids = {a["agent_id"] for a in data["agents"]}
    assert ids == {"agent-aaa", "agent-bbb"}
    sample = next(a for a in data["agents"] if a["agent_id"] == "agent-aaa")
    # Spec §4.1 keys + finished_at (added so UIs can compute duration)
    for key in ("agent_id", "name", "role", "tier", "state", "task",
                "tools", "skills", "iteration", "cost_cents",
                "retry_count", "created_at", "last_heartbeat",
                "finished_at"):
        assert key in sample
    assert sample["state"] == "running"
    assert sample["finished_at"] is None  # RUNNING agent has not terminated


@pytest.mark.asyncio
async def test_get_agents_empty_when_registry_disabled(app_no_registry, aiohttp_client):
    """Spec §4.8: subsystem disabled → 200 with empty list."""
    client = await aiohttp_client(app_no_registry)
    resp = await client.get("/v1/agents")
    assert resp.status == 200
    data = await resp.json()
    assert data == {"agents": []}


@pytest.mark.asyncio
async def test_get_agent_by_id_returns_detail(app_with_registry, aiohttp_client):
    client = await aiohttp_client(app_with_registry)
    resp = await client.get("/v1/agents/agent-bbb")
    assert resp.status == 200
    data = await resp.json()
    assert data["agent_id"] == "agent-bbb"
    assert data["state"] == "finished"
    # Spec §4.2: detail response includes 'error' field
    assert data["error"] == "prior fail"


@pytest.mark.asyncio
async def test_get_agent_by_id_returns_404_for_unknown(app_with_registry, aiohttp_client):
    client = await aiohttp_client(app_with_registry)
    resp = await client.get("/v1/agents/agent-ghost")
    assert resp.status == 404
    body = await resp.json()
    assert body["error"]["type"] == "not_found"
    assert body["error"]["code"] == "agent_not_found"


@pytest.mark.asyncio
async def test_get_agent_by_id_404_when_registry_disabled(app_no_registry, aiohttp_client):
    """Spec §4.8: with no registry, GET /v1/agents/{id} → 404 (consistent with 'does not exist')."""
    client = await aiohttp_client(app_no_registry)
    resp = await client.get("/v1/agents/anyid")
    assert resp.status == 404
