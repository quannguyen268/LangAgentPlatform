# tests/test_api_management.py
"""Test management API routes."""
import pytest
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop
from aiohttp import web
import json


@pytest.fixture
def management_app(tmp_path):
    """Create a test aiohttp app with the Phase 1B memory + cost + dream routes."""
    from src.api.routes import setup_legacy_routes

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "IDENTITY.md").write_text("I am LangAgent.")
    (workspace / "MEMORY.md").write_text("User likes Python.")
    memory_dir = workspace / "memory"
    memory_dir.mkdir()

    from src.observability.cost import CostTracker
    cost_tracker = CostTracker()
    cost_tracker.record("anthropic", "claude-sonnet-4-6", 1000, 500, "user1", "standard")

    app = web.Application()
    setup_legacy_routes(app, workspace=str(workspace), cost_tracker=cost_tracker)
    return app


@pytest.mark.asyncio
async def test_memory_list(management_app, aiohttp_client):
    client = await aiohttp_client(management_app)
    resp = await client.get("/v1/memory")
    assert resp.status == 200
    data = await resp.json()
    assert isinstance(data, list)
    assert any(f["name"] == "IDENTITY.md" for f in data)
    assert any(f["name"] == "MEMORY.md" for f in data)


@pytest.mark.asyncio
async def test_memory_read(management_app, aiohttp_client):
    client = await aiohttp_client(management_app)
    resp = await client.get("/v1/memory/IDENTITY.md")
    assert resp.status == 200
    data = await resp.json()
    assert "I am LangAgent" in data["content"]


@pytest.mark.asyncio
async def test_memory_read_not_found(management_app, aiohttp_client):
    client = await aiohttp_client(management_app)
    resp = await client.get("/v1/memory/NONEXISTENT.md")
    assert resp.status == 404


@pytest.mark.asyncio
async def test_memory_update(management_app, aiohttp_client):
    client = await aiohttp_client(management_app)
    resp = await client.put(
        "/v1/memory/MEMORY.md",
        json={"content": "Updated memory content."},
    )
    assert resp.status == 200
    # Verify it was written
    resp2 = await client.get("/v1/memory/MEMORY.md")
    data = await resp2.json()
    assert data["content"] == "Updated memory content."


@pytest.mark.asyncio
async def test_cost_summary(management_app, aiohttp_client):
    client = await aiohttp_client(management_app)
    resp = await client.get("/v1/cost")
    assert resp.status == 200
    data = await resp.json()
    assert "total_tokens" in data
    assert data["total_tokens"] > 0


@pytest.mark.asyncio
async def test_cost_breakdown(management_app, aiohttp_client):
    client = await aiohttp_client(management_app)
    resp = await client.get("/v1/cost/breakdown")
    assert resp.status == 200
    data = await resp.json()
    assert "by_user" in data
    assert "by_tier" in data


@pytest.mark.asyncio
async def test_cost_breakdown_contract(management_app, aiohttp_client):
    """Spec §4.6 contract test: /v1/cost/breakdown returns {by_user, by_tier, by_agent}."""
    client = await aiohttp_client(management_app)
    resp = await client.get("/v1/cost/breakdown")
    assert resp.status == 200
    data = await resp.json()
    # Pin the documented shape
    assert set(data.keys()) == {"by_user", "by_tier", "by_agent"}
    assert isinstance(data["by_user"], dict)
    assert isinstance(data["by_tier"], dict)
    assert isinstance(data["by_agent"], dict)
