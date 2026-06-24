# WS2 — Runtime Tool / Skill / Tier Subscription Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the master agent change a *running* sub-agent's tools, skills, tier, and tasks, so `subscribe_tool` / `unsubscribe_tool` / `subscribe_skill` / `assign_task` / `switch_agent_model` take effect instead of being inert.

**Architecture:** WS1 made the spawner stream a sub-agent in one segment (`_stream_run` over `inner.astream`). WS2 wraps that in an **outer segment loop**: after each run completes (a guaranteed-clean boundary — no pending tool calls), the loop drains the sub-agent's `inbox`, applies any tool/skill changes by **rebuilding** the inner DeepAgents instance with the carried-forward message history, and runs another segment if there is new work. **Tier** changes need no rebuild — sub-agents already run on the `RoutingChatModel`, so the loop just calls `set_active_tier(...)` inside the sub-agent's asyncio task (picked up on the next model call). **Skills** use "all-available + hint": sub-agents get a `FilesystemBackend` + `skills=["skills"]` (all skills discoverable, progressively loaded), and `subscribe_skill` records the name and injects a prompt hint.

**Tech Stack:** Python 3.13, deepagents 0.6.1 (`create_deep_agent`, `FilesystemBackend`), LangGraph `BaseStore`, the existing `RoutingChatModel` + `set_active_tier` (`src/tools/model_router.py`), pytest + pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-06-23-orchestration-completion-scope.md` §4 WS2, §6.1–6.2. Depends on WS1 (merged streaming loop).

### Design decisions (resolved with the user)
1. **Reconfigure granularity = segment boundary.** Changes apply after the current run completes, then the loop continues if there's new work. A change mid-long-run waits for that run to finish. Guaranteed-clean (no orphaned `tool_call`/`tool_result`).
2. **Skills = all-available + hint.** No per-name gating (DeepAgents discovers skills by scanning a dir; there is no load-by-name). `subscribe_skill` updates `info.skills` and injects "Prioritize these skills: …" as a prompt hint; progressive loading means unused skills cost ~nothing.
3. **Tier = ContextVar, no rebuild.** `set_active_tier(info.tier)` at spawn; `change_tier` directive applies via `set_active_tier` at the next chunk. Only effective when the model router is configured; otherwise a harmless no-op.
4. **Tools = rebuild.** Tools are compiled into the graph, so `subscribe_tool`/`unsubscribe_tool` mutate `info.tools` and the *next segment* rebuilds with them. A newly subscribed tool is used when the agent next has work (typically via `assign_task`).
5. **assign_task semantics.** Reaches an agent that is still running (mid-segment); the task is picked up when the current segment completes. Once an agent goes idle with an empty inbox it finishes — assigning to a finished agent is out of scope (would need a persistent-worker mode; noted as future work).

---

## File Structure

| File | Responsibility | Change |
|------|----------------|--------|
| `src/subagent/spawner.py` | Sub-agent execution: backend/skills/tier-aware build + outer segment loop | Modify — add `workspace`/`skills_dirs` ctor args, `_build_inner`, `_skills_hint`, set tier at spawn, outer loop + inbox drain + `change_tier` handling |
| `src/subagent/tools.py` | Orchestration tools | Modify — add `subscribe_tool`, `unsubscribe_tool`, `subscribe_skill`; add `known_tools` to `init_orchestration_tools` for validation |
| `src/agent.py` | `create_agent` wiring | Modify — pass `workspace`/`skills_dirs` to spawner, `known_tools` to `init_orchestration_tools`, add the 3 tools to `custom_tools` |
| `tests/test_spawner.py` | Spawner tests | Modify — extend the `_astream_factory` helper for multi-segment; add backend/skills/tier + segment-loop tests |
| `tests/test_subagent_tools.py` | Orchestration tool tests | Modify — add subscribe/unsubscribe/skill tests |

---

## Task 1: Backend + skills + per-task tier; extract `_build_inner`

Give sub-agents a filesystem backend and the shared skills source, set their tier inside their own asyncio task, and route all inner-agent construction through one `_build_inner` helper. Behavior for existing tests is preserved (mocks ignore the new kwargs).

**Files:**
- Modify: `src/subagent/spawner.py`
- Test: `tests/test_spawner.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_spawner.py`:

```python
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
    """With no workspace, _build_inner does not pass a backend or skills."""
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
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_spawner.py -k "build_inner or active_tier" -v`
Expected: FAIL — `DeepAgentsSpawner.__init__` has no `workspace`/`skills_dirs`; `_build_inner` doesn't exist; tier not set.

- [ ] **Step 3: Implement the constructor args, `_build_inner`, `_skills_hint`, and tier-at-spawn**

In `src/subagent/spawner.py`:

(a) Add imports:
```python
from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from langchain_core.messages import AIMessage, HumanMessage

