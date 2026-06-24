# WS3 — Live Progress + Per-Agent Cost (End-to-End) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a running sub-agent's `cost_cents` reflect real per-step token usage (instead of the static `0.0`), so `monitor_agents`, `review_cost`, and the `agent_progress`/`agent_complete` events that already stream to the WebSocket carry true cost.

**Architecture:** WS1's streaming loop already emits `agent_progress` per step and `agent_complete` at the end, both carrying `info.cost_cents` — but that value never changes from `0.0` because nothing records usage. WS3 gives the spawner a `CostTracker`, and in `_run_segment` reads `usage_metadata` off each *newly produced* `AIMessage` (tracked by a `counted` index to avoid double-counting the cumulative `stream_mode="values"` snapshots), records it, and accumulates `info.cost_cents`. Since the event path already flows (WS1) and reads `info.cost_cents`, the cost becomes live end-to-end with no changes to the broadcaster or WebSocket.

**Tech Stack:** Python 3.13, LangChain `AIMessage.usage_metadata` / `.response_metadata`, the existing `CostTracker` (`src/observability/cost.py`), `EventHub` (`src/api/websocket.py`), pytest.

**Spec:** `docs/superpowers/specs/2026-06-23-orchestration-completion-scope.md` §4 WS3. Depends on WS1 (streaming loop) + WS2 (segment loop) — both merged on this branch.

### Design decisions
1. **No double-counting.** `stream_mode="values"` yields cumulative message snapshots. `_run_segment` dedupes with a dual guard: a `counted` slice index **and** a `costed_ids` set of `id(m)` object identities seeded from the echo chunk. (Implementation note: `counted` stays `0` after the echo rather than `len(echo)`, because the test `_astream_factory` mocks yield non-cumulative chunks while real LangGraph yields cumulative ones — `costed_ids` is the guard that covers both, since langgraph's `add_messages` reuses prior message objects so their `id()` is stable across snapshots and across the outer loop's carried-forward history.) Each `AIMessage` is costed exactly once in both environments.
2. **Token counts are always accurate; cents are best-effort.** `usage_metadata` gives exact input/output tokens. `CostTracker` computes cents only when the message's model name matches a `DEFAULT_PRICING` key (returns `0.0` otherwise — graceful). Exact model-string → pricing-key normalization (e.g. dated model ids) is a pre-existing `CostTracker` concern, NOT in scope here; this plan records what the model reports.
3. **Sub-agent cost attribution.** Recorded with `agent_id=info.agent_id` and `tier=info.tier` (the meaningful axes for sub-agents). `user_id` is a `"subagent"` sentinel — the spawner doesn't carry the spawning user's id today; threading it is future work, noted below.
4. **Event path unchanged.** The broadcaster/EventHub/WebSocket wiring already streams `agent_progress`/`agent_complete` with `cost_cents`/`cost_total_cents`. WS3 only makes the underlying value real; no changes to `broadcaster.py` or `websocket.py`.

---

## File Structure

| File | Responsibility | Change |
|------|----------------|--------|
| `src/subagent/spawner.py` | Per-step cost recording in the streaming loop | Modify — add `cost_tracker` ctor arg, `_record_costs` helper, count-and-record in `_run_segment` |
| `src/agent.py` | `create_agent` wiring | Modify — pass `cost_tracker=cost_tracker` to `DeepAgentsSpawner` |
| `tests/test_spawner.py` | Spawner tests | Modify — add cost-recording + no-double-count tests |
| `tests/test_agent_swarm_wiring.py` | Wiring test | Modify — assert the spawner receives the cost tracker |

---

## Task 1: Record per-step cost in the streaming loop

**Files:**
- Modify: `src/subagent/spawner.py`
- Test: `tests/test_spawner.py`

- [ ] **Step 1: Write the failing tests**

Add a helper near the top of `tests/test_spawner.py` (after the existing imports) for building an AIMessage that carries usage:

```python
def _ai_with_usage(text, model="claude-sonnet-4-6", in_tok=100, out_tok=50):
    """An AIMessage carrying usage_metadata + response_metadata model name."""
    return AIMessage(
        content=text,
        usage_metadata={"input_tokens": in_tok, "output_tokens": out_tok,
                        "total_tokens": in_tok + out_tok},
        response_metadata={"model_name": model},
    )
```

Then append:

