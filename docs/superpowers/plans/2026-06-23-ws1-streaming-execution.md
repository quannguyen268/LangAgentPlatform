# WS1 — Streaming Execution Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the sub-agent single-shot `inner.ainvoke(state)` with an incremental driver loop over `inner.astream(...)` that increments `iteration`, writes per-step heartbeat/progress, emits `agent_progress` events, and honors a `shutdown` directive — the foundation every other orchestration gap (WS2–WS4) attaches to.

**Architecture:** `DeepAgentsSpawner._run` keeps a single shared prologue (tool resolution, spawn event, build inner agent, recovery-context prepend, `RUNNING` transition) and a single shared epilogue (write result, `FINISHED`, `agent_complete`). Only the middle "execute" step branches: a new `_stream_run` consumes the agent's stream turn-by-turn, while the original single-shot path is retained behind a `streaming` flag as a kill-switch. The flag ships **on**; flip it off to fall back to single-shot.

**Tech Stack:** Python 3.13, `deepagents` 0.6.1 (`create_deep_agent` → `CompiledStateGraph` with `astream`), LangGraph `BaseStore`, `contextlib.aclosing`, pytest + pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-06-23-orchestration-completion-scope.md` (§3 Approach A, §4 WS1, §6.3).

> **Note on stream mode (refines spec §6.3):** the spec recommended `stream_mode="updates"` to avoid the low-level `astream_events` API. This plan uses `stream_mode="values"` instead — it equally satisfies the anti-coupling intent (it is a high-level, stable stream mode, *not* `astream_events`) while yielding the full state snapshot each step, which makes final-output extraction trivial and robust (no manual message accumulation). Per-step progress is read from the latest message in each snapshot.

---

## File Structure

| File | Responsibility | Change |
|------|----------------|--------|
| `src/subagent/spawner.py` | Sub-agent execution: prologue/epilogue + single-shot and streaming execute paths | Modify — add `streaming` param, `_PROGRESS_PREVIEW_CHARS`, refactor `_run`, add `_stream_run` |
| `src/config.py` | `SubAgentConfig` | Modify — add `streaming: bool = True` |
| `src/agent.py` | `create_agent()` wiring | Modify — pass `streaming=config.subagent.streaming` to `DeepAgentsSpawner` |
| `tests/test_spawner.py` | Spawner tests | Modify — add streaming-path tests; pin the 6 legacy tests to `streaming=False` |
| `tests/test_config.py` | Config parsing tests | Modify — assert `streaming` default |

---

## Task 1: Refactor `_run` execution seam + add (unused) `streaming` flag

Behavior-preserving refactor: isolate the invoke into `_execute()` and add the flag (default `False`, unused this task). Nothing changes at runtime — existing tests stay green.

**Files:**
- Modify: `src/subagent/spawner.py`
- Modify: `src/config.py:286-292` (`SubAgentConfig`)
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing config test**

Add to `tests/test_config.py`:

```python
def test_subagent_streaming_defaults_true():
    from src.config import SubAgentConfig
    assert SubAgentConfig().streaming is True
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_config.py::test_subagent_streaming_defaults_true -v`
Expected: FAIL — `AttributeError: 'SubAgentConfig' object has no attribute 'streaming'`

- [ ] **Step 3: Add the config field**

In `src/config.py`, modify `SubAgentConfig` (currently ends at `health_check_interval`):

```python
class SubAgentConfig(BaseModel):
    enabled: bool = True
    heartbeat_timeout: float = 120.0
    task_timeout: float = 1800.0
    max_iterations: int = 50
    max_retries: int = 1
    health_check_interval: float = 30.0
    streaming: bool = True  # WS1: drive sub-agents via astream loop (False = single-shot fallback)
```

- [ ] **Step 4: Run it to verify it passes**

Run: `python -m pytest tests/test_config.py::test_subagent_streaming_defaults_true -v`
Expected: PASS

- [ ] **Step 5: Refactor `spawner.py` — add flag + preview constant + `_execute` seam**

In `src/subagent/spawner.py`, add the module-level constant after the logger line:

```python
logger = logging.getLogger(__name__)

_PROGRESS_PREVIEW_CHARS = 200
```

Change `__init__` to accept `streaming` (default `False` for now — flipped in Task 3):

```python
    def __init__(
        self,
        registry: SubAgentRegistry,
        broadcaster: EventBroadcaster,
        base_model: Any,
        tools_by_name: dict[str, Any],
        streaming: bool = False,
    ):
        self._registry = registry
        self._broadcaster = broadcaster
        self._base_model = base_model
        self._tools_by_name = tools_by_name
        self._streaming = streaming