from ..tools.model_router import set_active_tier
from .broadcaster import EventBroadcaster
from .registry import SubAgentRegistry
from .state import AgentInfo, SubAgentState
```

(b) Extend `__init__`:
```python
    def __init__(
        self,
        registry: SubAgentRegistry,
        broadcaster: EventBroadcaster,
        base_model: Any,
        tools_by_name: dict[str, Any],
        streaming: bool = True,
        workspace: str | None = None,
        skills_dirs: list[str] | None = None,
    ):
        self._registry = registry
        self._broadcaster = broadcaster
        self._base_model = base_model
        self._tools_by_name = tools_by_name
        self._streaming = streaming
        self._workspace = workspace
        self._skills_dirs = skills_dirs
```

(c) Add `_build_inner` and `_skills_hint` (place after `__init__`):
```python
    def _build_inner(self, info: AgentInfo) -> Any:
        """Construct the inner DeepAgents instance for this agent's current config.

        Rebuilt each segment so tool changes (subscribe_tool/unsubscribe_tool)
        take effect. Raises ValueError on an unknown tool name — a config bug,
        surfaced loudly (and create_deep_agent is not called).
        """
        missing = [n for n in info.tools if n not in self._tools_by_name]
        if missing:
            raise ValueError(
                f"Unknown tools requested by {info.agent_id}: {missing}. "
                f"Available: {sorted(self._tools_by_name)}"
            )
        tools = [self._tools_by_name[n] for n in info.tools]
        kwargs: dict = {"model": self._base_model, "tools": tools}
        if self._workspace:
            kwargs["backend"] = FilesystemBackend(root_dir=self._workspace, virtual_mode=True)
        if self._skills_dirs:
            kwargs["skills"] = self._skills_dirs
        return create_deep_agent(**kwargs)

    @staticmethod
    def _skills_hint(info: AgentInfo) -> str | None:
        """A prompt nudge listing the agent's subscribed skills, or None."""
        if not info.skills:
            return None
        return f"Prioritize these skills for this work: {', '.join(info.skills)}."
```

(d) Rework `_run` so the prologue no longer builds `inner` (the loop does), sets the tier, and composes the initial messages (with skills hint). Replace the prologue block from the unknown-tool check through the `state = {...}` / RUNNING transition with:
```python
        try:
            # --- prologue (shared by both execution paths) ---
            # Validate tools up-front (also re-checked per build in _build_inner).
            missing = [n for n in info.tools if n not in self._tools_by_name]
            if missing:
                raise ValueError(
                    f"Unknown tools requested by {agent_id}: {missing}. "
                    f"Available: {sorted(self._tools_by_name)}"
                )

            self._broadcaster.agent_spawned(
                agent_id=agent_id, name=info.name, role=info.role, tier=info.tier,
            )
            await store.write_heartbeat(agent_id, iteration=0, status="starting")

            # Scope this sub-agent's tier to its own asyncio task. Effective only
            # when base_model is the RoutingChatModel; a harmless no-op otherwise.
            set_active_tier(info.tier)

            task_text = info.task
            if recovery_context:
                task_text = f"{recovery_context}\n\n---\n\nTask: {info.task}"
            hint = self._skills_hint(info)
            if hint:
                task_text = f"{hint}\n\n{task_text}"
            messages = [HumanMessage(content=task_text)]

            await store.write_heartbeat(agent_id, iteration=1, status="running")
            self._registry.update_state(agent_id, SubAgentState.RUNNING)

            # --- execute (streaming default; streaming=False for single-shot fallback) ---
            output, stopped = await self._execute(info, messages)