```python
@pytest.mark.asyncio
async def test_streaming_records_cost_per_step(monkeypatch):
    """Each AIMessage with usage_metadata accrues real cost on the agent + tracker."""
    from src.observability.cost import CostTracker
    store = InMemoryStore()
    registry = SubAgentRegistry(store)
    broadcaster = EventBroadcaster(None)
    cost_tracker = CostTracker()

    inner = MagicMock()
    inner.astream = _astream_factory([
        {"messages": [_ai_with_usage("step1")]},
        {"messages": [_ai_with_usage("step1"), _ai_with_usage("step2")]},
    ])
    monkeypatch.setattr("src.subagent.spawner.create_deep_agent", lambda **kw: inner)

    spawner = DeepAgentsSpawner(
        registry=registry, broadcaster=broadcaster,
        base_model=MagicMock(), tools_by_name={}, streaming=True,
        cost_tracker=cost_tracker,
    )
    info = AgentInfo(agent_id="a1", name="n", role="executor", task="t",
                     tier="standard", tools=[], skills=[])
    registry.register(info, asyncio.create_task(asyncio.sleep(0)))
    task = await spawner.spawn(info)
    registry._tasks["a1"] = task
    await asyncio.wait_for(task, timeout=5.0)

    # claude-sonnet-4-6 = (300, 1500) cents per 1M. Two steps:
    #   each step: (100*300 + 50*1500)/1e6 = (30000+75000)/1e6 = 0.105 cents
    #   two steps -> 0.21 cents
    assert registry.get_agent("a1").cost_cents == pytest.approx(0.21, rel=1e-3)
    by_agent = cost_tracker.by_agent()
    assert by_agent["a1"]["total_tokens"] == 300        # (150)*2
    assert by_agent["a1"]["calls"] == 2


@pytest.mark.asyncio
async def test_streaming_cost_not_double_counted(monkeypatch):
    """An AIMessage that reappears in later cumulative snapshots is costed once."""
    from src.observability.cost import CostTracker
    store = InMemoryStore()
    registry = SubAgentRegistry(store)
    broadcaster = EventBroadcaster(None)
    cost_tracker = CostTracker()

    ai1 = _ai_with_usage("a1msg")
    # ai1 reappears in chunk 2 alongside a tool result (no new AIMessage there).
    from langchain_core.messages import ToolMessage
    inner = MagicMock()
    inner.astream = _astream_factory([
        {"messages": [ai1]},
        {"messages": [ai1, ToolMessage(content="tool out", tool_call_id="x")]},
    ])
    monkeypatch.setattr("src.subagent.spawner.create_deep_agent", lambda **kw: inner)

    spawner = DeepAgentsSpawner(
        registry=registry, broadcaster=broadcaster,
        base_model=MagicMock(), tools_by_name={}, streaming=True,
        cost_tracker=cost_tracker,
    )
    info = AgentInfo(agent_id="a1", name="n", role="executor", task="t",
                     tier="standard", tools=[], skills=[])
    registry.register(info, asyncio.create_task(asyncio.sleep(0)))
    task = await spawner.spawn(info)
    registry._tasks["a1"] = task
    await asyncio.wait_for(task, timeout=5.0)

    # ai1 costed exactly once: 0.105 cents, one call.
    assert cost_tracker.by_agent()["a1"]["calls"] == 1
    assert registry.get_agent("a1").cost_cents == pytest.approx(0.105, rel=1e-3)


@pytest.mark.asyncio
async def test_streaming_no_cost_tracker_is_safe(monkeypatch):
    """With no cost tracker, the loop runs fine and cost stays 0."""
    store = InMemoryStore()
    registry = SubAgentRegistry(store)
    broadcaster = EventBroadcaster(None)

    inner = MagicMock()
    inner.astream = _astream_factory([{"messages": [_ai_with_usage("x")]}])
    monkeypatch.setattr("src.subagent.spawner.create_deep_agent", lambda **kw: inner)

    spawner = DeepAgentsSpawner(
        registry=registry, broadcaster=broadcaster,
        base_model=MagicMock(), tools_by_name={}, streaming=True,
    )  # no cost_tracker
    info = AgentInfo(agent_id="a1", name="n", role="executor", task="t",
                     tier="standard", tools=[], skills=[])
    registry.register(info, asyncio.create_task(asyncio.sleep(0)))
    task = await spawner.spawn(info)
    registry._tasks["a1"] = task
    await asyncio.wait_for(task, timeout=5.0)

    assert registry.get_agent("a1").cost_cents == 0.0


@pytest.mark.asyncio
async def test_agent_progress_event_carries_real_cost(monkeypatch):
    """agent_progress events report the accumulated cost_cents."""
    from src.observability.cost import CostTracker
    store = InMemoryStore()
    registry = SubAgentRegistry(store)
    hub = EventHub()
    broadcaster = EventBroadcaster(hub)
    cost_tracker = CostTracker()

    events = []
    async def sub():
        async for ev in hub.subscribe():
            events.append(ev)
            if ev.type == "agent_complete":
                break
    sub_task = asyncio.create_task(sub())
    await asyncio.sleep(0.05)

    inner = MagicMock()
    inner.astream = _astream_factory([{"messages": [_ai_with_usage("step1")]}])
    monkeypatch.setattr("src.subagent.spawner.create_deep_agent", lambda **kw: inner)

    spawner = DeepAgentsSpawner(
        registry=registry, broadcaster=broadcaster,
        base_model=MagicMock(), tools_by_name={}, streaming=True,
        cost_tracker=cost_tracker,
    )
    info = AgentInfo(agent_id="a1", name="n", role="executor", task="t",
                     tier="standard", tools=[], skills=[])
    registry.register(info, asyncio.create_task(asyncio.sleep(0)))
    task = await spawner.spawn(info)
    registry._tasks["a1"] = task
    await asyncio.wait_for(task, timeout=5.0)
    await asyncio.wait_for(sub_task, timeout=2.0)

    progress = [e for e in events if e.type == "agent_progress"]
    assert progress and progress[-1].data["cost_cents"] == pytest.approx(0.105, rel=1e-3)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_spawner.py -k "cost or double_counted" -v`
