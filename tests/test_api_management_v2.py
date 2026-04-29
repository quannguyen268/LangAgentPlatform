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


async def _make_swarm_with_team():
    """Build a Swarm that has launched one 2-agent team. Async helper, not a fixture."""
    from src.subagent.broadcaster import EventBroadcaster
    from src.swarm.coordinator import Swarm
    from src.swarm.templates import TeamTemplate, AgentTemplate
    from unittest.mock import AsyncMock, MagicMock

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

    tmpl = TeamTemplate(
        name="t", goal="g", phases=["plan", "execute"],
        agents=[
            AgentTemplate(name="a1", role="planner", tier="standard",
                          tools=[], skills=[], task_prompt="Plan"),
            AgentTemplate(name="a2", role="executor", tier="standard",
                          tools=[], skills=[], task_prompt="Execute"),
        ],
    )
    team_id = await swarm.launch(tmpl)
    return registry, swarm, team_id


@pytest.mark.asyncio
async def test_get_teams_returns_launched_teams(make_app, aiohttp_client):
    registry, swarm, team_id = await _make_swarm_with_team()
    app = make_app(subagent_registry=registry, swarm=swarm)
    client = await aiohttp_client(app)

    resp = await client.get("/v1/teams")
    assert resp.status == 200
    data = await resp.json()
    assert "teams" in data
    assert len(data["teams"]) == 1
    team = data["teams"][0]
    for key in ("team_id", "phases", "current_phase", "is_finished",
                "agent_count", "agent_ids"):
        assert key in team
    assert team["team_id"] == team_id
    assert team["phases"] == ["plan", "execute"]
    assert team["is_finished"] is False
    assert team["current_phase"] == "plan"
    assert team["agent_count"] == 2
    assert len(team["agent_ids"]) == 2


@pytest.mark.asyncio
async def test_get_teams_empty_when_swarm_disabled(app_no_registry, aiohttp_client):
    client = await aiohttp_client(app_no_registry)
    resp = await client.get("/v1/teams")
    assert resp.status == 200
    assert await resp.json() == {"teams": []}


@pytest.mark.asyncio
async def test_get_teams_after_all_phases_finished(make_app, aiohttp_client):
    """Pin the post-finish JSON shape: current_phase is null, is_finished is True."""
    from src.swarm.phases import HarnessContext
    registry, swarm, team_id = await _make_swarm_with_team()

    runner = swarm.get_harness(team_id)
    ctx = HarnessContext(workspace="/tmp", registry=registry, approvals=set())
    # No gates configured → every try_advance succeeds.
    while not runner.is_finished:
        await runner.try_advance(ctx)

    app = make_app(subagent_registry=registry, swarm=swarm)
    client = await aiohttp_client(app)
    resp = await client.get("/v1/teams")
    assert resp.status == 200
    team = (await resp.json())["teams"][0]
    assert team["is_finished"] is True
    assert team["current_phase"] is None


@pytest.mark.asyncio
async def test_get_teams_lists_multiple_distinct_teams(make_app, aiohttp_client):
    """Two launches must produce two entries with disjoint agent_ids."""
    registry1, swarm, team_id1 = await _make_swarm_with_team()
    # Launch a second team on the same swarm — distinct team_id, distinct agents.
    from src.swarm.templates import TeamTemplate, AgentTemplate
    tmpl = TeamTemplate(
        name="t2", goal="g2", phases=["plan"],
        agents=[
            AgentTemplate(name="b1", role="planner", tier="standard",
                          tools=[], skills=[], task_prompt="P2"),
        ],
    )
    team_id2 = await swarm.launch(tmpl)

    app = make_app(subagent_registry=registry1, swarm=swarm)
    client = await aiohttp_client(app)
    resp = await client.get("/v1/teams")
    assert resp.status == 200
    teams = (await resp.json())["teams"]
    assert len(teams) == 2
    by_id = {t["team_id"]: t for t in teams}
    assert team_id1 in by_id and team_id2 in by_id
    # Agent IDs disjoint
    set1 = set(by_id[team_id1]["agent_ids"])
    set2 = set(by_id[team_id2]["agent_ids"])
    assert set1.isdisjoint(set2)


@pytest.mark.asyncio
async def test_get_teams_returns_internal_error_envelope_on_exception(make_app, aiohttp_client):
    """Inject a swarm whose iter_teams() raises; assert 500 envelope shape."""
    from unittest.mock import MagicMock
    swarm = MagicMock()
    swarm.iter_teams.side_effect = RuntimeError("boom")

    app = make_app(swarm=swarm)
    client = await aiohttp_client(app)
    resp = await client.get("/v1/teams")
    assert resp.status == 500
    body = await resp.json()
    assert body["error"]["type"] == "internal_error"
    assert body["error"]["message"] == "Failed to list teams"


@pytest.fixture
def app_with_tasks(tmp_path, monkeypatch, make_app):
    """aiohttp app with cron module pointed at a tmp tasks file holding one task."""
    from src.tools import cron
    import json as json_mod

    data_file = tmp_path / "tasks.json"
    data_file.write_text(json_mod.dumps([
        {
            "id": "t-1",
            "prompt": "Daily check",
            "type": "cron",
            "value": "0 9 * * *",
            "channel": "telegram",
            "chat_id": "100",
            "created_at": "2026-04-20T11:23:00+00:00",
            "last_run": None,
            "active": True,
            "model_tier": "standard",
        }
    ]))
    monkeypatch.setattr(cron, "_data_file", str(data_file))
    monkeypatch.setattr(cron, "_tasks_lock", asyncio.Lock())
    return make_app()