```

(e) Update `_execute` to take `(info, messages)` and build inner internally:
```python
    async def _execute(self, info: AgentInfo, messages: list) -> tuple[str, bool]:
        """Run the inner agent and return (output, stopped)."""
        if self._streaming:
            return await self._stream_run(info, messages)
        inner = self._build_inner(info)
        result = await inner.ainvoke({"messages": messages})
        return _extract_last_text(result.get("messages", [])), False
```

(f) Update `_stream_run`'s signature/first lines to build inner from `info` and take `messages` (the outer loop is added in Task 2; for now keep a single segment so tests stay green). Change its head to:
```python
    async def _stream_run(self, info: AgentInfo, messages: list) -> tuple[str, bool]:
        """Drive the inner agent via astream (single segment; outer loop added in WS2 Task 2)."""
        agent_id = info.agent_id
        store = self._registry.agent_store
        inner = self._build_inner(info)
        state = {"messages": messages}
        final_state = state
        stopped = False
        saw_step = False

        async with aclosing(inner.astream(state, stream_mode="values")) as stream:
```
(The remainder of `_stream_run` — the `first`/skip-echo loop, heartbeat/progress/broadcast, shutdown directive, `saw_step` guard, and final `return` — is unchanged from WS1.)

- [ ] **Step 4: Run the new tests + full spawner suite**

Run: `python -m pytest tests/test_spawner.py -v`
Expected: PASS — the 3 new tests plus all WS1 tests (12). Mocks ignore the extra `backend`/`skills` kwargs; `set_active_tier` is harmless with a `MagicMock` base model.

- [ ] **Step 5: Commit**

```bash
git add src/subagent/spawner.py tests/test_spawner.py
git commit -m "feat(subagent): sub-agents get backend + skills + per-task tier; extract _build_inner"
```

---

## Task 2: Outer segment loop + inbox drain + `change_tier`

Turn `_stream_run` into an outer loop: run a segment, then at the clean boundary drain the inbox (new tasks + skill hints) and rebuild for the next segment if there's work; finish when idle. Handle the `change_tier` directive per chunk.

**Files:**
- Modify: `src/subagent/spawner.py`
- Test: `tests/test_spawner.py`

- [ ] **Step 1: Extend the test `astream` factory to vary output per segment, and write failing tests**

In `tests/test_spawner.py`, add a segment-aware fake after the existing helpers:

```python
def _astream_segments(segments):
    """Fake astream where each call returns the next segment's chunks.

    ``segments`` is a list of chunk-lists; call N yields segment N (preceded by
    the input-state echo, mirroring stream_mode="values").
    """
    calls = {"n": 0}

    def _astream(state, **kwargs):
        idx = calls["n"]
        calls["n"] += 1
        chunks = segments[idx] if idx < len(segments) else []
        async def _gen():
            yield state
            for c in chunks:
                yield c
        return _gen()
    return _astream