```

Replace the body of `_run` (the `try:` block's invoke + result handling) so the invoke is delegated to `_execute`, and the result `status` is derived from a `stopped` flag. The full new `_run` + `_execute`:

```python
    async def _run(self, info: AgentInfo, recovery_context: Optional[str]) -> None:
        agent_id = info.agent_id
        store = self._registry.agent_store

        try:
            # --- prologue (shared by both execution paths) ---
            missing = [n for n in info.tools if n not in self._tools_by_name]
            if missing:
                raise ValueError(
                    f"Unknown tools requested by {agent_id}: {missing}. "
                    f"Available: {sorted(self._tools_by_name)}"
                )
            tools = [self._tools_by_name[n] for n in info.tools]

            self._broadcaster.agent_spawned(
                agent_id=agent_id, name=info.name, role=info.role, tier=info.tier,
            )
            await store.write_heartbeat(agent_id, iteration=0, status="starting")

            inner = create_deep_agent(
                model=self._base_model,
                tools=tools,
            )

            task_text = info.task
            if recovery_context:
                task_text = f"{recovery_context}\n\n---\n\nTask: {info.task}"
            state = {"messages": [HumanMessage(content=task_text)]}

            await store.write_heartbeat(agent_id, iteration=1, status="running")
            self._registry.update_state(agent_id, SubAgentState.RUNNING)

            # --- execute (branches in Task 2; single-shot for now) ---
            output, stopped = await self._execute(inner, state, info)

            # --- epilogue (shared) ---
            status = "stopped" if stopped else "success"
            await store.write_result(
                agent_id, status=status, output=output, cost_total=info.cost_cents,
            )
            info.result = output
            info.finished_at = time.time()
            self._registry.update_state(agent_id, SubAgentState.FINISHED)
            self._broadcaster.agent_completed(
                agent_id=agent_id, result=output, cost_total_cents=info.cost_cents,
            )
            logger.info("Sub-agent %s completed (status=%s)", agent_id, status)

        except asyncio.CancelledError:
            logger.info("Sub-agent %s cancelled", agent_id)
            raise
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            info.error = err
            info.finished_at = time.time()
            self._registry.update_state(agent_id, SubAgentState.FAILED)
            try:
                await store.write_result(
                    agent_id, status="failed", output=err, cost_total=info.cost_cents,
                )
            except Exception as store_err:
                logger.warning(
                    "Sub-agent %s: failed to write failure result: %s",
                    agent_id, store_err,
                )
            self._broadcaster.agent_failed(
                agent_id=agent_id, reason=type(e).__name__, action="pending",
            )
            logger.exception("Sub-agent %s failed", agent_id)

    async def _execute(self, inner: Any, state: dict, info: AgentInfo) -> tuple[str, bool]:
        """Run the inner agent and return (output, stopped).

        ``stopped`` is True only when a shutdown directive ended a streaming run
        early. Single-shot runs always return stopped=False.
        """
        result = await inner.ainvoke(state)
        return _extract_last_text(result.get("messages", [])), False
```

- [ ] **Step 6: Run the full spawner + config suite to verify green (no behavior change)**

Run: `python -m pytest tests/test_spawner.py tests/test_config.py -v`
Expected: PASS — all 6 existing spawner tests + the new config test pass (single-shot path unchanged; `status="success"` because `stopped=False`).

- [ ] **Step 7: Commit**

```bash
git add src/subagent/spawner.py src/config.py tests/test_config.py
git commit -m "refactor(subagent): isolate execute seam + add streaming flag (unused)"
```

---

## Task 2: Implement the streaming execute path + tests

Add `_stream_run` and branch `_execute` on `self._streaming`. New tests construct the spawner with `streaming=True`; legacy tests (default `False`) stay green.

**Files:**
- Modify: `src/subagent/spawner.py`
- Test: `tests/test_spawner.py`

- [ ] **Step 1: Add a shared `astream` test helper at the top of `tests/test_spawner.py`**

After the existing imports in `tests/test_spawner.py`, add:

```python
from contextlib import suppress  # noqa: F401  (kept for symmetry with async helpers)