@pytest.mark.asyncio
async def test_get_tasks_returns_active_tasks(app_with_tasks, aiohttp_client):
    client = await aiohttp_client(app_with_tasks)
    resp = await client.get("/v1/tasks")
    assert resp.status == 200
    data = await resp.json()
    assert "tasks" in data
    assert len(data["tasks"]) == 1
    t = data["tasks"][0]
    for key in ("task_id", "prompt", "schedule_type", "schedule_value",
                "model_tier", "next_run", "created_at"):
        assert key in t
    assert t["task_id"] == "t-1"
    assert t["schedule_type"] == "cron"


@pytest.mark.asyncio
async def test_get_tasks_empty_when_data_file_missing(tmp_path, monkeypatch, make_app, aiohttp_client):
    """Spec §4.8: missing scheduler data → 200 with empty list."""
    from src.tools import cron
    monkeypatch.setattr(cron, "_data_file", str(tmp_path / "does-not-exist.json"))
    monkeypatch.setattr(cron, "_tasks_lock", asyncio.Lock())

    app = make_app()
    client = await aiohttp_client(app)

    resp = await client.get("/v1/tasks")
    assert resp.status == 200
    assert await resp.json() == {"tasks": []}


@pytest.mark.asyncio
async def test_get_tasks_empty_when_cron_not_initialized(monkeypatch, make_app, aiohttp_client):
    """Spec §4.8: cron tools not initialized (lock is None) → 200 with empty list.

    This is the actual disabled-subsystem path; the data-file-missing test only
    covers the happy path with no rows.
    """
    from src.tools import cron
    monkeypatch.setattr(cron, "_tasks_lock", None)

    app = make_app()
    client = await aiohttp_client(app)
    resp = await client.get("/v1/tasks")
    assert resp.status == 200
    assert await resp.json() == {"tasks": []}


@pytest.mark.asyncio
async def test_get_tasks_excludes_inactive_at_api_layer(tmp_path, monkeypatch, make_app, aiohttp_client):
    """Pin the active-only contract at the API surface (cron unit tests cover internals)."""
    from src.tools import cron
    import json as json_mod

    data_file = tmp_path / "tasks.json"
    data_file.write_text(json_mod.dumps([
        {"id": "active-1", "prompt": "p", "type": "cron", "value": "* * * * *",
         "channel": None, "chat_id": None, "created_at": "2026-04-20T00:00:00+00:00",
         "last_run": None, "active": True},
        {"id": "inactive-1", "prompt": "p", "type": "cron", "value": "* * * * *",
         "channel": None, "chat_id": None, "created_at": "2026-04-20T00:00:00+00:00",
         "last_run": None, "active": False},
    ]))
    monkeypatch.setattr(cron, "_data_file", str(data_file))
    monkeypatch.setattr(cron, "_tasks_lock", asyncio.Lock())

    app = make_app()
    client = await aiohttp_client(app)
    resp = await client.get("/v1/tasks")
    data = await resp.json()
    ids = [t["task_id"] for t in data["tasks"]]
    assert ids == ["active-1"]


@pytest.mark.asyncio
async def test_get_tasks_returns_internal_error_on_unexpected_exception(
    monkeypatch, make_app, aiohttp_client,
):
    """Non-init RuntimeError (or any other exception) must NOT be swallowed —
    surface as a 500 error envelope so operators see real bugs."""
    from src.tools import cron

    async def boom():
        raise RuntimeError("malformed cron expression")

    monkeypatch.setattr(cron, "_tasks_lock", asyncio.Lock())
    monkeypatch.setattr(cron, "list_active_tasks_structured", boom)

    app = make_app()
    client = await aiohttp_client(app)
    resp = await client.get("/v1/tasks")
    assert resp.status == 500
    body = await resp.json()
    assert body["error"]["type"] == "internal_error"
    assert body["error"]["message"] == "Failed to list scheduled tasks"


@pytest.mark.asyncio
async def test_get_tasks_next_run_type_is_str_or_null(app_with_tasks, aiohttp_client):
    """`next_run` must be a string or null in the JSON response."""
    client = await aiohttp_client(app_with_tasks)
    resp = await client.get("/v1/tasks")
    data = await resp.json()
    for t in data["tasks"]:
        assert t["next_run"] is None or isinstance(t["next_run"], str)


@pytest.fixture
def app_with_config(make_app):
    """aiohttp app with management routes + an AppConfig instance."""
    from src.config import AppConfig

    cfg = AppConfig()
    cfg.provider.api_key = "sk-secret-must-not-leak"
    return make_app(config=cfg)


@pytest.mark.asyncio
async def test_get_config_returns_redacted_dump(app_with_config, aiohttp_client):
    client = await aiohttp_client(app_with_config)
    resp = await client.get("/v1/config")
    assert resp.status == 200
    data = await resp.json()
    assert "provider" in data
    assert "agent" in data
    assert "subagent" in data
    assert data["provider"]["api_key"] == "***REDACTED***"
    assert "sk-secret" not in str(data)


@pytest.mark.asyncio
async def test_get_config_503_when_config_not_wired(app_no_registry, aiohttp_client):
    """When setup_management_routes received config=None, the endpoint surfaces a 503."""
    client = await aiohttp_client(app_no_registry)
    resp = await client.get("/v1/config")
    assert resp.status == 503
    body = await resp.json()
    assert body["error"]["type"] == "internal_error"
