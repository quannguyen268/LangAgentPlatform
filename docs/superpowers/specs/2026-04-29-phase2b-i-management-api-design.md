# Phase 2B-I: Management API (Read-Only) — Design Spec

**Date:** 2026-04-29
**Phase:** 2B-I (first slice of Phase 2B)
**Predecessor:** Phase 2A (`v0.4.0-phase2a`)
**Successor:** Phase 2B-II (Web UI v1) — depends on this slice
**Spec reference:** `docs/superpowers/specs/2026-04-15-langagent-platform-design.md` §20

---

## 1. Goal

Add 6 read-only HTTP endpoints to the existing aiohttp app in `src/channels/api.py` so a future Web UI (Phase 2B-II) can mirror platform state. The API exposes existing in-memory and persisted state — it does **not** add mutation paths; mutation continues to flow through the master agent's orchestration tools (`spawn_agent`, `recall_agent`, etc.).

**Out of scope (deferred to other phases):**
- Mutation endpoints (POST/DELETE/PATCH for `/v1/agents`, `/v1/teams`, etc.) — Phase 2B-II if needed, otherwise via chat tools.
- Authentication (JWT, multi-user) — Phase 2B-I.5 if needed; this slice ships localhost-bind only.
- Discord / Slack channels — Phase 2B-III.
- Web UI — Phase 2B-II.
- Task-board projection (`GET /v1/teams/{id}/board`) — designed alongside the UI in Phase 2B-II.

## 2. Decomposition rationale

The original Phase 2B (per spec §20.8) bundled chat channels + management API + Web UI. Each is a multi-week subsystem; bundling produced a 30+ task plan that drifts. This spec slices off the API extensions because:

1. **Smallest** of the three (~10 tasks vs ~15 for channels, ~30 for Web UI).
2. **Unblocks** Phase 2B-II — the UI is useless without endpoints.
3. **Pure backend Python** — direct reuse of Phase 2A's Swarm/HarnessRunner, Phase 1B's GitStore/CostTracker, Phase 1C's SubAgentRegistry.

Order: **Phase 2B-I (API) → Phase 2B-II (Web UI) → Phase 2B-III (Discord/Slack)**.

## 3. Endpoints

| Method | Path | Backed by | Status |
|---|---|---|---|
| GET | `/v1/agents` | `SubAgentRegistry.list_agents()` | new |
| GET | `/v1/agents/{id}` | `SubAgentRegistry.get_agent()` | new |
| GET | `/v1/teams` | `Swarm._teams` (Swarm wired into `create_agent`) | new |
| GET | `/v1/tasks` | `cron._load_tasks()` (structured) | new |
| GET | `/v1/config` | redacted `AppConfig.model_dump()` | new |
| GET | `/v1/cost/breakdown` | existing — contract test only | audit |

`/v1/teams/{id}/board` is **not** included; the board projection is designed in Phase 2B-II once the UI's needs are concrete.

`/v1/memory*` and `/v1/cost` (summary) already shipped in Phase 1B; this spec extends, does not duplicate.

## 4. Response shapes

All responses are `application/json`, 200 on success, OpenAI-style error envelope on failure. All timestamps are ISO-8601 UTC.

### 4.1 `GET /v1/agents`
```json
{
  "agents": [
    {
      "agent_id": "agent-a3f1b2c4",
      "name": "backend-dev",
      "role": "executor",
      "tier": "standard",
      "state": "running",
      "task": "Implement endpoints from plan.md",
      "tools": ["read_file", "write_file"],
      "skills": ["commit"],
      "iteration": 3,
      "cost_cents": 12.4,
      "retry_count": 0,
      "created_at": "2026-04-23T14:02:11Z",
      "last_heartbeat": "2026-04-23T14:05:42Z",
      "finished_at": null
    }
  ]
}
```
``finished_at`` is null for agents that have not terminated; ISO-8601 UTC for FINISHED or FAILED agents. Useful so UIs can compute "how long did this run?"

### 4.2 `GET /v1/agents/{id}`
Same shape as one element of the `agents` array above, plus an `error` field (most recent error string from `AgentInfo.error` if `retry_count > 0`, else null). 404 with OpenAI error envelope when unknown.