def _astream_factory(chunks, captured=None):
    """Return a fake ``astream(state, **kwargs)`` yielding the given chunks.

    If ``captured`` is provided, the first message's content is recorded under
    ``captured["content"]`` (used to assert recovery-context prepending).
    """
    def _astream(state, **kwargs):
        if captured is not None:
            captured["content"] = state["messages"][0].content

        async def _gen():
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
```

- [ ] **Step 2: Write the failing streaming tests**

Append to `tests/test_spawner.py`:

```python
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
```

- [ ] **Step 3: Run the new tests to verify they fail**

Run: `python -m pytest tests/test_spawner.py -k streaming -v`
Expected: FAIL — `_execute` always runs single-shot, so `inner.astream` is never consumed (`iteration` stays 0, no progress events). Errors like `assert 0 == 3`.

- [ ] **Step 4: Implement `_stream_run` and branch `_execute`**

In `src/subagent/spawner.py`, add the `aclosing` import at the top of the imports block:

```python
import asyncio
import logging
import time
from contextlib import aclosing
from typing import Any, Optional
```

Replace `_execute` with the branching version and add `_stream_run`:

```python
    async def _execute(self, inner: Any, state: dict, info: AgentInfo) -> tuple[str, bool]:
        """Run the inner agent and return (output, stopped).

        ``stopped`` is True only when a shutdown directive ended a streaming run
        early. Single-shot runs always return stopped=False.
        """
        if self._streaming:
            return await self._stream_run(inner, state, info)
        result = await inner.ainvoke(state)
        return _extract_last_text(result.get("messages", [])), False

    async def _stream_run(self, inner: Any, state: dict, info: AgentInfo) -> tuple[str, bool]:
        """Drive the inner agent turn-by-turn via astream.

        Per chunk: increment iteration, write heartbeat + progress, emit
        agent_progress, and break early if a shutdown directive is pending.
        Uses stream_mode="values" so each chunk is the full state snapshot; the
        last snapshot carries the final messages.
        """
        agent_id = info.agent_id
        store = self._registry.agent_store
        final_state = state
        stopped = False

        async with aclosing(inner.astream(state, stream_mode="values")) as stream:
            async for chunk in stream:
                final_state = chunk
                self._registry.increment_iteration(agent_id)
                preview = _extract_last_text(chunk.get("messages", []))[:_PROGRESS_PREVIEW_CHARS]

                await store.write_heartbeat(agent_id, iteration=info.iteration, status="running")
                await store.write_progress(agent_id, message=preview, cost=info.cost_cents)
                self._broadcaster.agent_progress(
                    agent_id=agent_id, message=preview, cost_cents=info.cost_cents,
                )

                directive = await store.read_directive(agent_id)
                if directive and directive.get("action") == "shutdown":
                    await store.clear_directive(agent_id)
                    stopped = True
                    logger.info("Sub-agent %s received shutdown directive; stopping", agent_id)
                    break

        return _extract_last_text(final_state.get("messages", [])), stopped
```

- [ ] **Step 5: Run the new tests to verify they pass**

Run: `python -m pytest tests/test_spawner.py -k streaming -v`
Expected: PASS — all 5 streaming tests pass.

- [ ] **Step 6: Run the full spawner suite to confirm legacy tests still green**

Run: `python -m pytest tests/test_spawner.py -v`
Expected: PASS — 6 legacy (single-shot, default `streaming=False`) + 5 new streaming tests.

- [ ] **Step 7: Commit**

```bash
git add src/subagent/spawner.py tests/test_spawner.py
git commit -m "feat(subagent): add streaming execution path (iteration, progress, graceful shutdown)"
```

---

## Task 3: Flip default to streaming + wire config end-to-end

Make streaming the production default and feed the config flag through `create_agent`. Pin the 6 legacy tests to `streaming=False` so the single-shot fallback stays covered.

**Files:**
- Modify: `src/subagent/spawner.py` (`__init__` default)
- Modify: `src/agent.py:312-318` (spawner construction)
- Modify: `tests/test_spawner.py` (pin legacy tests)

- [ ] **Step 1: Pin the 6 legacy single-shot tests to `streaming=False`**

In `tests/test_spawner.py`, the following test functions each construct `DeepAgentsSpawner(...)` and mock `inner.ainvoke`. In **each** of these constructions, add `streaming=False` as the final keyword argument:

- `test_spawner_writes_heartbeat_and_result`
- `test_spawner_emits_spawn_and_complete`
- `test_spawner_handles_inner_failure`
- `test_spawner_raises_on_unknown_tool`
- `test_spawner_prepends_recovery_context`
- `test_spawner_failed_event_uses_exception_type`

The transformation in every case:

```python
# before
    spawner = DeepAgentsSpawner(
        registry=registry,
        broadcaster=broadcaster,
        base_model=MagicMock(),
        tools_by_name={},
    )
