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


def _astream_factory(chunks, captured=None):
    """Return a fake ``astream(state, **kwargs)`` yielding the given chunks.

    If ``captured`` is provided, the first message's content is recorded under
    ``captured["content"]`` (used to assert recovery-context prepending).
    """
    def _astream(state, **kwargs):
        if captured is not None:
            captured["content"] = state["messages"][0].content

        async def _gen():
            yield state  # mirror stream_mode="values": input snapshot echoed first
            for c in chunks:
                yield c
        return _gen()
    return _astream


def _astream_raises(exc):
    """Return a fake ``astream`` whose generator raises ``exc`` when iterated."""
    def _astream(state, **kwargs):
        async def _gen():
            raise exc
            yield  # unreachable; makes this an async generator
        return _gen()
    return _astream


def _astream_segments(segments, captured_states=None):
    """Fake astream: call N yields segment N (preceded by the input-state echo).

    Raises IndexError if called more times than there are segments, so an
    unexpected extra segment fails loudly instead of silently yielding nothing.
    """
    calls = {"n": 0}

    def _astream(state, **kwargs):
        idx = calls["n"]
        calls["n"] += 1
        if idx >= len(segments):
            raise IndexError(
                f"_astream_segments: called {idx + 1} times but only "
                f"{len(segments)} segment(s) configured"
            )
        if captured_states is not None:
            captured_states.append(state["messages"])
        chunks = segments[idx]
        async def _gen():
            yield state
            for c in chunks:
                yield c
        return _gen()
    return _astream


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
        streaming=False,
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
        streaming=False,
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
        streaming=False,
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


@pytest.mark.asyncio
async def test_spawner_raises_on_unknown_tool(monkeypatch):
    """Missing tool name is a config bug — FAIL loudly with FAILED state."""
    store = InMemoryStore()
    registry = SubAgentRegistry(store)
    broadcaster = EventBroadcaster(None)

    # create_deep_agent shouldn't even be called if the pre-flight catches
    called = {"count": 0}

    def fake_create(**kwargs):
        called["count"] += 1
        return MagicMock()
    monkeypatch.setattr("src.subagent.spawner.create_deep_agent", fake_create)

    spawner = DeepAgentsSpawner(
        registry=registry, broadcaster=broadcaster,
        base_model=MagicMock(), tools_by_name={"read_file": object()},
        streaming=False,
    )
    info = AgentInfo(
        agent_id="a1", name="n1", role="executor", task="t",
        tier="standard",
        tools=["read_file", "bogus_tool"],  # one known, one unknown
        skills=[],
    )
    registry.register(info, asyncio.create_task(asyncio.sleep(0)))
    task = await spawner.spawn(info)
    registry._tasks["a1"] = task
    await asyncio.wait_for(task, timeout=5.0)

    assert called["count"] == 0, "create_deep_agent must not be called when tools are missing"
    assert registry.get_agent("a1").state == SubAgentState.FAILED
    assert "bogus_tool" in (registry.get_agent("a1").error or "")


@pytest.mark.asyncio
async def test_spawner_prepends_recovery_context(monkeypatch):
    """When recovery_context is provided, it must be prepended to the task."""
    store = InMemoryStore()
    registry = SubAgentRegistry(store)
    broadcaster = EventBroadcaster(None)

    captured = {}

    async def capture_invoke(state):
        captured["content"] = state["messages"][0].content
        return {"messages": [AIMessage(content="ok")]}

    inner = MagicMock()
    inner.ainvoke = capture_invoke
    monkeypatch.setattr("src.subagent.spawner.create_deep_agent", lambda **kw: inner)

    spawner = DeepAgentsSpawner(
        registry=registry, broadcaster=broadcaster,
        base_model=MagicMock(), tools_by_name={},
        streaming=False,
    )
    info = AgentInfo(
        agent_id="a1", name="n1", role="executor", task="the original task",
        tier="standard", tools=[], skills=[],
    )
    registry.register(info, asyncio.create_task(asyncio.sleep(0)))
    task = await spawner.spawn(info, recovery_context="Resuming after failure X")
    registry._tasks["a1"] = task
    await asyncio.wait_for(task, timeout=5.0)

    msg = captured["content"]
    assert "Resuming after failure X" in msg
    assert "Task: the original task" in msg