```

Then add:

```python
@pytest.mark.asyncio
async def test_assign_task_runs_another_segment(monkeypatch):
    """A task in the inbox is consumed after the current segment, running another."""
    store = InMemoryStore()
    registry = SubAgentRegistry(store)
    broadcaster = EventBroadcaster(None)

    inner = MagicMock()
    inner.astream = _astream_segments([
        [{"messages": [AIMessage(content="seg1-done")]}],
        [{"messages": [AIMessage(content="seg2-done")]}],
    ])
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
    # inbox was drained
    assert await registry.agent_store.drain_inbox("a1") == []


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
    # Directive present before the first real chunk's post-check.
    await registry.agent_store.write_directive("a1", action="change_tier", params={"tier": "expert"})

    task = await spawner.spawn(info)
    registry._tasks["a1"] = task
    await asyncio.wait_for(task, timeout=5.0)

    assert seen_tiers[0] == "standard"   # initial
    assert seen_tiers[1] == "expert"     # changed after first chunk's directive check
    assert await registry.agent_store.read_directive("a1") is None  # consumed
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_spawner.py -k "another_segment or one_segment or change_tier" -v`
Expected: FAIL — single-segment `_stream_run` ignores the inbox (no second segment) and only handles `shutdown`.

- [ ] **Step 3: Rewrite `_stream_run` as an outer loop with a `_run_segment` helper**

Replace the entire `_stream_run` method in `src/subagent/spawner.py` with:

```python
    async def _stream_run(self, info: AgentInfo, messages: list) -> tuple[str, bool]:
        """Outer loop: run streaming segments until the inbox is empty or shutdown.

        Each segment is a full ``inner.astream`` run rebuilt from the agent's
        current config (so subscribe_tool changes apply). Between segments — a
        guaranteed-clean boundary — the inbox is drained: queued tasks become new
        HumanMessages and trigger another segment. tier changes apply live via
        the per-chunk ``change_tier`` directive.
        """
        agent_id = info.agent_id
        store = self._registry.agent_store
        first_segment = True

        while True:
            inner = self._build_inner(info)
            messages, stopped, saw_step = await self._run_segment(inner, messages, info)

            if stopped:                       # shutdown directive mid-segment
                return _extract_last_text(messages), True
            if first_segment and not saw_step:
                raise RuntimeError(f"Sub-agent {agent_id}: astream produced no steps")
            first_segment = False

            # Clean boundary: drain inbox for follow-up work.
            inbox = await store.drain_inbox(agent_id)
            if not inbox:
                return _extract_last_text(messages), False
            for item in inbox:
                messages = messages + [HumanMessage(content=item["message"])]

    async def _run_segment(self, inner: Any, messages: list, info: AgentInfo) -> tuple[list, bool, bool]:
        """Stream one inner run. Returns (final_messages, stopped, saw_step)."""
        agent_id = info.agent_id
        store = self._registry.agent_store
        state = {"messages": messages}
        final_state = state
        stopped = False
        saw_step = False

        async with aclosing(inner.astream(state, stream_mode="values")) as stream:
            first = True
            async for chunk in stream:
                final_state = chunk
                if first:
                    # stream_mode="values" echoes the input state first — not a step.
                    first = False
                    continue
                saw_step = True
                self._registry.increment_iteration(agent_id)
                iteration = self._registry.get_agent(agent_id).iteration
                preview = _extract_last_text(chunk.get("messages", []))[:_PROGRESS_PREVIEW_CHARS]

                await store.write_heartbeat(agent_id, iteration=iteration, status="running")
                await store.write_progress(agent_id, message=preview, cost=info.cost_cents)
                self._broadcaster.agent_progress(
                    agent_id=agent_id, message=preview, cost_cents=info.cost_cents,
                )

                directive = await store.read_directive(agent_id)
                if directive:
                    action = directive.get("action")
                    if action == "shutdown":
                        await store.clear_directive(agent_id)
                        stopped = True
                        logger.info("Sub-agent %s received shutdown directive; stopping", agent_id)
                        break
                    if action == "change_tier":
                        new_tier = directive.get("params", {}).get("tier")
                        if new_tier:
                            set_active_tier(new_tier)
                            logger.info("Sub-agent %s tier → %s (live)", agent_id, new_tier)
                        await store.clear_directive(agent_id)

        return final_state.get("messages", []), stopped, saw_step
```

- [ ] **Step 4: Run the new tests + full spawner suite**

Run: `python -m pytest tests/test_spawner.py -v`
Expected: PASS — new segment-loop/tier tests plus all prior tests. (WS1's `test_streaming_*` tests use `_astream_factory`, which yields one segment then an empty inbox → one segment, identical behavior.)

- [ ] **Step 5: Commit**

```bash
git add src/subagent/spawner.py tests/test_spawner.py
git commit -m "feat(subagent): outer segment loop — inbox drain + live change_tier"
```

---

## Task 3: `subscribe_tool` / `unsubscribe_tool` / `subscribe_skill` tools

Add the three missing orchestration tools and validate tool names against the known set.

**Files:**
- Modify: `src/subagent/tools.py`
- Test: `tests/test_subagent_tools.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_subagent_tools.py` (match the file's existing fixture style for `init_orchestration_tools`; these assume a `registry` with a registered agent `a1`):

```python
@pytest.mark.asyncio
async def test_subscribe_tool_adds_to_info(registry_with_agent):
    from src.subagent.tools import init_orchestration_tools, subscribe_tool
    registry, info = registry_with_agent           # info.tools == ["read_file"]
    init_orchestration_tools(registry, known_tools={"read_file", "web_search"})

    out = await subscribe_tool.ainvoke({"agent_id": "a1", "tool_name": "web_search"})
    assert "web_search" in info.tools
    assert "web_search" in out