# after
    spawner = DeepAgentsSpawner(
        registry=registry,
        broadcaster=broadcaster,
        base_model=MagicMock(),
        tools_by_name={},
        streaming=False,
    )
```

(`tools_by_name` differs in `test_spawner_raises_on_unknown_tool` — it is `{"read_file": object()}` — but the edit is the same: append `streaming=False`.)

- [ ] **Step 2: Run the legacy tests to verify they fail without the default flip**

Run: `python -m pytest tests/test_spawner.py -k "not streaming" -v`
Expected: PASS still (default is currently `False`, and we just made it explicit). This step confirms the pin is correct before flipping the default.

- [ ] **Step 3: Flip the spawner default to streaming**

In `src/subagent/spawner.py`, change the `__init__` signature default:

```python
        tools_by_name: dict[str, Any],
        streaming: bool = True,
```

- [ ] **Step 4: Wire the config flag in `create_agent`**

In `src/agent.py`, update the `DeepAgentsSpawner(...)` construction (currently around line 312):

```python
        spawner = DeepAgentsSpawner(
            registry=subagent_registry,
            broadcaster=broadcaster,
            base_model=model,
            tools_by_name=tools_by_name,
            streaming=config.subagent.streaming,
        )
```

- [ ] **Step 5: Run the full spawner suite**

Run: `python -m pytest tests/test_spawner.py -v`
Expected: PASS — legacy tests run single-shot (pinned `streaming=False`), streaming tests run the loop (explicit `streaming=True`). The default flip does not affect either because both are explicit.

- [ ] **Step 6: Run the whole orchestration + agent suite for regressions**

Run: `python -m pytest tests/ -k "subagent or swarm or spawn or recovery or health or harness or agent_swarm or config" -q`
Expected: PASS — no regressions across the orchestration subsystems (was 158 passing for the orchestration filter; now higher with the new streaming tests).

- [ ] **Step 7: Commit**

```bash
git add src/subagent/spawner.py src/agent.py tests/test_spawner.py
git commit -m "feat(subagent): make streaming the default execution model + wire config flag"
```

---

## Self-Review

**Spec coverage (against scope doc §4 WS1):**
- "single `ainvoke` → outer driver loop over `astream`" → Task 2 `_stream_run`. ✅
- "increment `AgentInfo.iteration`" → Task 2 `increment_iteration` per chunk; `test_streaming_increments_iteration_per_chunk`. ✅
- "write heartbeat (real iteration count, not hard-coded 0→1) + progress" → Task 2 `write_heartbeat(iteration=info.iteration)` + `write_progress`. ✅
- "emit `agent_progress` via the broadcaster" → Task 2 `broadcaster.agent_progress`; `test_streaming_emits_progress_per_chunk`. ✅
- "drain `directive` and honor `shutdown` gracefully" → Task 2 directive check + `clear_directive`; `test_streaming_honors_shutdown_directive`. ✅
- "keeps existing SPAWNING→RUNNING→FINISHED/FAILED transitions and CancelledError/exception handling" → Task 1 retains the `except` blocks verbatim; `test_streaming_inner_failure_marks_failed`. ✅
- Cross-cutting config flag `subagent.streaming` (default on) → Task 1 (field) + Task 3 (default flip + wiring). ✅
- Out of scope (correctly absent): runtime tool/skill subscription (WS2), per-agent cost wiring (WS3), autonomous phases (WS4). ✅

**Placeholder scan:** No "TBD"/"TODO"/"handle edge cases"/"similar to". The one repeated edit (Task 3 Step 1) is shown verbatim with all 6 target functions enumerated. ✅

**Type consistency:** `_execute(inner, state, info) -> tuple[str, bool]` and `_stream_run(inner, state, info) -> tuple[str, bool]` agree across Tasks 1–2. `streaming` param name consistent in `__init__`, `create_agent`, and all tests. `_PROGRESS_PREVIEW_CHARS` defined in Task 1, used in Task 2. Store/registry methods (`increment_iteration`, `write_heartbeat`, `write_progress`, `read_directive`, `clear_directive`, `agent_progress`) all match the real signatures in `registry.py` / `store.py` / `broadcaster.py`. ✅
