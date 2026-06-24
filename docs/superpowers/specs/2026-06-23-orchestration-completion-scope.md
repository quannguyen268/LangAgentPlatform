# Orchestration Completion — Scope & Sizing

**Version:** 1.0
**Date:** 2026-06-23
**Status:** Scope approved — pending implementation plan (writing-plans)
**Depends on:** Phase 2A (sub-agents) + Phase 2B-I (swarm/management API) — both DONE
**Scope mode:** Keystone-first. Sizing/sequencing/decisions doc, not implementation-ready detail.

---

## 1. Purpose

The sub-agent and swarm *infrastructure* is built and tested (158 passing tests across
`src/subagent/` + `src/swarm/`), but the orchestration layer is not yet "finished"
against the design vision. Sub-agents run **single-shot** (`DeepAgentsSpawner._run`
calls `inner.ainvoke(state)` once), which blocks every form of runtime coordination.

This document scopes closing the **keystone-first** subset of gaps:

1. **Streaming execution model** — single-shot → incremental driver loop.
2. **Runtime tool / skill / tier subscription** — affect a *running* agent.
3. **Live `agent_progress` events + per-agent cost** — end-to-end.
4. **Autonomous swarm phase advancement** — the harness drives itself.

Explicitly **out of scope** (deferred, see §8): `create_team`/`dissolve_team`/`escalate`
tools, `Rebalancer` wiring, template tool-placeholder cleanup, per-sub-agent permission
interrupts, and true checkpoint-resume recovery.

---

## 2. The keystone insight

Closing these gaps is **one mechanism, not four features**. The store already exposes
the channels needed for runtime coordination — `AgentStore` has `directive`, `inbox`,
`progress`, and `heartbeat` (`src/subagent/store.py`) — and `AgentInfo` already carries
mutable `tools` / `skills` / `tier` / `iteration` / `state` (including `BLOCKED`) fields
(`src/subagent/state.py`). DeepAgents 0.6.1 compiled agents expose `astream` /
`astream_events`.

What is missing is a sub-agent execution loop that **reads** those channels mid-flight.
Today `_run` invokes the inner agent exactly once and never checks the store again, so
`assign_task`, `switch_agent_model`, and any tool subscription cannot reach a live agent.

Therefore the single-shot → streaming change (WS1) is the lynchpin: it is the loop that
every other in-scope feature attaches to.

---

## 3. Decision: execution model

**Chosen: Approach A — outer driver loop with agent rebuild ("step-and-reconfigure").**

The spawner owns a loop that streams the inner agent one turn at a time
(`inner.astream(...)`). Per turn it increments `iteration`, writes `heartbeat`+`progress`,
emits `agent_progress`, and drains `directive`/`inbox`. At a **clean turn boundary** (no
pending tool call), if tools/skills/tier changed it rebuilds the inner DeepAgents instance
with the new toolset, carrying forward the accumulated message history, and continues.

**Rejected:**
- **B — in-graph dynamic-tool middleware.** Depends on middleware rebinding tools per
  model call — fragile, version-coupled to langchain/deepagents internals, and still
  needs a driver loop for heartbeat/progress. Strictly more work and more risk than A.
- **C — stream-only, defer runtime mutation.** Smallest change, but `subscribe_tool` /
  `assign_task` on a running agent still wouldn't work. It is the first half of A; A
  subsumes it.

A stays on supported APIs and delivers the full keystone goal. If rebuild cost ever
mattered, B's trick could be adopted later as an optimization (not anticipated).

---

## 4. Workstreams

### WS1 — Streaming execution model (keystone) · size **L** · ~3–5 d
Rewrite `DeepAgentsSpawner._run` from a single `ainvoke` into an outer driver loop over
`inner.astream(stream_mode="updates")`. Per turn:
- increment `AgentInfo.iteration`;
- write `heartbeat` (real iteration count, not the current hard-coded 0→1) + `progress`;
- emit `agent_progress` via the broadcaster;
- drain `directive` and honor `shutdown` gracefully (replaces the abrupt cancel path).