@pytest.mark.asyncio
async def test_subscribe_tool_rejects_unknown(registry_with_agent):
    from src.subagent.tools import init_orchestration_tools, subscribe_tool
    registry, info = registry_with_agent
    init_orchestration_tools(registry, known_tools={"read_file"})

    out = await subscribe_tool.ainvoke({"agent_id": "a1", "tool_name": "bogus"})
    assert "bogus" not in info.tools
    assert "Unknown tool" in out


@pytest.mark.asyncio
async def test_unsubscribe_tool_removes(registry_with_agent):
    from src.subagent.tools import init_orchestration_tools, unsubscribe_tool
    registry, info = registry_with_agent           # info.tools == ["read_file"]
    init_orchestration_tools(registry, known_tools={"read_file"})

    out = await unsubscribe_tool.ainvoke({"agent_id": "a1", "tool_name": "read_file"})
    assert "read_file" not in info.tools
    assert "read_file" in out


@pytest.mark.asyncio
async def test_subscribe_skill_records_and_nudges(registry_with_agent):
    from src.subagent.tools import init_orchestration_tools, subscribe_skill
    registry, info = registry_with_agent
    init_orchestration_tools(registry, known_tools=set())

    out = await subscribe_skill.ainvoke({"agent_id": "a1", "skill_name": "github"})
    assert "github" in info.skills
    # the agent is nudged via its inbox
    inbox = await registry.agent_store.drain_inbox("a1")
    assert any("github" in m["message"] for m in inbox)
    assert "github" in out
```

If `tests/test_subagent_tools.py` lacks a `registry_with_agent` fixture, add this near the top of the file:

```python
@pytest.fixture
def registry_with_agent():
    import asyncio
    from langgraph.store.memory import InMemoryStore
    from src.subagent.registry import SubAgentRegistry
    from src.subagent.state import AgentInfo
    registry = SubAgentRegistry(InMemoryStore())
    info = AgentInfo(agent_id="a1", name="n", role="executor", task="t",
                     tier="standard", tools=["read_file"], skills=[])
    registry.register(info, asyncio.get_event_loop().create_task(asyncio.sleep(0)))
    return registry, info
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_subagent_tools.py -k "subscribe or unsubscribe" -v`
Expected: FAIL — those tools don't exist; `init_orchestration_tools` has no `known_tools` param.

- [ ] **Step 3: Add `known_tools` to `init_orchestration_tools` and implement the three tools**

In `src/subagent/tools.py`:

(a) Add a module global and extend the initializer:
```python
_registry: SubAgentRegistry | None = None
_spawner: Callable | None = None          # async (info) → asyncio.Task
_cost_tracker = None                        # CostTracker or None
_known_tools: frozenset[str] = frozenset()  # valid tool names for subscribe_tool


def init_orchestration_tools(
    registry: SubAgentRegistry,
    spawner: Optional[Callable] = None,
    cost_tracker=None,
    known_tools: Optional[set[str]] = None,
) -> None:
    """Initialize module-level references for orchestration tools."""
    global _registry, _spawner, _cost_tracker, _known_tools
    if _registry is not None and _registry is not registry:
        logger.warning(
            "Orchestration tools re-initialized; previous registry (%r) replaced",
            _registry,
        )
    _registry = registry
    _spawner = spawner
    _cost_tracker = cost_tracker
    _known_tools = frozenset(known_tools or set())
```

(b) Add the three tools (place after `switch_agent_model`):
```python
@tool
async def subscribe_tool(agent_id: str, tool_name: str) -> str:
    """Add a tool to a running sub-agent. Takes effect on its next work segment.

    Args:
        agent_id: The agent to modify
        tool_name: Name of a tool to grant (must be a known platform tool)
    """
    if _registry is None:
        return "Error: orchestration not initialized"
    info = _registry.get_agent(agent_id)
    if info is None:
        return f"Agent {agent_id} not found"
    if tool_name not in _known_tools:
        return f"Unknown tool '{tool_name}'. Available: {sorted(_known_tools)}"
    if tool_name not in info.tools:
        info.tools.append(tool_name)
    return f"Tool '{tool_name}' subscribed to {agent_id} (effective next segment)."