Expected: FAIL — `DeepAgentsSpawner.__init__` has no `cost_tracker`; no cost is recorded (`cost_cents` stays 0.0).

- [ ] **Step 3: Implement cost recording**

In `src/subagent/spawner.py`:

(a) Add `cost_tracker` to `__init__` (after `skills_dirs`), storing it:
```python
        streaming: bool = True,
        workspace: str | None = None,
        skills_dirs: list[str] | None = None,
        cost_tracker: Any = None,
    ):
        self._registry = registry
        self._broadcaster = broadcaster
        self._base_model = base_model
        self._tools_by_name = tools_by_name
        self._streaming = streaming
        self._workspace = workspace
        self._skills_dirs = skills_dirs
        self._cost_tracker = cost_tracker
```

(b) Add a `_record_costs` helper (place near `_skills_hint`):
```python
    def _record_costs(self, info: AgentInfo, new_messages: list) -> None:
        """Record usage for any newly produced AIMessages, accruing info.cost_cents.

        Token counts come from ``usage_metadata``; the cents are computed by the
        CostTracker from the message's model name (0.0 if the model is not in the
        pricing table). No-op when no cost tracker is wired.
        """
        if self._cost_tracker is None:
            return
        for m in new_messages:
            if not isinstance(m, AIMessage):
                continue
            usage = getattr(m, "usage_metadata", None)
            if not usage:
                continue
            meta = m.response_metadata or {}
            model = meta.get("model_name") or meta.get("model") or ""
            cost = self._cost_tracker.record(
                provider="",
                model=model,
                prompt_tokens=usage.get("input_tokens", 0) or 0,
                completion_tokens=usage.get("output_tokens", 0) or 0,
                user_id="subagent",   # spawning user id not threaded yet (future work)
                tier=info.tier,
                agent_id=info.agent_id,
            )
            info.cost_cents += cost
```