### 4.3 `GET /v1/teams`
```json
{
  "teams": [
    {
      "team_id": "team-7e2c1a89",
      "phases": ["plan", "execute", "verify"],
      "current_phase": "execute",
      "is_finished": false,
      "agent_count": 3,
      "agent_ids": ["agent-a3f1...", "agent-b8d2...", "agent-c4e9..."]
    }
  ]
}
```
`agent_ids` requires `Swarm` to track team→agent mapping. Add `self._team_agents: dict[str, list[str]]` in `Swarm.launch()` (folded into the same task that wires `Swarm` into `create_agent`).

### 4.4 `GET /v1/tasks`
```json
{
  "tasks": [
    {
      "task_id": "task-xyz",
      "prompt": "Daily standup summary",
      "schedule_type": "cron",
      "schedule_value": "0 9 * * *",
      "model_tier": "standard",
      "next_run": "2026-04-24T09:00:00Z",
      "created_at": "2026-04-20T11:23:00Z"
    }
  ]
}
```
Refactor `src/tools/cron._load_tasks()` to return structured data; the existing `list_tasks` @tool wraps it with formatting.

### 4.5 `GET /v1/config`
```json
{
  "agent": {"workspace": "./workspace", "data_dir": "./data"},
  "provider": {"name": "anthropic", "model": "claude-opus-4-7", "api_key": "***REDACTED***"},
  "subagent": {"enabled": true, "max_retries": 1},
  "swarm": {"enabled": false}
}
```

### 4.6 `GET /v1/cost/breakdown`
Existing endpoint. Audit shape vs spec §20.6 and pin with a contract test; no behavior change unless drift is found.

### 4.7 Error envelope (all endpoints)
```json
{"error": {"message": "Agent not found", "type": "not_found", "code": "agent_not_found"}}
```
Helpers in `src/api/errors.py`: `not_found(detail)`, `bad_request(detail)`, `internal_error(detail, exc=None)`. Matches the existing `/v1/chat/completions` error style.

### 4.8 Disabled-subsystem behavior

When the underlying subsystem is disabled (`config.subagent.enabled=false` for agents, `config.swarm.enabled=false` for teams), the corresponding endpoints return `200` with an empty list rather than 404 or 503. Rationale: callers (Web UI) get a uniform "nothing is happening" rendering path. The disabled state is observable via `GET /v1/config`.

- `GET /v1/agents` with no registry → `{"agents": []}`
- `GET /v1/agents/{id}` with no registry → 404 (consistent with "agent does not exist")
- `GET /v1/teams` with no Swarm → `{"teams": []}`
- `GET /v1/tasks` with no scheduler enabled → `{"tasks": []}`

## 5. Auth & network

**Localhost-only.** No HTTP authentication. Sensitive data (memory contents, cost by user_id, config) is protected only by network boundary.

- `APIChannel.start()` emits a startup `logger.warning` when `config.channels.api.host` is not in `{"127.0.0.1", "localhost", "::1"}`. This is observable but not enforced — sysadmins know what they are doing.
- Future Phase 2B-I.5 may add an optional static bearer token middleware without touching the endpoint handlers.

## 6. Config redaction

Hybrid policy in `src/api/redaction.py`:

1. **Suffix match (default)** — values whose key matches `*_key`, `*_token`, `*_secret`, `*_password`, or contains `credentials` are replaced with `"***REDACTED***"`. Recursive over nested dicts.
2. **Pydantic annotation (escape hatch)** — `Field(..., json_schema_extra={"sensitive": True})` flags fields the suffix rules miss. The redactor walks the model schema to collect such paths.
3. **Combined** — a field is redacted if either rule fires.

Tests pin the policy:
- Any `*_key` field is redacted in the response.
- An explicitly `sensitive=True` field with a non-matching name is redacted.
- A field matching neither rule is preserved.
- Redaction is recursive (nested `provider.api_key` → redacted; `mcp_servers.foo.token` → redacted).

Initial annotation pass touches ~6 fields (provider/gateway/web/transcription/telegram/auth) where the field name does not match the suffix list.

## 7. Architecture & files

### New files
```
src/api/management.py         # Handlers for /v1/agents, /v1/teams, /v1/tasks, /v1/config
src/api/errors.py             # OpenAI-style error envelope helpers
src/api/redaction.py          # Config redactor (hybrid policy)
tests/test_api_errors.py
tests/test_api_redaction.py
```