Keeps the existing `SPAWNING → RUNNING → FINISHED/FAILED` transitions and the
`asyncio.CancelledError` / exception handling already in `_run`.

### WS2 — Runtime tool / skill / tier subscription · size **M** · ~2–4 d
- Add agent-callable tools `subscribe_tool`, `unsubscribe_tool`, `subscribe_skill`
  (currently absent — only 6 of the 12 designed orchestration tools are wired). They
  write directives to the store.
- Make `assign_task` and `switch_agent_model` effective on a *running* agent (today they
  write to the store but the single-shot agent never reads them).
- Driver applies changes at a clean turn boundary: mutate `AgentInfo.tools/skills/tier`,
  rebuild the inner agent with carried-forward messages, resume.
- `assign_task` injects the new task via `inbox` → appended as a `HumanMessage` on the
  next turn.

### WS3 — Live progress + per-agent cost, end-to-end · size **S–M** · ~1–2 d
- Verify the path `spawner → EventBroadcaster → EventHub → WebSocket/channels` for
  `agent_progress` / `agent_complete` (broadcaster exists; needs WS1's emissions).
- Wire `CostTracker` into the loop so `AgentInfo.cost_cents` reflects real token usage
  per turn instead of static `0.0`. Surfaces correctly in `review_cost` and `/v1/cost`.

### WS4 — Autonomous swarm phase advancement · size **M–L** · ~3–5 d
- Add an optional `phase: str | None` field to `AgentTemplate` (must be one of
  `template.phases` when set) — **decision §6.1, option (a)**. Backward compatibility:
  if no agent declares a phase, retain current behavior (all agents spawned at launch);
  if any declares one, the team runs in phased mode.
- Introduce a `SwarmDriver` background task (per team) that builds a `HarnessContext`,
  calls `HarnessRunner.try_advance(ctx)` when the current phase's agents complete, and
  activates the next phase's agents on advance.
- Activate the currently-dormant `Swarm._broadcaster` / `Swarm._workspace` fields
  (`src/swarm/coordinator.py:12-14`) for team-level lifecycle events + `HarnessContext`.
- `FAILED` agents are treated as a gate input and deferred to the existing `RecoveryChain`
  rather than wedging the harness.

### Cross-cutting (folded into each WS)
- Config flags: `subagent.streaming` (default on once WS1 lands), `swarm.autonomous`.
- Tests per workstream (see §7).
- A short "future work" pointer left in each deferred area (§8).

---

## 5. Dependencies & sequencing

```
WS1 (streaming loop)  ──┬──► WS2 (runtime subscription)
   [foundation]         │
                        ├──► WS3 (progress + cost)   ← largely emitted inside WS1
                        │
                        └──► WS4 (autonomous swarm)   ← needs reliable completion events
```

WS1 ships first and alone. WS2 / WS3 / WS4 then proceed largely in parallel; WS3 is
half-complete the moment WS1 lands.

| Workstream | Size | Est. |
|---|---|---|
| WS1 — streaming loop | L | ~3–5 d |
| WS2 — runtime subscription | M | ~2–4 d |
| WS3 — progress + cost | S–M | ~1–2 d |
| WS4 — autonomous swarm | M–L | ~3–5 d |
| **Total** | | **~9–16 dev-days** |

Estimates are rough order-of-magnitude for one engineer, including tests.

---

## 6. Key design decisions

### 6.1 Phase→agent mapping (WS4) — RESOLVED: option (a)
The template has a flat `phases` list and a flat `agents` list with no binding between
them (`src/swarm/templates.py:46`). **Chosen:** add an optional `phase` field per agent so
the driver activates agents per phase (true `plan → execute → verify` execution).
Rejected (b) "all agents alive throughout, phases as pure checkpoints" — it makes phase
advancement cosmetic. Backward compatibility rule in WS4 above.

### 6.2 Reconfigure boundary (WS2) — RESOLVED
Apply tool/skill/tier changes only between turns when no tool-call is pending, so swapping
the toolset cannot orphan a `tool_call` / `tool_result` message pair. Low-risk.

### 6.3 Stream mode (WS1) — RESOLVED
Use `inner.astream(stream_mode="updates")` rather than low-level `astream_events`, to
minimize coupling to LangGraph's internal event shapes (see risk §7).

---

## 7. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Message-history corruption when tools are swapped mid-run | Reconfigure only at clean boundaries (§6.2); add a test that swaps tools mid-run and asserts message validity. |
| Stream-parsing fragility across langchain/deepagents versions | Prefer `stream_mode="updates"` (§6.3); isolate parsing in one helper; pin a test against the current version. |
| Recovery × autonomous-phase interaction wedging the harness | Driver treats `FAILED` as a gate input and defers to the existing `RecoveryChain`; harness never blocks indefinitely on a dead agent. |
| `directive`/`inbox` drain races with the agent loop | Drain only at turn boundaries on the loop's own task; document `InMemoryStore` vs persistent-store ordering semantics. |
| Per-turn cost attribution accuracy | Read token usage from stream metadata where available; fall back to end-of-run totals; assert non-decreasing `cost_cents`. |

### Testing strategy (per workstream)
- **WS1:** loop runs N turns, `iteration` increments, heartbeat/progress written each turn,
  `shutdown` directive ends the loop gracefully.
- **WS2:** subscribe/unsubscribe/skill/tier directives applied at next clean boundary;
  mid-run tool swap preserves message validity; `assign_task` reaches a live agent.
- **WS3:** `agent_progress` reaches a fake `EventHub`; `cost_cents` is real and monotonic.
- **WS4:** phased template advances on completion; gate blocks until satisfied; a `FAILED`
  agent routes to recovery without wedging; legacy (no-phase) template still launches.

---

## 8. Explicitly deferred (out of scope here)

Each gets a one-line "future work" pointer in code where relevant:
- `create_team` / `dissolve_team` / `escalate` agent-callable tools.
- `Rebalancer` wiring into the recovery chain (`src/subagent/rebalance.py`).
- Team template tool-placeholder cleanup (`research.toml`, `software-dev.toml` reference a
  not-yet-existing file-ops tool family).
- Per-sub-agent permission interrupts (`interrupt_on` + `BLOCKED` state on sub-agents).
- True checkpoint-resume recovery (today recovery respawns fresh with a text
  `recovery_context`, not a real checkpoint resume).

### 8.1 WS1 follow-ups (found in final review)

Now that streaming makes `iteration` load-bearing, two adjacent issues are worth tracking:
- **Iteration not reset on respawn** — `RecoveryExecutor` reuses the same `AgentInfo`, so a
  recovered agent resumes its old `iteration` count and can re-trip `max_iterations` on the
  next health tick. Fix when wiring recovery alongside WS2/streaming (reset `iteration` on respawn).
- **`recall_agent` shutdown is racy** — `src/subagent/tools.py` writes the `shutdown` directive
  then immediately `deregister`s (cancels), so the cooperative graceful-stop path WS1 added
  rarely wins. Wire `recall_agent` to await the cooperative stop before cancelling (WS2 or a
  follow-up).

---

## 9. Success criteria

- A spawned sub-agent streams `agent_progress` events and shows an incrementing
  `iteration` and real `cost_cents` in `monitor_agents` / `/v1/agents`.
- `subscribe_tool` / `assign_task` / `switch_agent_model` issued against a *running*
  agent take effect on its next turn.
- A phased team launched via `Swarm.launch` advances `plan → execute → verify` on its own,
  gated by `PhaseGate`s, with team lifecycle events emitted.
- All existing 158 orchestration tests still pass; new tests per §7 added and green.