(c) In `_run_segment`, track a `counted` index and record costs for new messages each step. Replace the loop body so it reads (note the `counted` init in the echo branch and the cost call before the heartbeat/progress so the reported `cost_cents` is current):
```python
        agent_id = info.agent_id
        store = self._registry.agent_store
        state = {"messages": messages}
        final_state = state
        stopped = False
        saw_step = False
        counted = 0

        async with aclosing(inner.astream(state, stream_mode="values")) as stream:
            first = True
            async for chunk in stream:
                final_state = chunk
                msgs = chunk.get("messages", [])
                if first:
                    # stream_mode="values" echoes the input state first — not a step.
                    # Everything already present was costed in a prior segment/step.
                    first = False
                    counted = len(msgs)
                    continue
                saw_step = True
                self._record_costs(info, msgs[counted:])
                counted = len(msgs)
                self._registry.increment_iteration(agent_id)
                iteration = self._registry.get_agent(agent_id).iteration
                preview = _extract_last_text(msgs)[:_PROGRESS_PREVIEW_CHARS]

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
Expected: PASS — the 4 new cost tests + all prior spawner tests. (Prior tests use `_astream_factory` with plain `AIMessage`s that have no `usage_metadata`, so `_record_costs` is a no-op for them and `cost_cents` stays 0.0 — their assertions are unaffected.)

- [ ] **Step 5: Commit**

```bash
git add src/subagent/spawner.py tests/test_spawner.py
git commit -m "feat(subagent): record real per-step token cost in the streaming loop"
```

---

## Task 2: Wire the cost tracker into `create_agent`

**Files:**
- Modify: `src/agent.py`
- Test: `tests/test_agent_swarm_wiring.py`

- [ ] **Step 1: Write the failing wiring test**

In `tests/test_agent_swarm_wiring.py`, add a behavioral test that builds the agent (mocked model/graph, as the existing `test_ws2_known_tools_excludes_orchestration_tools` does) and captures the kwargs the spawner was constructed with:

```python
@pytest.mark.asyncio
async def test_ws3_spawner_receives_cost_tracker(monkeypatch, tmp_path):
    """create_agent passes the shared CostTracker into the spawner."""
    from unittest.mock import MagicMock
    import src.agent as agent_mod
    import src.subagent.spawner as spawner_mod
    from src.config import AppConfig

    monkeypatch.setattr(agent_mod, "init_chat_model", lambda *a, **k: MagicMock())
    monkeypatch.setattr(agent_mod, "create_deep_agent", lambda **k: MagicMock())
    # Middleware build needs a cheap model under default config — stub it out
    # (orthogonal to this wiring assertion).
    monkeypatch.setattr(agent_mod, "_build_middleware", lambda config: [])

    captured = {}
    real_init = spawner_mod.DeepAgentsSpawner.__init__
    def capturing_init(self, *args, **kwargs):
        captured["cost_tracker"] = kwargs.get("cost_tracker")
        real_init(self, *args, **kwargs)
    monkeypatch.setattr(spawner_mod.DeepAgentsSpawner, "__init__", capturing_init)

    cfg = AppConfig()
    cfg.agent.workspace = str(tmp_path / "ws")
    cfg.agent.data_dir = str(tmp_path / "data")
    cfg.subagent.enabled = True
    cfg.swarm.enabled = False
    cfg.model_router.enabled = False

    bundle = await agent_mod.create_agent(cfg)

    assert captured["cost_tracker"] is not None
    # Same tracker the bundle exposes (shared with review_cost / API).
    assert captured["cost_tracker"] is bundle.cost_tracker
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_agent_swarm_wiring.py -k ws3 -v`
Expected: FAIL — the spawner is constructed without `cost_tracker`, so `captured["cost_tracker"]` is `None`.

- [ ] **Step 3: Wire it in `create_agent`**

In `src/agent.py`, the `DeepAgentsSpawner(...)` construction (inside `if config.subagent.enabled:`) currently passes `registry/broadcaster/base_model/tools_by_name/streaming/workspace/skills_dirs`. Add `cost_tracker=cost_tracker` (the `cost_tracker = CostTracker()` already created earlier in the function and also passed to `init_orchestration_tools`):
```python
        spawner = DeepAgentsSpawner(
            registry=subagent_registry,
            broadcaster=broadcaster,
            base_model=model,
            tools_by_name=tools_by_name,
            streaming=config.subagent.streaming,
            workspace=workspace,
            skills_dirs=skills_dirs if skills_dirs else None,
            cost_tracker=cost_tracker,
        )
```

- [ ] **Step 4: Run the wiring test + regression sweep**

Run: `python -m pytest tests/test_agent_swarm_wiring.py -v && python -m pytest tests/ -k "subagent or swarm or spawn or agent_swarm or cost or config" -q`
Expected: PASS — wiring test green, no regressions.

- [ ] **Step 5: Commit**

```bash
git add src/agent.py tests/test_agent_swarm_wiring.py
git commit -m "feat(subagent): wire CostTracker into the spawner for live per-agent cost"
```

---

## Self-Review

**Spec coverage (scope doc §4 WS3):**
- "Wire CostTracker into the loop so AgentInfo.cost_cents reflects real token usage per turn instead of static 0.0" → Task 1 (`_record_costs` + per-step counting). ✅
- "Verify the path spawner → EventBroadcaster → EventHub → WebSocket for agent_progress/agent_complete" → the path already flows (WS1); Task 1's `test_agent_progress_event_carries_real_cost` asserts the live cost reaches a real `EventHub` subscriber; `agent_complete` already carries `info.cost_cents` via the unchanged epilogue. ✅
- create_agent wiring → Task 2. ✅
- Out of scope (correctly absent): WS4 autonomous phases; exact model-string→pricing normalization; threading the spawning user_id (noted as future work).

**Placeholder scan:** None. Cost arithmetic in the tests is computed explicitly from `DEFAULT_PRICING` so the assertions are concrete.

**Type consistency:** `cost_tracker` ctor arg (`Any`, default `None`) and `self._cost_tracker` consistent; `_record_costs(info, new_messages)` defined in Task 1 and called in `_run_segment`; `CostTracker.record(...)` args match `src/observability/cost.py`; `counted` index logic costs each AIMessage once. The `agent_complete` event already reads `info.cost_cents` (unchanged WS1 epilogue), so the end value is live with no epilogue change.

**Known limitations (logged, not silently dropped):** sub-agent cost is attributed to a `"subagent"` user-id sentinel (real user threading is future work); cents are `0.0` when the reported model name isn't a `DEFAULT_PRICING` key (token counts are still accurate). Both are recorded in §Design decisions.