@tool
async def unsubscribe_tool(agent_id: str, tool_name: str) -> str:
    """Remove a tool from a running sub-agent. Takes effect on its next work segment.

    Args:
        agent_id: The agent to modify
        tool_name: Name of the tool to revoke
    """
    if _registry is None:
        return "Error: orchestration not initialized"
    info = _registry.get_agent(agent_id)
    if info is None:
        return f"Agent {agent_id} not found"
    if tool_name in info.tools:
        info.tools.remove(tool_name)
        return f"Tool '{tool_name}' unsubscribed from {agent_id} (effective next segment)."
    return f"Agent {agent_id} did not have tool '{tool_name}'."


@tool
async def subscribe_skill(agent_id: str, skill_name: str) -> str:
    """Make a skill a priority for a running sub-agent (nudged via its inbox).

    Args:
        agent_id: The agent to modify
        skill_name: Name of the skill to prioritize
    """
    if _registry is None:
        return "Error: orchestration not initialized"
    info = _registry.get_agent(agent_id)
    if info is None:
        return f"Agent {agent_id} not found"
    if skill_name not in info.skills:
        info.skills.append(skill_name)
    await _registry.agent_store.send_inbox(
        agent_id, sender="master",
        message=f"You now have access to the '{skill_name}' skill — use it when relevant.",
    )
    return f"Skill '{skill_name}' subscribed to {agent_id}."
```

- [ ] **Step 4: Run the new tests + full orchestration-tool suite**

Run: `python -m pytest tests/test_subagent_tools.py -v`
Expected: PASS — new subscribe/unsubscribe/skill tests plus existing ones (the new `known_tools` param defaults to empty and doesn't break existing `init_orchestration_tools` calls).

- [ ] **Step 5: Commit**

```bash
git add src/subagent/tools.py tests/test_subagent_tools.py
git commit -m "feat(subagent): add subscribe_tool/unsubscribe_tool/subscribe_skill orchestration tools"
```

---

## Task 4: Wire WS2 into `create_agent`

Feed the spawner the workspace + skills dirs, give the orchestration tools the known-tool set, and expose the three new tools to the master.

**Files:**
- Modify: `src/agent.py`
- Test: `tests/test_agent_swarm_wiring.py` (extend if present; otherwise add a focused wiring test)

- [ ] **Step 1: Write the failing wiring test**

Add to `tests/test_agent_swarm_wiring.py` (or create it) a test that builds the agent with subagents enabled and asserts the three tools are present and the spawner got the workspace. Keep it light — assert on the tool names registered:

```python
@pytest.mark.asyncio
async def test_subscribe_tools_registered(monkeypatch, tmp_path):
    """create_agent exposes the WS2 subscription tools when subagents are enabled."""
    from src.config import AppConfig
    from src import agent as agent_mod

    cfg = AppConfig()
    cfg.agent.workspace = str(tmp_path)
    cfg.subagent.enabled = True

    bundle = await agent_mod.create_agent(cfg)
    # The master's tool list should include the new orchestration tools.
    names = {t.name for t in bundle.agent.tools} if hasattr(bundle.agent, "tools") else set()
    # Fallback: assert the tools are importable + were extended into custom_tools
    from src.subagent.tools import subscribe_tool, unsubscribe_tool, subscribe_skill
    assert subscribe_tool.name == "subscribe_tool"
    assert unsubscribe_tool.name == "unsubscribe_tool"
    assert subscribe_skill.name == "subscribe_skill"
```

> Note for the implementer: if `bundle.agent` does not expose `.tools` directly, assert instead that `create_agent` ran without error and that `init_orchestration_tools` was called with a non-empty `known_tools` (you can monkeypatch `src.subagent.tools.init_orchestration_tools` to capture its kwargs). Pick whichever assertion the codebase supports; the goal is to prove the three tools are wired and `known_tools`/`workspace` reach their consumers.

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_agent_swarm_wiring.py -k subscribe -v`
Expected: FAIL — the three tools aren't added to `custom_tools`; the spawner/init calls don't pass the new args.

- [ ] **Step 3: Wire `create_agent`**

In `src/agent.py`, inside the `if config.subagent.enabled:` block:

(a) Import the three new tools alongside the existing orchestration imports:
```python
        from .subagent.tools import (
            init_orchestration_tools,
            spawn_agent, recall_agent, monitor_agents,
            assign_task, switch_agent_model, review_cost,
            subscribe_tool, unsubscribe_tool, subscribe_skill,
        )
```

(b) Pass `workspace` + `skills_dirs` to the spawner (`tools_by_name` is built just above this in the existing code):
```python
        spawner = DeepAgentsSpawner(
            registry=subagent_registry,
            broadcaster=broadcaster,
            base_model=model,
            tools_by_name=tools_by_name,
            streaming=config.subagent.streaming,
            workspace=workspace,
            skills_dirs=skills_dirs if skills_dirs else None,
        )
```

(c) Pass `known_tools` to the initializer (the set of all custom tool names available to sub-agents):
```python
        init_orchestration_tools(
            registry=subagent_registry,
            spawner=spawner.spawn,
            cost_tracker=cost_tracker,
            known_tools={t.name for t in custom_tools},
        )
```

(d) Add the three tools to `custom_tools`:
```python
        custom_tools.extend([
            spawn_agent, recall_agent, monitor_agents,
            assign_task, switch_agent_model, review_cost,
            subscribe_tool, unsubscribe_tool, subscribe_skill,
        ])
        logger.info("Orchestration tools enabled (9 tools)")
```

> Note: `tools_by_name` is currently built from `custom_tools` *before* the orchestration tools are appended (it's used by the spawner to resolve sub-agent tool names). Leave that as-is — sub-agents resolve worker tools (web/host/etc.), not orchestration tools. `known_tools` for `subscribe_tool` is derived from that same pre-orchestration `custom_tools` snapshot, which is correct: a sub-agent should only subscribe worker tools, never orchestration tools.

- [ ] **Step 4: Run the wiring test + full orchestration suite**

Run: `python -m pytest tests/test_agent_swarm_wiring.py -v && python -m pytest tests/ -k "subagent or swarm or spawn or agent_swarm or config or tools" -q`
Expected: PASS — wiring test green, no regressions.

- [ ] **Step 5: Commit**

```bash
git add src/agent.py tests/test_agent_swarm_wiring.py
git commit -m "feat(subagent): wire WS2 — spawner workspace/skills, known_tools, expose subscribe tools"
```

---

## Self-Review

**Spec coverage (scope doc §4 WS2):**
- "subscribe_tool / unsubscribe_tool / subscribe_skill (currently absent)" → Task 3. ✅
- "make assign_task and switch_agent_model effective on a running agent" → Task 2 (inbox drain triggers a new segment for `assign_task`; `change_tier` directive applied live for `switch_agent_model`). ✅
- "driver applies changes at a clean turn boundary; rebuild with carried-forward messages" → Task 2 outer loop rebuilds per segment from `info.tools`, carrying `messages`. ✅
- "assign_task injects via inbox → appended as HumanMessage on the next turn" → Task 2 `drain_inbox` → `HumanMessage`. ✅
- Decisions §6.1/§6.2 (segment boundary, clean reconfigure) honored; tier-via-ContextVar and skills-hint are the user-approved refinements, documented in the header. ✅

**Placeholder scan:** No "TBD"/"handle later". The one conditional instruction (Task 4 Step 1 fallback assertion) gives the implementer a concrete decision rule, not a vague gap. ✅

**Type consistency:** `_execute(info, messages)` and `_stream_run(info, messages)` agree (Tasks 1–2); `_run_segment(inner, messages, info) -> (list, bool, bool)` is defined and consumed in Task 2; `set_active_tier` imported from `..tools.model_router`; `_build_inner`/`_skills_hint` defined in Task 1 and used in Task 2; `known_tools` threaded from Task 3 (`init_orchestration_tools`) to Task 4 (`create_agent`). Store methods (`send_inbox`, `drain_inbox`, `read_directive`, `clear_directive`, `write_directive`) match `src/subagent/store.py`. ✅

**Known scope boundary (logged, not silently dropped):** `assign_task` only reaches an agent still running; an agent that has gone idle finishes and cannot be re-tasked without respawn (persistent-worker mode is future work, recorded in §5 of this plan's decisions and scope doc §8.1).