### Modified files
```
src/agent.py                  # Introduce PlatformBundle; instantiate Swarm when enabled
src/main.py                   # Unpack PlatformBundle; pass Swarm to APIChannel
src/swarm/coordinator.py      # Add _team_agents tracking
src/channels/api.py           # Register management routes; non-loopback host WARN
src/api/routes.py             # Re-export setup function (or absorb into management.py)
src/tools/cron.py             # Refactor _load_tasks to return structured data
src/config.py                 # Annotate ~6 sensitive Field(...) declarations
tests/test_api_management.py  # Extend with new endpoint contract tests
tests/test_swarm_coordinator.py  # Test _team_agents mapping
```

### `PlatformBundle` dataclass

```python
@dataclass(frozen=True)
class PlatformBundle:
    agent: Any
    checkpointer: Any
    mcp_client: Any | None
    subagent_registry: SubAgentRegistry | None
    cost_tracker: CostTracker
    recovery_executor: RecoveryExecutor | None
    broadcaster: EventBroadcaster | None
    swarm: Swarm | None  # 2B-I addition
```

Replaces the current 7-tuple return from `create_agent`. Call sites in `main.py` change from positional unpack to attribute access. T13 reviewer flagged tuple-shape fragility; this retires it.

### Route registration flow

```
main.py
  ├─ create_agent(config) → PlatformBundle
  ├─ event_hub = EventHub() (only when channels.api.enabled)
  ├─ bundle.broadcaster.set_hub(event_hub)
  └─ APIChannel(workspace, cost_tracker, event_hub,
                subagent_registry=bundle.subagent_registry,
                swarm=bundle.swarm)
        └─ .start()
            ├─ existing routes (/v1/chat/completions, /v1/models, /health)
            ├─ existing memory + cost routes (Phase 1B)
            └─ NEW: setup_management_routes(app, registry, swarm, config)
```

`setup_management_routes` lives in `src/api/management.py`. It takes the dependencies it needs as arguments rather than reaching through globals.

## 8. Testing strategy

Per Phase 2A pattern: aiohttp test client fixtures.

- **Unit tests** for `errors.py` and `redaction.py` (no HTTP layer, just function-level).
- **Endpoint contract tests** via `aiohttp_client` fixture: each endpoint gets a happy-path test (200 + shape) and a failure test (404 / 500 / shape) where applicable.
- **Integration test** for Swarm launch → `GET /v1/teams` returning the launched team.
- **Per-task review cycle** preserved from Phase 2A: spec-compliance review + code-quality review in parallel after each implementer landing.

## 9. Exit criteria

- 5 new endpoints + 1 audited endpoint live behind localhost binding.
- `PlatformBundle` retires the `create_agent` tuple return.
- `Swarm` instantiated when `config.swarm.enabled`.
- Sensitive fields redacted, with both suffix-match and explicit-annotation pathways tested.
- Full test suite at the existing 6-pre-existing-fail baseline, no new failures.
- Plan README updated to mark Phase 2B-I done.
- Tag `v0.5.0-phase2b-i` pushed.

## 10. Estimated task count

10 tasks. Detailed task breakdown moves to the implementation plan at `docs/superpowers/plans/2026-04-29-phase2b-i-management-api.md` (created via `superpowers:writing-plans` after this spec is approved).

## 11. Risks & mitigations

| Risk | Mitigation |
|---|---|
| `PlatformBundle` refactor cascades into untested call sites | Phase 2A T13 review confirmed no test unpacks `create_agent`'s return. Grep again before refactor; update any new call sites that landed since. |
| `Swarm._team_agents` requires touching `coordinator.py` which is already polished | Single one-line addition in `launch()`; existing tests still pass; new test for the mapping. |
| Config redactor false-positives (redacts a non-secret named `*_key`) | Acceptable trade-off for the personal-use scope; explicit-allowlist escape hatch can be added in 2B-I.5 if needed. |
| `cron._load_tasks` refactor breaks the `list_tasks` @tool | Refactor returns structured data; @tool wraps with `json.dumps` or pretty-print. Existing tool test pinned; new test for the structured return. |
| Localhost-warn is too quiet (sysadmin misses it) | Logged at WARNING level; documented in README. Bind enforcement (refuse to start if non-loopback + no auth) is deferred to 2B-I.5. |

---

**End of spec.**