@pytest.mark.asyncio
async def test_spawner_failed_event_uses_exception_type(monkeypatch):
    """agent_failed reason should be the exception type, not a generic string."""
    store = InMemoryStore()
    registry = SubAgentRegistry(store)
    hub = EventHub()
    broadcaster = EventBroadcaster(hub)

    failed_events = []

    async def sub():
        async for ev in hub.subscribe():
            if ev.type == "agent_failed":
                failed_events.append(ev)
                break

    sub_task = asyncio.create_task(sub())
    await asyncio.sleep(0.05)

    inner = MagicMock()
    inner.ainvoke = AsyncMock(side_effect=ValueError("bad input"))
    monkeypatch.setattr("src.subagent.spawner.create_deep_agent", lambda **kw: inner)

    spawner = DeepAgentsSpawner(
        registry=registry, broadcaster=broadcaster,
        base_model=MagicMock(), tools_by_name={},
        streaming=False,
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

    assert len(failed_events) == 1
    assert failed_events[0].data["reason"] == "ValueError"
    assert failed_events[0].data["action"] == "pending"


@pytest.mark.asyncio
async def test_streaming_increments_iteration_per_chunk(monkeypatch):
    """Streaming path increments AgentInfo.iteration once per stream chunk."""
    store = InMemoryStore()
    registry = SubAgentRegistry(store)
    broadcaster = EventBroadcaster(None)

    inner = MagicMock()
    inner.astream = _astream_factory([
        {"messages": [AIMessage(content="step1")]},
        {"messages": [AIMessage(content="step2")]},
        {"messages": [AIMessage(content="step3")]},
    ])
    monkeypatch.setattr("src.subagent.spawner.create_deep_agent", lambda **kw: inner)

    spawner = DeepAgentsSpawner(
        registry=registry, broadcaster=broadcaster,
        base_model=MagicMock(), tools_by_name={}, streaming=True,
    )
    info = AgentInfo(agent_id="a1", name="n1", role="executor", task="t",
                     tier="standard", tools=[], skills=[])
    registry.register(info, asyncio.create_task(asyncio.sleep(0)))
    task = await spawner.spawn(info)
    registry._tasks["a1"] = task
    await asyncio.wait_for(task, timeout=5.0)

    assert registry.get_agent("a1").iteration == 3
    hb = await registry.agent_store.read_heartbeat("a1")
    assert hb["iteration"] == 3
    result = await registry.agent_store.read_result("a1")
    assert result["status"] == "success"
    assert result["output"] == "step3"
    assert registry.get_agent("a1").state == SubAgentState.FINISHED


@pytest.mark.asyncio
async def test_streaming_emits_progress_per_chunk(monkeypatch):
    """Streaming path emits one agent_progress event per chunk."""
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
    inner.astream = _astream_factory([
        {"messages": [AIMessage(content="alpha")]},
        {"messages": [AIMessage(content="beta")]},
    ])
    monkeypatch.setattr("src.subagent.spawner.create_deep_agent", lambda **kw: inner)

    spawner = DeepAgentsSpawner(
        registry=registry, broadcaster=broadcaster,
        base_model=MagicMock(), tools_by_name={}, streaming=True,
    )
    info = AgentInfo(agent_id="a1", name="n1", role="executor", task="t",
                     tier="standard", tools=[], skills=[])
    registry.register(info, asyncio.create_task(asyncio.sleep(0)))
    task = await spawner.spawn(info)
    registry._tasks["a1"] = task
    await asyncio.wait_for(task, timeout=5.0)
    await asyncio.wait_for(sub_task, timeout=2.0)

    progress = [e for e in events if e.type == "agent_progress"]
    assert len(progress) == 2
    assert progress[0].data["message"] == "alpha"
    assert progress[1].data["message"] == "beta"


@pytest.mark.asyncio
async def test_streaming_honors_shutdown_directive(monkeypatch):
    """A pending shutdown directive ends the loop after the current chunk."""
    store = InMemoryStore()
    registry = SubAgentRegistry(store)
    broadcaster = EventBroadcaster(None)

    inner = MagicMock()
    inner.astream = _astream_factory([
        {"messages": [AIMessage(content="step1")]},
        {"messages": [AIMessage(content="step2")]},
        {"messages": [AIMessage(content="step3")]},
        {"messages": [AIMessage(content="step4")]},
        {"messages": [AIMessage(content="step5")]},
    ])
    monkeypatch.setattr("src.subagent.spawner.create_deep_agent", lambda **kw: inner)

    spawner = DeepAgentsSpawner(
        registry=registry, broadcaster=broadcaster,
        base_model=MagicMock(), tools_by_name={}, streaming=True,
    )
    info = AgentInfo(agent_id="a1", name="n1", role="executor", task="t",
                     tier="standard", tools=[], skills=[])
    registry.register(info, asyncio.create_task(asyncio.sleep(0)))

    # Pre-write the shutdown directive so the first chunk's post-check sees it.
    await registry.agent_store.write_directive("a1", action="shutdown")

    task = await spawner.spawn(info)
    registry._tasks["a1"] = task
    await asyncio.wait_for(task, timeout=5.0)

    assert registry.get_agent("a1").iteration == 1  # broke after chunk 1
    result = await registry.agent_store.read_result("a1")
    assert result["status"] == "stopped"
    assert result["output"] == "step1"
    assert registry.get_agent("a1").state == SubAgentState.FINISHED
    # Directive was consumed
    assert await registry.agent_store.read_directive("a1") is None


@pytest.mark.asyncio
async def test_streaming_inner_failure_marks_failed(monkeypatch):
    """An exception raised mid-stream marks the agent FAILED."""
    store = InMemoryStore()
    registry = SubAgentRegistry(store)
    broadcaster = EventBroadcaster(None)

    inner = MagicMock()
    inner.astream = _astream_raises(RuntimeError("boom"))
    monkeypatch.setattr("src.subagent.spawner.create_deep_agent", lambda **kw: inner)

    spawner = DeepAgentsSpawner(
        registry=registry, broadcaster=broadcaster,
        base_model=MagicMock(), tools_by_name={}, streaming=True,
    )
    info = AgentInfo(agent_id="a1", name="n1", role="executor", task="t",
                     tier="standard", tools=[], skills=[])
    registry.register(info, asyncio.create_task(asyncio.sleep(0)))
    task = await spawner.spawn(info)
    registry._tasks["a1"] = task
    await asyncio.wait_for(task, timeout=5.0)

    assert registry.get_agent("a1").state == SubAgentState.FAILED
    assert "boom" in (registry.get_agent("a1").error or "")


@pytest.mark.asyncio
async def test_streaming_prepends_recovery_context(monkeypatch):
    """Recovery context is prepended to the task in the streaming path too."""
    store = InMemoryStore()
    registry = SubAgentRegistry(store)
    broadcaster = EventBroadcaster(None)
    captured = {}

    inner = MagicMock()
    inner.astream = _astream_factory(
        [{"messages": [AIMessage(content="ok")]}], captured=captured,
    )
    monkeypatch.setattr("src.subagent.spawner.create_deep_agent", lambda **kw: inner)

    spawner = DeepAgentsSpawner(
        registry=registry, broadcaster=broadcaster,
        base_model=MagicMock(), tools_by_name={}, streaming=True,
    )
    info = AgentInfo(agent_id="a1", name="n1", role="executor", task="the original task",
                     tier="standard", tools=[], skills=[])
    registry.register(info, asyncio.create_task(asyncio.sleep(0)))
    task = await spawner.spawn(info, recovery_context="Resuming after failure X")
    registry._tasks["a1"] = task
    await asyncio.wait_for(task, timeout=5.0)

    assert "Resuming after failure X" in captured["content"]
    assert "Task: the original task" in captured["content"]


@pytest.mark.asyncio
async def test_streaming_empty_stream_fails(monkeypatch):
    """A stream that yields no chunks fails loudly rather than reporting empty success."""
    store = InMemoryStore()
    registry = SubAgentRegistry(store)
    broadcaster = EventBroadcaster(None)

    inner = MagicMock()
    inner.astream = _astream_factory([])  # zero chunks
    monkeypatch.setattr("src.subagent.spawner.create_deep_agent", lambda **kw: inner)

    spawner = DeepAgentsSpawner(
        registry=registry, broadcaster=broadcaster,
        base_model=MagicMock(), tools_by_name={}, streaming=True,
    )
    info = AgentInfo(agent_id="a1", name="n1", role="executor", task="t",
                     tier="standard", tools=[], skills=[])
    registry.register(info, asyncio.create_task(asyncio.sleep(0)))
    task = await spawner.spawn(info)
    registry._tasks["a1"] = task
    await asyncio.wait_for(task, timeout=5.0)

    assert registry.get_agent("a1").state == SubAgentState.FAILED
    assert "no steps" in (registry.get_agent("a1").error or "")


def test_build_inner_passes_backend_and_skills(monkeypatch):
    """_build_inner wires backend + skills into create_deep_agent when configured."""
    from src.subagent.spawner import DeepAgentsSpawner
    from src.subagent.state import AgentInfo
    from src.subagent.registry import SubAgentRegistry
    from src.subagent.broadcaster import EventBroadcaster
    from langgraph.store.memory import InMemoryStore

    captured = {}
    monkeypatch.setattr(
        "src.subagent.spawner.create_deep_agent",
        lambda **kw: captured.update(kw) or MagicMock(),
    )
    spawner = DeepAgentsSpawner(
        registry=SubAgentRegistry(InMemoryStore()), broadcaster=EventBroadcaster(None),
        base_model=MagicMock(), tools_by_name={"read_file": object()},
        workspace="/tmp/ws", skills_dirs=["skills"],
    )
    info = AgentInfo(agent_id="a1", name="n", role="executor", task="t",
                     tier="standard", tools=["read_file"], skills=[])
    spawner._build_inner(info)

    assert "backend" in captured           # FilesystemBackend wired
    assert captured.get("skills") == ["skills"]
    assert len(captured["tools"]) == 1


def test_build_inner_omits_backend_when_no_workspace(monkeypatch):
    """No workspace -> no backend; no skills_dirs -> no skills (both gated independently)."""
    from src.subagent.spawner import DeepAgentsSpawner
    from src.subagent.state import AgentInfo
    from src.subagent.registry import SubAgentRegistry
    from src.subagent.broadcaster import EventBroadcaster
    from langgraph.store.memory import InMemoryStore

    captured = {}
    monkeypatch.setattr(
        "src.subagent.spawner.create_deep_agent",
        lambda **kw: captured.update(kw) or MagicMock(),
    )
    spawner = DeepAgentsSpawner(
        registry=SubAgentRegistry(InMemoryStore()), broadcaster=EventBroadcaster(None),
        base_model=MagicMock(), tools_by_name={},
    )
    info = AgentInfo(agent_id="a1", name="n", role="executor", task="t",
                     tier="standard", tools=[], skills=[])
    spawner._build_inner(info)

    assert "backend" not in captured
    assert "skills" not in captured


def test_build_inner_skills_without_workspace(monkeypatch):
    """skills_dirs are passed even when workspace is None (independent gating)."""
    from src.subagent.spawner import DeepAgentsSpawner
    from src.subagent.state import AgentInfo
    from src.subagent.registry import SubAgentRegistry
    from src.subagent.broadcaster import EventBroadcaster
    from langgraph.store.memory import InMemoryStore

    captured = {}
    monkeypatch.setattr(
        "src.subagent.spawner.create_deep_agent",
        lambda **kw: captured.update(kw) or MagicMock(),
    )
    spawner = DeepAgentsSpawner(
        registry=SubAgentRegistry(InMemoryStore()), broadcaster=EventBroadcaster(None),
        base_model=MagicMock(), tools_by_name={}, skills_dirs=["skills"],
    )
    info = AgentInfo(agent_id="a1", name="n", role="executor", task="t",
                     tier="standard", tools=[], skills=[])
    spawner._build_inner(info)

    assert "backend" not in captured
    assert captured["skills"] == ["skills"]


@pytest.mark.asyncio
async def test_spawn_sets_active_tier(monkeypatch):
    """The sub-agent sets its tier on its own task at spawn."""
    import src.tools.model_router as mr
    store = InMemoryStore()
    registry = SubAgentRegistry(store)
    broadcaster = EventBroadcaster(None)

    seen = {}
    inner = MagicMock()

    def _astream(state, **kwargs):
        seen["tier"] = mr._active_tier.get()
        async def _gen():
            yield state
            yield {"messages": [AIMessage(content="done")]}
        return _gen()
    inner.astream = _astream
    monkeypatch.setattr("src.subagent.spawner.create_deep_agent", lambda **kw: inner)

    spawner = DeepAgentsSpawner(
        registry=registry, broadcaster=broadcaster,
        base_model=MagicMock(), tools_by_name={}, streaming=True,
    )
    info = AgentInfo(agent_id="a1", name="n", role="executor", task="t",
                     tier="advanced", tools=[], skills=[])
    registry.register(info, asyncio.create_task(asyncio.sleep(0)))
    task = await spawner.spawn(info)
    registry._tasks["a1"] = task
    await asyncio.wait_for(task, timeout=5.0)

    assert seen["tier"] == "advanced"


@pytest.mark.asyncio
async def test_streaming_prepends_skills_hint(monkeypatch):
    """info.skills produces a 'Prioritize these skills' hint at the top of the task message."""
    store = InMemoryStore()
    registry = SubAgentRegistry(store)
    broadcaster = EventBroadcaster(None)
    captured = {}

    inner = MagicMock()
    inner.astream = _astream_factory([{"messages": [AIMessage(content="ok")]}], captured=captured)
    monkeypatch.setattr("src.subagent.spawner.create_deep_agent", lambda **kw: inner)

    spawner = DeepAgentsSpawner(
        registry=registry, broadcaster=broadcaster,
        base_model=MagicMock(), tools_by_name={}, streaming=True,
    )
    info = AgentInfo(agent_id="a1", name="n", role="executor", task="the task",
                     tier="standard", tools=[], skills=["code_review"])
    registry.register(info, asyncio.create_task(asyncio.sleep(0)))
    task = await spawner.spawn(info)
    registry._tasks["a1"] = task
    await asyncio.wait_for(task, timeout=5.0)

    assert captured["content"].startswith("Prioritize these skills for this work: code_review.")
    assert "the task" in captured["content"]


@pytest.mark.asyncio
async def test_assign_task_runs_another_segment(monkeypatch):
    """A task in the inbox is consumed after the current segment, running another."""
    store = InMemoryStore()
    registry = SubAgentRegistry(store)
    broadcaster = EventBroadcaster(None)

    inner = MagicMock()
    captured_states = []
    inner.astream = _astream_segments([
        [{"messages": [AIMessage(content="seg1-done")]}],
        [{"messages": [AIMessage(content="seg2-done")]}],
    ], captured_states=captured_states)
    monkeypatch.setattr("src.subagent.spawner.create_deep_agent", lambda **kw: inner)

    spawner = DeepAgentsSpawner(
        registry=registry, broadcaster=broadcaster,
        base_model=MagicMock(), tools_by_name={}, streaming=True,
    )
    info = AgentInfo(agent_id="a1", name="n", role="executor", task="t",
                     tier="standard", tools=[], skills=[])
    registry.register(info, asyncio.create_task(asyncio.sleep(0)))

    # Queue a follow-up task BEFORE running so segment 1's boundary drains it.
    await registry.agent_store.send_inbox("a1", sender="master", message="do more")

    task = await spawner.spawn(info)
    registry._tasks["a1"] = task
    await asyncio.wait_for(task, timeout=5.0)

    result = await registry.agent_store.read_result("a1")
    assert result["status"] == "success"
    assert result["output"] == "seg2-done"   # ran the second segment
    assert await registry.agent_store.drain_inbox("a1") == []

    # Segment 2's input must include the queued follow-up task.
    from langchain_core.messages import HumanMessage as _HM
    seg2_human = [m for m in captured_states[1] if isinstance(m, _HM)]
    assert any("do more" in m.content for m in seg2_human)


@pytest.mark.asyncio
async def test_no_inbox_finishes_after_one_segment(monkeypatch):
    """With an empty inbox, the agent finishes after one segment."""
    store = InMemoryStore()
    registry = SubAgentRegistry(store)
    broadcaster = EventBroadcaster(None)

    inner = MagicMock()
    inner.astream = _astream_segments([[{"messages": [AIMessage(content="only")]}]])
    monkeypatch.setattr("src.subagent.spawner.create_deep_agent", lambda **kw: inner)

    spawner = DeepAgentsSpawner(
        registry=registry, broadcaster=broadcaster,
        base_model=MagicMock(), tools_by_name={}, streaming=True,
    )
    info = AgentInfo(agent_id="a1", name="n", role="executor", task="t",
                     tier="standard", tools=[], skills=[])
    registry.register(info, asyncio.create_task(asyncio.sleep(0)))
    task = await spawner.spawn(info)
    registry._tasks["a1"] = task
    await asyncio.wait_for(task, timeout=5.0)

    result = await registry.agent_store.read_result("a1")
    assert result["output"] == "only"
    assert registry.get_agent("a1").state == SubAgentState.FINISHED


@pytest.mark.asyncio
async def test_change_tier_directive_applies_live(monkeypatch):
    """A change_tier directive switches the active tier mid-segment."""
    import src.tools.model_router as mr
    store = InMemoryStore()
    registry = SubAgentRegistry(store)
    broadcaster = EventBroadcaster(None)

    seen_tiers = []
    inner = MagicMock()

    def _astream(state, **kwargs):
        async def _gen():
            yield state
            seen_tiers.append(mr._active_tier.get())          # before directive
            yield {"messages": [AIMessage(content="s1")]}
            seen_tiers.append(mr._active_tier.get())          # after directive applied
            yield {"messages": [AIMessage(content="s2")]}
        return _gen()
    inner.astream = _astream
    monkeypatch.setattr("src.subagent.spawner.create_deep_agent", lambda **kw: inner)

    spawner = DeepAgentsSpawner(
        registry=registry, broadcaster=broadcaster,
        base_model=MagicMock(), tools_by_name={}, streaming=True,
    )
    info = AgentInfo(agent_id="a1", name="n", role="executor", task="t",
                     tier="standard", tools=[], skills=[])
    registry.register(info, asyncio.create_task(asyncio.sleep(0)))
    await registry.agent_store.write_directive("a1", action="change_tier", params={"tier": "expert"})

    task = await spawner.spawn(info)
    registry._tasks["a1"] = task
    await asyncio.wait_for(task, timeout=5.0)

    assert seen_tiers[0] == "standard"   # initial
    assert seen_tiers[1] == "expert"     # changed after first chunk's directive check
    assert await registry.agent_store.read_directive("a1") is None  # consumed
