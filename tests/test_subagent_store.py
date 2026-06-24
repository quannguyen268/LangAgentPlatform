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
