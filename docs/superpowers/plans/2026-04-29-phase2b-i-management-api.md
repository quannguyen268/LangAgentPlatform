# Phase 2B-I: Management API (Read-Only) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 5 new read-only HTTP endpoints (`/v1/agents`, `/v1/agents/{id}`, `/v1/teams`, `/v1/tasks`, `/v1/config`) plus a contract audit of the existing `/v1/cost/breakdown` so a future Web UI (Phase 2B-II) can mirror platform state. Localhost-bind only, no auth, OpenAI-style error envelope, hybrid config redaction.

**Architecture:** A new `src/api/management.py` module hosts handlers for the 4 new groups; an `errors.py` module provides OpenAI-style error envelope helpers; a `redaction.py` module runs the hybrid suffix-match + Pydantic-annotation policy on `AppConfig.model_dump()`. `create_agent` retires its 7-tuple return in favor of a frozen `PlatformBundle` dataclass; `Swarm` is finally instantiated when `config.swarm.enabled` (deferred from Phase 2A T14) and threaded through the bundle. `APIChannel` registers the new route group alongside the existing memory + cost routes from Phase 1B, and emits a startup `WARN` when the configured host is non-loopback.

**Tech Stack:** Python 3.11+, aiohttp (REST), Pydantic v2, dataclasses, croniter (existing — for `next_run` computation in tasks endpoint), pytest + `aiohttp_client` fixture.

**Spec Reference:** `docs/superpowers/specs/2026-04-29-phase2b-i-management-api-design.md`

**Prerequisites:** Phase 2A complete (`v0.4.0-phase2a`, 806 tests passing). Depends on:
- `src.subagent.SubAgentRegistry` — agent state source
- `src.swarm.Swarm`, `src.swarm.HarnessRunner` — team state source
- `src.tools.cron._load_tasks` — scheduled-task source (will be refactored to return structured data)
- `src.config.AppConfig` — config source for `/v1/config`
- `src.api.websocket.EventHub` — already wired into `EventBroadcaster` via `set_hub()` (Phase 2A T13 polish)
- `src.observability.cost.CostTracker` — `/v1/cost/breakdown` already exists; this plan only adds a contract test

---

## File Structure

### New files

```
src/api/management.py          # Handlers for /v1/agents, /v1/teams, /v1/tasks, /v1/config
src/api/errors.py              # OpenAI-style error envelope helpers
src/api/redaction.py           # Config redactor (hybrid: suffix match + Pydantic sensitive=True)

tests/test_api_errors.py
tests/test_api_redaction.py
tests/test_api_management_v2.py    # New endpoints' contract tests (kept separate from existing test_api_management.py)
tests/test_platform_bundle.py      # PlatformBundle dataclass + create_agent contract
```

### Modified files

```
src/agent.py                   # Introduce PlatformBundle; instantiate Swarm when enabled
src/main.py                    # Unpack PlatformBundle via attribute access; pass Swarm to APIChannel
src/swarm/coordinator.py       # Add _team_agents: dict[str, list[str]] in launch()
src/channels/api.py            # Accept subagent_registry + swarm kwargs; register management.py routes; non-loopback host WARN
src/tools/cron.py              # Refactor _load_tasks() to return structured data + add list_active_tasks_structured()
src/config.py                  # Annotate ~6 sensitive Field(...) declarations
tests/test_swarm_coordinator.py  # Test _team_agents mapping
tests/test_api_management.py     # Pin /v1/cost/breakdown response shape (audit)
docs/superpowers/plans/README.md  # Mark Phase 2B-I as DONE (in T11)
```

---

### Task 1: Introduce `PlatformBundle` dataclass

**Files:**
- Modify: `src/agent.py` — return `PlatformBundle` instead of 7-tuple
- Modify: `src/main.py` — unpack via attribute access
- Create: `tests/test_platform_bundle.py`

The current `create_agent()` returns a 7-tuple; T13 reviewer flagged tuple-shape fragility. Phase 2B-I will add `Swarm` to the bundle, making it 8 slots — cheaper to retire the tuple now. Frozen dataclass with one field per existing return slot, plus a placeholder `swarm: Swarm | None = None` field that Task 2 will start populating.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_platform_bundle.py
"""Test PlatformBundle replaces create_agent's tuple return."""
import pytest


def test_platform_bundle_is_frozen():
    """PlatformBundle must be a frozen dataclass — no field mutation after construction."""
    from src.agent import PlatformBundle
    from dataclasses import fields, FrozenInstanceError

    field_names = {f.name for f in fields(PlatformBundle)}
    assert field_names == {
        "agent", "checkpointer", "mcp_client",
        "subagent_registry", "cost_tracker",
        "recovery_executor", "broadcaster", "swarm",
    }

    # Frozen check
    bundle = PlatformBundle(
        agent=object(), checkpointer=object(), mcp_client=None,
        subagent_registry=None, cost_tracker=object(),
        recovery_executor=None, broadcaster=None, swarm=None,
    )
    with pytest.raises(FrozenInstanceError):
        bundle.agent = object()


def test_platform_bundle_defaults_optional_fields_to_none():
    """All Optional[...] fields must default to None so callers can construct minimally."""
    from src.agent import PlatformBundle
    bundle = PlatformBundle(
        agent=object(),
        checkpointer=object(),
        cost_tracker=object(),
    )
    assert bundle.mcp_client is None
    assert bundle.subagent_registry is None
    assert bundle.recovery_executor is None
    assert bundle.broadcaster is None
    assert bundle.swarm is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_platform_bundle.py -v
```

Expected: FAIL with `ImportError: cannot import name 'PlatformBundle' from 'src.agent'`.

- [ ] **Step 3: Add `PlatformBundle` and refactor `create_agent` return**

In `src/agent.py`, near the top:

```python
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PlatformBundle:
    """Aggregate return value of create_agent().

    Replaces the historical N-tuple to keep call sites stable as new
    subsystems get wired in (Swarm in 2B-I, future broadcaster channels, etc.).
    """
    agent: Any
    checkpointer: Any
    cost_tracker: Any
    mcp_client: Any | None = None
    subagent_registry: Any | None = None
    recovery_executor: Any | None = None
    broadcaster: Any | None = None
    swarm: Any | None = None
```

Replace the existing `return agent, checkpointer, mcp_client, subagent_registry, cost_tracker, recovery_executor, broadcaster` line with:

```python
    return PlatformBundle(
        agent=agent,
        checkpointer=checkpointer,
        mcp_client=mcp_client,
        subagent_registry=subagent_registry,
        cost_tracker=cost_tracker,
        recovery_executor=recovery_executor,
        broadcaster=broadcaster,
        swarm=None,  # Task 2 wires Swarm here when config.swarm.enabled
    )
```

Update the `create_agent` docstring (around line 140) to document the new return type.

In `src/main.py`, replace the existing tuple unpack:

```python
    bundle = await create_agent(config)
    logger.info("Agent ready")
```

…and update every downstream reference:
- `agent` → `bundle.agent`
- `checkpointer` → `bundle.checkpointer`
- `mcp_client` → `bundle.mcp_client`
- `subagent_registry` → `bundle.subagent_registry`
- `cost_tracker` → `bundle.cost_tracker`
- `recovery_executor` → `bundle.recovery_executor`
- `broadcaster` → `bundle.broadcaster`

- [ ] **Step 4: Run test to verify it passes + full-suite regression**

```bash
pytest tests/test_platform_bundle.py -v
pytest tests/ -q --tb=line --ignore=tests/test_middleware_bridge.py --ignore=tests/test_middleware_full.py 2>&1 | tail -5
```

Expected: 2 passed for `test_platform_bundle.py`; full suite at 6 pre-existing failures + 2 new passing = 808 passed. **No new failures.**

- [ ] **Step 5: Commit**

```bash
git add src/agent.py src/main.py tests/test_platform_bundle.py
git commit -m "refactor(agent): retire create_agent tuple return for PlatformBundle dataclass"
```

---

### Task 2: Wire `Swarm` into `create_agent` + add `_team_agents` tracking

**Files:**
- Modify: `src/agent.py` — instantiate `Swarm` when `config.swarm.enabled`
- Modify: `src/swarm/coordinator.py` — add `self._team_agents: dict[str, list[str]]` populated in `launch()`
- Modify: `tests/test_swarm_coordinator.py` — extend with `_team_agents` assertion

`Swarm` was built in Phase 2A T12 but never instantiated; T14 only added `SwarmConfig`. This task wires it. Also adds a team→agents mapping that `GET /v1/teams` (Task 7) will need to populate the `agent_ids` field.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_swarm_coordinator.py`:

```python
@pytest.mark.asyncio
async def test_launch_records_team_agents_mapping():
    """After launch, swarm.get_team_agents(team_id) returns the launched agent_ids."""
    swarm, registry, spawner = _make_swarm()
    tmpl = _make_template()

    team_id = await swarm.launch(tmpl)

    agent_ids = swarm.get_team_agents(team_id)
    assert isinstance(agent_ids, list)
    assert len(agent_ids) == len(tmpl.agents)
    # Each ID must correspond to a registered agent
    for aid in agent_ids:
        assert registry.get_agent(aid) is not None


@pytest.mark.asyncio
async def test_get_team_agents_returns_empty_list_for_unknown():
    swarm, _, _ = _make_swarm()
    assert swarm.get_team_agents("team-ghost") == []


@pytest.mark.asyncio
async def test_rollback_clears_team_agents_mapping():
    """Failed launch must not leave a partial _team_agents entry behind."""
    registry = SubAgentRegistry(InMemoryStore())
    broadcaster = EventBroadcaster(None)
    spawner = MagicMock()
    call = {"n": 0}

    async def spawn_stub(info, recovery_context=None):
        call["n"] += 1
        if call["n"] == 2:
            raise RuntimeError("spawn boom")
        async def noop():
            await asyncio.sleep(0.01)
        return asyncio.create_task(noop())

    spawner.spawn = AsyncMock(side_effect=spawn_stub)
    swarm = Swarm(registry=registry, broadcaster=broadcaster,
                  spawner=spawner, workspace="/tmp")

    with pytest.raises(RuntimeError):
        await swarm.launch(_make_template())

    # No team_id was returned, so nothing should be in _team_agents
    assert swarm._team_agents == {}
```

Add a new file `tests/test_agent_swarm_wiring.py`. Rather than running `create_agent`
end-to-end (which requires a real model + checkpointer), this test inspects
the source for the wiring branch. It is a structural test: a code-search
guard that fails loudly if a future refactor moves the Swarm wiring out of
`create_agent` without updating this contract.

```python
"""Structural test: src/agent.py wires a Swarm into PlatformBundle when enabled."""
import pytest


def test_create_agent_imports_swarm():
    """src/agent.py must import Swarm from .swarm.coordinator (statically findable)."""
    import src.agent
    src_text = open(src.agent.__file__).read()
    assert "from .swarm.coordinator import Swarm" in src_text, (
        "Expected `from .swarm.coordinator import Swarm` in src/agent.py — "
        "the Swarm wiring branch must be discoverable by code search."
    )


def test_create_agent_branch_on_swarm_enabled():
    """src/agent.py must have a `if config.swarm.enabled:` branch that constructs Swarm."""
    import src.agent
    src_text = open(src.agent.__file__).read()
    assert "if config.swarm.enabled" in src_text
    # Find the line with the Swarm() construction
    assert "Swarm(" in src_text


def test_platform_bundle_includes_swarm_field():
    """PlatformBundle must declare a swarm field (T1 contract; T2 sets it)."""
    from dataclasses import fields
    from src.agent import PlatformBundle
    field_names = {f.name for f in fields(PlatformBundle)}
    assert "swarm" in field_names
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_swarm_coordinator.py::test_launch_records_team_agents_mapping tests/test_agent_swarm_wiring.py -v
```

Expected: FAIL — `Swarm` has no `_team_agents` attribute / no `get_team_agents` method; `bundle.swarm` is always `None`.

- [ ] **Step 3: Add `_team_agents` to `Swarm` and wire it into `create_agent`**

In `src/swarm/coordinator.py`, in `Swarm.__init__`, add the new field:

```python
        self._teams: dict[str, HarnessRunner] = {}
        self._team_agents: dict[str, list[str]] = {}
```

In `Swarm.launch()`, after the success path successfully builds `HarnessRunner`:

```python
        self._teams[team_id] = HarnessRunner(
            phases=template.phases, gates=gates,
        )
        self._team_agents[team_id] = list(spawned_ids)
        logger.info(...)  # existing log line
        return team_id
```

Note: the rollback path (`_rollback`) is fine — it never reaches the `_teams` write, and `_team_agents` is also unwritten on failure. No change needed there. The new third test pins this.

Add a public accessor:

```python
    def get_team_agents(self, team_id: str) -> list[str]:
        """Return the agent_ids launched for a given team_id, or [] if unknown."""
        return list(self._team_agents.get(team_id, []))
```

In `src/agent.py`, in the sub-agent enabled branch (around line 245), after `recovery_executor` is constructed and before `init_orchestration_tools` is called, add the Swarm wiring:

```python
        # Swarm — top-level team launch (Phase 2B-I wires what Phase 2A T14 deferred)
        swarm = None
        if config.swarm.enabled:
            from .swarm.coordinator import Swarm
            swarm = Swarm(
                registry=subagent_registry,
                broadcaster=broadcaster,
                spawner=spawner,
                workspace=config.swarm.workspace,
            )
            logger.info("Swarm enabled (workspace=%s)", config.swarm.workspace)
```

Initialize `swarm = None` near the top of the function (next to `recovery_executor = None`):

```python
    subagent_registry = None
    recovery_executor = None
    broadcaster = None
    swarm = None
```

Update the `PlatformBundle` construction in the `return` statement to set `swarm=swarm`.

- [ ] **Step 4: Run tests to verify pass + regression**

```bash
pytest tests/test_swarm_coordinator.py tests/test_agent_swarm_wiring.py -v
pytest tests/ -q --tb=line --ignore=tests/test_middleware_bridge.py --ignore=tests/test_middleware_full.py 2>&1 | tail -5
```

Expected: All targeted tests pass; full-suite at 6-pre-existing baseline.

- [ ] **Step 5: Commit**

```bash
git add src/agent.py src/swarm/coordinator.py tests/test_swarm_coordinator.py tests/test_agent_swarm_wiring.py
git commit -m "feat(swarm): wire Swarm into create_agent + add team→agents mapping"
```

---

### Task 3: OpenAI-style error envelope helpers

**Files:**
- Create: `src/api/errors.py`
- Create: `tests/test_api_errors.py`

Three helper functions producing the standard `{"error": {"message", "type", "code"}}` shape used by `/v1/chat/completions`. These will be used by all Task 6–9 handlers; building them now keeps the handler tasks focused.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_api_errors.py
"""Test OpenAI-style error envelope helpers."""
import json
import pytest
from aiohttp import web


def test_not_found_returns_404_with_envelope():
    from src.api.errors import not_found
    resp = not_found("Agent missing", code="agent_not_found")
    assert isinstance(resp, web.Response)
    assert resp.status == 404
    body = json.loads(resp.body.decode())
    assert body == {
        "error": {
            "message": "Agent missing",
            "type": "not_found",
            "code": "agent_not_found",
        }
    }


def test_not_found_default_code_is_not_found():
    from src.api.errors import not_found
    resp = not_found("Resource missing")
    body = json.loads(resp.body.decode())
    assert body["error"]["code"] == "not_found"


def test_bad_request_returns_400():
    from src.api.errors import bad_request
    resp = bad_request("Invalid id format")
    assert resp.status == 400
    body = json.loads(resp.body.decode())
    assert body["error"]["type"] == "bad_request"
    assert body["error"]["message"] == "Invalid id format"


def test_internal_error_returns_500_and_logs_when_exc_provided(caplog):
    from src.api.errors import internal_error
    try:
        raise RuntimeError("kaboom")
    except RuntimeError as exc:
        resp = internal_error("Something broke", exc=exc)
    assert resp.status == 500
    body = json.loads(resp.body.decode())
    assert body["error"]["type"] == "internal_error"
    # The original exception detail must NOT be exposed in the envelope (security)
    assert "kaboom" not in body["error"]["message"]
    # …but it must be logged
    assert any("kaboom" in r.message or "kaboom" in str(r.exc_info) for r in caplog.records)


def test_internal_error_no_exc_does_not_log():
    from src.api.errors import internal_error
    resp = internal_error("Server hiccup")
    assert resp.status == 500
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_api_errors.py -v
```

Expected: FAIL — `src.api.errors` does not exist.

- [ ] **Step 3: Implement helpers**

```python
# src/api/errors.py
"""OpenAI-style error envelope helpers for the management API.

Every handler must return errors in the shape:

    {"error": {"message": str, "type": str, "code": str}}

which matches the existing /v1/chat/completions error contract.
"""
from __future__ import annotations

import logging

from aiohttp import web

logger = logging.getLogger(__name__)


def _envelope(message: str, type_: str, code: str, status: int) -> web.Response:
    return web.json_response(
        {"error": {"message": message, "type": type_, "code": code}},
        status=status,
    )


def not_found(message: str, *, code: str = "not_found") -> web.Response:
    return _envelope(message, type_="not_found", code=code, status=404)


def bad_request(message: str, *, code: str = "bad_request") -> web.Response:
    return _envelope(message, type_="bad_request", code=code, status=400)


def internal_error(
    message: str = "Internal server error",
    *,
    code: str = "internal_error",
    exc: Exception | None = None,
) -> web.Response:
    """500 response. Logs ``exc`` (if provided) but does not expose its detail."""
    if exc is not None:
        logger.exception("Management API internal error: %s", exc)
    return _envelope(message, type_="internal_error", code=code, status=500)
```

Also create an empty `src/api/__init__.py` if it doesn't already exist (it does — Phase 1B left it as `"""Management API package."""`, leave it alone).

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_api_errors.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/api/errors.py tests/test_api_errors.py
git commit -m "feat(api): add OpenAI-style error envelope helpers"
```

---

### Task 4: Config redactor (hybrid policy)

**Files:**
- Create: `src/api/redaction.py`
- Modify: `src/config.py` — annotate ~6 sensitive `Field(...)` declarations
- Create: `tests/test_api_redaction.py`

Hybrid policy: redact any field whose key matches `*_key`/`*_token`/`*_secret`/`*_password` or contains `credentials`, OR is annotated `Field(..., json_schema_extra={"sensitive": True})`. The combined rule covers both the well-named majority and the long tail.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_api_redaction.py
"""Test config redactor — suffix match + Pydantic sensitive=True."""
import pytest
from pydantic import BaseModel, Field


def test_suffix_match_redacts_key_token_secret_password():
    from src.api.redaction import redact
    raw = {
        "api_key": "sk-secret",
        "session_token": "tok-secret",
        "shared_secret": "shh",
        "admin_password": "hunter2",
        "username": "alice",
        "port": 8900,
    }
    out = redact(raw)
    assert out["api_key"] == "***REDACTED***"
    assert out["session_token"] == "***REDACTED***"
    assert out["shared_secret"] == "***REDACTED***"
    assert out["admin_password"] == "***REDACTED***"
    assert out["username"] == "alice"
    assert out["port"] == 8900


def test_credentials_substring_match():
    from src.api.redaction import redact
    raw = {"aws_credentials": {"access": "x", "secret": "y"}, "credentials_path": "/etc/x"}
    out = redact(raw)
    assert out["aws_credentials"] == "***REDACTED***"
    assert out["credentials_path"] == "***REDACTED***"


def test_redaction_is_recursive():
    from src.api.redaction import redact
    raw = {
        "provider": {"name": "anthropic", "api_key": "sk-x"},
        "mcp_servers": {
            "fooserver": {"command": "node", "env": {"FOO_TOKEN": "y"}},
        },
    }
    out = redact(raw)
    assert out["provider"]["api_key"] == "***REDACTED***"
    # Note: env keys are uppercase here. Suffix match is case-insensitive.
    assert out["mcp_servers"]["fooserver"]["env"]["FOO_TOKEN"] == "***REDACTED***"
    assert out["provider"]["name"] == "anthropic"


def test_lists_of_dicts_are_redacted():
    from src.api.redaction import redact
    raw = {"connections": [{"host": "a", "auth_token": "t1"}, {"host": "b", "auth_token": "t2"}]}
    out = redact(raw)
    assert out["connections"][0]["auth_token"] == "***REDACTED***"
    assert out["connections"][1]["auth_token"] == "***REDACTED***"
    assert out["connections"][0]["host"] == "a"


def test_pydantic_sensitive_annotation_redacts_non_matching_name():
    """A field annotated sensitive=True is redacted even if its name doesn't match."""
    from src.api.redaction import redact_model

    class M(BaseModel):
        bot_handle: str = Field(default="bot", json_schema_extra={"sensitive": True})
        username: str = "alice"

    out = redact_model(M(bot_handle="Mr.Robot", username="alice"))
    assert out["bot_handle"] == "***REDACTED***"
    assert out["username"] == "alice"


def test_pydantic_sensitive_works_with_nested_models():
    from src.api.redaction import redact_model

    class Inner(BaseModel):
        oauth_state: str = Field(default="x", json_schema_extra={"sensitive": True})

    class Outer(BaseModel):
        inner: Inner = Field(default_factory=Inner)
        api_key: str = "k"  # caught by suffix rule

    out = redact_model(Outer())
    assert out["inner"]["oauth_state"] == "***REDACTED***"
    assert out["api_key"] == "***REDACTED***"


def test_appconfig_redaction_redacts_provider_api_key():
    """Integration: AppConfig.model_dump() through redact_model masks provider.api_key."""
    from src.api.redaction import redact_model
    from src.config import AppConfig
    cfg = AppConfig()
    out = redact_model(cfg)
    # Provider api_key path should be redacted
    assert out["provider"].get("api_key") == "***REDACTED***" or out["provider"].get("api_key") in ("", None)


def test_redact_does_not_mutate_input():
    from src.api.redaction import redact
    raw = {"api_key": "sk-x", "name": "alice"}
    redact(raw)
    assert raw["api_key"] == "sk-x"  # original unchanged
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_api_redaction.py -v
```

Expected: FAIL — `src.api.redaction` does not exist.

- [ ] **Step 3: Implement the redactor + annotate sensitive fields**

```python
# src/api/redaction.py
"""Hybrid config redactor: suffix-match + Pydantic ``sensitive=True`` annotation.

Replaces secret-bearing values with ``"***REDACTED***"`` so the result is safe
to return from ``GET /v1/config``.
"""
from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)

REDACTED = "***REDACTED***"
_SUFFIX_RULES = ("_key", "_token", "_secret", "_password")
_CONTAINS_RULES = ("credentials",)


def _matches_suffix_rules(key: str) -> bool:
    k = key.lower()
    return any(k.endswith(s) for s in _SUFFIX_RULES) or any(c in k for c in _CONTAINS_RULES)


def redact(data: Any, *, sensitive_paths: set[tuple[str, ...]] | None = None) -> Any:
    """Walk ``data`` and replace secret-keyed values with ``REDACTED``.

    ``sensitive_paths`` is a set of dotted-path tuples (e.g. ``{("provider", "api_key")}``)
    indicating fields that must be redacted regardless of name. Suffix rules apply on top.
    """
    sensitive_paths = sensitive_paths or set()
    return _walk(data, path=(), sensitive_paths=sensitive_paths)


def _walk(node: Any, *, path: tuple[str, ...], sensitive_paths: set[tuple[str, ...]]) -> Any:
    if isinstance(node, dict):
        out: dict = {}
        for k, v in node.items():
            child_path = path + (str(k),)
            is_sensitive = (
                child_path in sensitive_paths
                or _matches_suffix_rules(str(k))
            )
            if is_sensitive:
                out[k] = REDACTED
            else:
                out[k] = _walk(v, path=child_path, sensitive_paths=sensitive_paths)
        return out
    if isinstance(node, list):
        return [_walk(x, path=path, sensitive_paths=sensitive_paths) for x in node]
    return node


def _collect_sensitive_paths(model_cls: type[BaseModel], prefix: tuple[str, ...] = ()) -> set[tuple[str, ...]]:
    """Walk a Pydantic model class and collect dotted paths flagged ``sensitive=True``."""
    paths: set[tuple[str, ...]] = set()
    for name, info in model_cls.model_fields.items():
        full_path = prefix + (name,)
        extra = info.json_schema_extra or {}
        if isinstance(extra, dict) and extra.get("sensitive"):
            paths.add(full_path)
        # Recurse into nested BaseModel annotations
        ann = info.annotation
        if isinstance(ann, type) and issubclass(ann, BaseModel):
            paths |= _collect_sensitive_paths(ann, prefix=full_path)
    return paths


def redact_model(model: BaseModel) -> dict:
    """Dump a Pydantic model and apply hybrid redaction (suffix + sensitive=True)."""
    sensitive_paths = _collect_sensitive_paths(type(model))
    return redact(model.model_dump(), sensitive_paths=sensitive_paths)
```

In `src/config.py`, annotate sensitive fields whose names don't match the suffix rules. Look for these and add `json_schema_extra={"sensitive": True}` to each:

```python
# Example annotations — apply to fields whose name doesn't end in _key/_token/_secret/_password.
# (Most existing fields with secrets ARE named appropriately and need no change.)
# Audit pass: search for fields holding sensitive values and confirm at least one is exercised.
# If no candidates exist (every secret already ends in _key/_token/_secret/_password),
# add a Field(default="", json_schema_extra={"sensitive": True}) example to a config class
# so the test_pydantic_sensitive_annotation path is exercised against a real config.
```

**Practical note for the implementer:** read `src/config.py` and inspect each field. Apply `json_schema_extra={"sensitive": True}` to any field that:
- Holds an OAuth state, signing key, or PII identifier whose name doesn't end in `_key`/`_token`/`_secret`/`_password`
- Otherwise leave fields alone

If the audit finds zero candidates (all secrets already match suffix rules), add the annotation to **one** existing field as a regression-pin (e.g., `provider.base_url` is not sensitive — bad pick; `channels.telegram.bot_token` already matches suffix — bad pick). The cleanest pick: annotate `gateway.token` if it exists, or any `*_id` field that the maintainer considers PII. Document the choice in the commit message.

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_api_redaction.py -v
```

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add src/api/redaction.py src/config.py tests/test_api_redaction.py
git commit -m "feat(api): add hybrid config redactor (suffix match + Pydantic sensitive)"
```

---

### Task 5: Refactor `cron._load_tasks()` to return structured data

**Files:**
- Modify: `src/tools/cron.py`
- Modify: `tests/test_tools_cron.py` — append the new test cases described in Step 1 alongside the existing tests

The existing `list_tasks` @tool returns a string. `GET /v1/tasks` (Task 8) needs structured data. Refactor by:
1. Adding a public `list_active_tasks_structured()` function that returns `list[dict]` with the API-shape keys.
2. Keep `list_tasks` @tool as-is — it now wraps the structured function for formatting.

This separates the data layer from the formatting layer without breaking the existing tool contract.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_tools_cron.py`:

```python
# Append to tests/test_tools_cron.py
"""Test cron tools — structured task listing for /v1/tasks endpoint."""
import asyncio
import json
import pytest
from pathlib import Path


@pytest.fixture
def cron_data_file(tmp_path, monkeypatch):
    """Initialize cron tools with a tmp data file."""
    from src.config import SchedulerConfig
    from src.tools import cron

    data_file = tmp_path / "tasks.json"
    monkeypatch.setattr(cron, "_data_file", str(data_file))
    monkeypatch.setattr(cron, "_tasks_lock", asyncio.Lock())
    return data_file


@pytest.mark.asyncio
async def test_list_active_tasks_structured_returns_api_shape(cron_data_file):
    """The structured listing must produce the keys the API endpoint promises."""
    from src.tools.cron import list_active_tasks_structured

    raw_tasks = [
        {
            "id": "abc12345",
            "prompt": "Daily standup summary",
            "type": "cron",
            "value": "0 9 * * *",
            "channel": "telegram",
            "chat_id": "100",
            "created_at": "2026-04-20T11:23:00+00:00",
            "last_run": None,
            "active": True,
            "model_tier": "standard",
        },
        {
            "id": "deadbeef",
            "prompt": "old job",
            "type": "interval",
            "value": "60",
            "channel": "cli",
            "chat_id": None,
            "created_at": "2026-04-20T11:00:00+00:00",
            "last_run": "2026-04-21T11:00:00+00:00",
            "active": False,  # MUST be excluded
        },
    ]
    cron_data_file.write_text(json.dumps(raw_tasks))

    out = await list_active_tasks_structured()
    assert isinstance(out, list)
    assert len(out) == 1  # Inactive is excluded
    t = out[0]
    # API-shape keys (matches spec §4.4)
    assert t["task_id"] == "abc12345"
    assert t["prompt"] == "Daily standup summary"
    assert t["schedule_type"] == "cron"
    assert t["schedule_value"] == "0 9 * * *"
    assert t["model_tier"] == "standard"
    assert t["created_at"] == "2026-04-20T11:23:00+00:00"
    assert "next_run" in t  # ISO-8601 string or null


@pytest.mark.asyncio
async def test_list_active_tasks_structured_empty(cron_data_file):
    from src.tools.cron import list_active_tasks_structured
    out = await list_active_tasks_structured()
    assert out == []


@pytest.mark.asyncio
async def test_list_active_tasks_structured_handles_missing_optional_fields(cron_data_file):
    """A task without model_tier or last_run must still serialize cleanly."""
    from src.tools.cron import list_active_tasks_structured

    raw = [{"id": "x1", "prompt": "p", "type": "once", "value": "2099-01-01T00:00:00",
            "channel": None, "chat_id": None, "created_at": "2026-04-20T00:00:00+00:00",
            "last_run": None, "active": True}]
    cron_data_file.write_text(json.dumps(raw))

    out = await list_active_tasks_structured()
    assert len(out) == 1
    assert out[0]["model_tier"] is None
    assert out[0]["task_id"] == "x1"
    assert out[0]["next_run"] is not None  # 'once' → use the value as next_run


@pytest.mark.asyncio
async def test_list_tasks_tool_still_returns_string(cron_data_file):
    """The existing @tool contract must keep working — it just consumes the structured data."""
    from src.tools.cron import list_tasks

    raw = [{"id": "abc12345", "prompt": "p", "type": "cron", "value": "* * * * *",
            "channel": None, "chat_id": None, "created_at": "2026-04-20T00:00:00+00:00",
            "last_run": None, "active": True}]
    cron_data_file.write_text(json.dumps(raw))

    result = await list_tasks.ainvoke({})
    assert isinstance(result, str)
    assert "abc12345" in result
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_tools_cron.py -v
```

Expected: FAIL — `list_active_tasks_structured` does not exist.

- [ ] **Step 3: Add `list_active_tasks_structured` and refactor `list_tasks`**

In `src/tools/cron.py`, add this function above the `@tool list_tasks` declaration:

```python
def _compute_next_run(task: dict) -> str | None:
    """Best-effort next-run ISO timestamp. Returns None if cannot compute."""
    schedule_type = task.get("type")
    schedule_value = task.get("value", "")
    if schedule_type == "once":
        # For 'once' tasks, the schedule_value IS the next run (until executed).
        return schedule_value
    if schedule_type == "cron":
        try:
            from croniter import croniter
            from datetime import datetime, timezone
            base = datetime.now(timezone.utc)
            return croniter(schedule_value, base).get_next(datetime).isoformat()
        except Exception:
            return None
    if schedule_type == "interval":
        try:
            from datetime import datetime, timezone, timedelta
            secs = int(schedule_value)
            last_run_iso = task.get("last_run")
            if last_run_iso:
                base = datetime.fromisoformat(last_run_iso)
            else:
                base = datetime.fromisoformat(task.get("created_at", datetime.now(timezone.utc).isoformat()))
            return (base + timedelta(seconds=secs)).isoformat()
        except Exception:
            return None
    return None


def _to_api_dict(task: dict) -> dict:
    """Project a stored task to the /v1/tasks response shape."""
    return {
        "task_id": task.get("id"),
        "prompt": task.get("prompt", ""),
        "schedule_type": task.get("type"),
        "schedule_value": task.get("value"),
        "model_tier": task.get("model_tier"),
        "next_run": _compute_next_run(task),
        "created_at": task.get("created_at"),
    }


async def list_active_tasks_structured() -> list[dict]:
    """Return all active scheduled tasks in the /v1/tasks response shape.

    Excludes inactive tasks (cancelled or completed). Used by both the
    Management API endpoint and the ``list_tasks`` @tool.
    """
    async with get_tasks_lock():
        tasks = _load_tasks()
    return [_to_api_dict(t) for t in tasks if t.get("active", True)]
```

Refactor `list_tasks` to use it:

```python
@tool
async def list_tasks() -> str:
    """List all active scheduled tasks."""
    structured = await list_active_tasks_structured()
    if not structured:
        return "No active scheduled tasks."

    lines = []
    for t in structured:
        lines.append(
            f"- [{t['task_id']}] {t['schedule_type']}={t['schedule_value']} | "
            f"{t['prompt'][:PROMPT_PREVIEW_LEN]}"
            f" | next_run={t['next_run'] or 'unknown'}"
        )
    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_tools_cron.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/tools/cron.py tests/test_tools_cron.py
git commit -m "refactor(cron): split structured task listing from list_tasks @tool"
```

---

### Task 6: `GET /v1/agents` and `GET /v1/agents/{id}`

**Files:**
- Create: `src/api/management.py`
- Create: `tests/test_api_management_v2.py`

First two endpoints establish the `management.py` module and its `setup_management_routes` function. Returns the agent state from `SubAgentRegistry.list_agents()` projected to the API shape (spec §4.1, §4.2). Disabled-subsystem behavior: empty list when registry is None (spec §4.8).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_api_management_v2.py
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
def app_with_registry():
    """aiohttp app with management routes wired to a populated registry.

    Uses MagicMock for asyncio.Task so the fixture stays sync (the read
    endpoints only inspect AgentInfo, not the task itself).
    """
    from unittest.mock import MagicMock
    from src.api.management import setup_management_routes

    registry = SubAgentRegistry(InMemoryStore())
    info1 = _make_agent_info(agent_id="agent-aaa", state=SubAgentState.RUNNING)
    info2 = _make_agent_info(
        agent_id="agent-bbb", state=SubAgentState.FINISHED,
        retry_count=2, error="prior fail",
    )
    registry.register(info1, MagicMock())
    registry.register(info2, MagicMock())

    app = web.Application()
    setup_management_routes(app, subagent_registry=registry, swarm=None, config=None)
    return app


@pytest.fixture
def app_no_registry():
    """aiohttp app with management routes but no registry (subsystem disabled)."""
    from src.api.management import setup_management_routes
    app = web.Application()
    setup_management_routes(app, subagent_registry=None, swarm=None, config=None)
    return app


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
    # Spec §4.1 keys
    for key in ("agent_id", "name", "role", "tier", "state", "task",
                "tools", "skills", "iteration", "cost_cents",
                "retry_count", "created_at", "last_heartbeat"):
        assert key in sample
    assert sample["state"] == "running"


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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_api_management_v2.py -v
```

Expected: FAIL — `src.api.management` does not exist.

- [ ] **Step 3: Implement the module + handlers**

```python
# src/api/management.py
"""Phase 2B-I read-only management endpoints.

Provides handlers for /v1/agents, /v1/agents/{id}, /v1/teams, /v1/tasks, /v1/config.
Distinct from src/api/routes.py which hosts Phase 1B's memory + cost endpoints.
"""
from __future__ import annotations

import logging
from typing import Optional

from aiohttp import web

from .errors import internal_error, not_found

logger = logging.getLogger(__name__)


def _agent_to_dict(info) -> dict:
    """Project AgentInfo to the /v1/agents response shape (spec §4.1)."""
    state = info.state.value if hasattr(info.state, "value") else str(info.state)
    return {
        "agent_id": info.agent_id,
        "name": info.name,
        "role": info.role,
        "tier": info.tier,
        "state": state,
        "task": info.task,
        "tools": list(info.tools),
        "skills": list(info.skills),
        "iteration": info.iteration,
        "cost_cents": info.cost_cents,
        "retry_count": info.retry_count,
        "created_at": _iso(info.created_at),
        "last_heartbeat": _iso(info.last_heartbeat),
    }


def _iso(timestamp: float | None) -> str | None:
    """Convert a unix timestamp (float) to ISO-8601 UTC string."""
    if timestamp is None:
        return None
    from datetime import datetime, timezone
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def setup_management_routes(
    app: web.Application,
    *,
    subagent_registry=None,
    swarm=None,
    config=None,
) -> None:
    """Register Phase 2B-I read-only routes on an aiohttp app.

    All dependencies are passed explicitly — no globals. Each is optional;
    when a dependency is None the corresponding endpoints return 200 with
    an empty list (spec §4.8) except detail endpoints which 404.
    """

    async def handle_agents_list(request: web.Request) -> web.Response:
        try:
            if subagent_registry is None:
                return web.json_response({"agents": []})
            agents = [_agent_to_dict(a) for a in subagent_registry.list_agents()]
            return web.json_response({"agents": agents})
        except Exception as e:
            return internal_error("Failed to list agents", exc=e)

    async def handle_agent_detail(request: web.Request) -> web.Response:
        agent_id = request.match_info["agent_id"]
        try:
            if subagent_registry is None:
                return not_found(f"Agent not found: {agent_id}", code="agent_not_found")
            info = subagent_registry.get_agent(agent_id)
            if info is None:
                return not_found(f"Agent not found: {agent_id}", code="agent_not_found")
            payload = _agent_to_dict(info)
            payload["error"] = info.error
            return web.json_response(payload)
        except Exception as e:
            return internal_error("Failed to get agent detail", exc=e)

    app.router.add_get("/v1/agents", handle_agents_list)
    app.router.add_get("/v1/agents/{agent_id}", handle_agent_detail)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_api_management_v2.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/api/management.py tests/test_api_management_v2.py
git commit -m "feat(api): add GET /v1/agents and GET /v1/agents/{id}"
```

---

### Task 7: `GET /v1/teams`

**Files:**
- Modify: `src/api/management.py` — add teams handler + route
- Modify: `tests/test_api_management_v2.py` — extend with teams tests

Returns the launched team list backed by `Swarm._teams` + `Swarm._team_agents`. Disabled-subsystem (no Swarm) → `{"teams": []}` per spec §4.8.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_api_management_v2.py`:

```python
async def _make_swarm_with_team():
    """Build a Swarm that has launched one 2-agent team. Async helper, not a fixture."""
    from src.api.management import setup_management_routes
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
async def test_get_teams_returns_launched_teams(aiohttp_client):
    from src.api.management import setup_management_routes
    registry, swarm, team_id = await _make_swarm_with_team()

    app = web.Application()
    setup_management_routes(app, subagent_registry=registry, swarm=swarm, config=None)
    client = await aiohttp_client(app)

    resp = await client.get("/v1/teams")
    assert resp.status == 200
    data = await resp.json()
    assert "teams" in data
    assert len(data["teams"]) == 1
    team = data["teams"][0]
    # Spec §4.3 keys
    for key in ("team_id", "phases", "current_phase", "is_finished",
                "agent_count", "agent_ids"):
        assert key in team
    assert team["team_id"] == team_id
    assert team["phases"] == ["plan", "execute"]
    assert team["is_finished"] is False
    assert team["current_phase"] == "plan"  # Initial phase, no advance yet
    assert team["agent_count"] == 2
    assert len(team["agent_ids"]) == 2


@pytest.mark.asyncio
async def test_get_teams_empty_when_swarm_disabled(app_no_registry, aiohttp_client):
    """Spec §4.8: no swarm → {teams: []}."""
    client = await aiohttp_client(app_no_registry)
    resp = await client.get("/v1/teams")
    assert resp.status == 200
    assert await resp.json() == {"teams": []}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_api_management_v2.py::test_get_teams_returns_launched_teams tests/test_api_management_v2.py::test_get_teams_empty_when_swarm_disabled -v
```

Expected: FAIL — no `/v1/teams` route.

- [ ] **Step 3: Add teams handler**

In `src/api/management.py`, inside `setup_management_routes`, before the `app.router.add_get` block:

```python
    async def handle_teams_list(request: web.Request) -> web.Response:
        try:
            if swarm is None:
                return web.json_response({"teams": []})
            teams = []
            for team_id, runner in swarm._teams.items():
                agent_ids = swarm.get_team_agents(team_id)
                teams.append({
                    "team_id": team_id,
                    "phases": list(runner._phases),
                    "current_phase": runner.current_phase,
                    "is_finished": runner.is_finished,
                    "agent_count": len(agent_ids),
                    "agent_ids": list(agent_ids),
                })
            return web.json_response({"teams": teams})
        except Exception as e:
            return internal_error("Failed to list teams", exc=e)
```

Add the route registration:

```python
    app.router.add_get("/v1/teams", handle_teams_list)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_api_management_v2.py -v
```

Expected: 7 passed (5 from Task 6 + 2 new).

- [ ] **Step 5: Commit**

```bash
git add src/api/management.py tests/test_api_management_v2.py
git commit -m "feat(api): add GET /v1/teams"
```

---

### Task 8: `GET /v1/tasks`

**Files:**
- Modify: `src/api/management.py` — add tasks handler + route
- Modify: `tests/test_api_management_v2.py` — extend with tasks tests

Wraps `cron.list_active_tasks_structured()` (Task 5). When the scheduler is disabled (or its data file doesn't exist), the underlying function returns `[]`, which surfaces as `{"tasks": []}` per spec §4.8.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_api_management_v2.py`:

```python
@pytest.fixture
def app_with_tasks(tmp_path, monkeypatch):
    """aiohttp app with management routes + a populated cron task store."""
    from src.api.management import setup_management_routes
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

    app = web.Application()
    setup_management_routes(app, subagent_registry=None, swarm=None, config=None)
    return app


@pytest.mark.asyncio
async def test_get_tasks_returns_active_tasks(app_with_tasks, aiohttp_client):
    client = await aiohttp_client(app_with_tasks)
    resp = await client.get("/v1/tasks")
    assert resp.status == 200
    data = await resp.json()
    assert "tasks" in data
    assert len(data["tasks"]) == 1
    t = data["tasks"][0]
    # Spec §4.4 keys
    for key in ("task_id", "prompt", "schedule_type", "schedule_value",
                "model_tier", "next_run", "created_at"):
        assert key in t
    assert t["task_id"] == "t-1"
    assert t["schedule_type"] == "cron"


@pytest.mark.asyncio
async def test_get_tasks_empty_when_data_file_missing(tmp_path, monkeypatch, aiohttp_client):
    """Spec §4.8: missing scheduler data → 200 with empty list."""
    from src.api.management import setup_management_routes
    from src.tools import cron

    monkeypatch.setattr(cron, "_data_file", str(tmp_path / "does-not-exist.json"))
    monkeypatch.setattr(cron, "_tasks_lock", asyncio.Lock())

    app = web.Application()
    setup_management_routes(app, subagent_registry=None, swarm=None, config=None)
    client = await aiohttp_client(app)

    resp = await client.get("/v1/tasks")
    assert resp.status == 200
    assert await resp.json() == {"tasks": []}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_api_management_v2.py::test_get_tasks_returns_active_tasks tests/test_api_management_v2.py::test_get_tasks_empty_when_data_file_missing -v
```

Expected: FAIL — no `/v1/tasks` route.

- [ ] **Step 3: Add tasks handler**

In `src/api/management.py`, inside `setup_management_routes`:

```python
    async def handle_tasks_list(request: web.Request) -> web.Response:
        try:
            from ..tools.cron import list_active_tasks_structured
            tasks = await list_active_tasks_structured()
            return web.json_response({"tasks": tasks})
        except RuntimeError:
            # cron tools not initialized — treat as "scheduler disabled"
            return web.json_response({"tasks": []})
        except Exception as e:
            return internal_error("Failed to list scheduled tasks", exc=e)
```

Register the route:

```python
    app.router.add_get("/v1/tasks", handle_tasks_list)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_api_management_v2.py -v
```

Expected: 9 passed (7 prior + 2 new).

- [ ] **Step 5: Commit**

```bash
git add src/api/management.py tests/test_api_management_v2.py
git commit -m "feat(api): add GET /v1/tasks"
```

---

### Task 9: `GET /v1/config`

**Files:**
- Modify: `src/api/management.py` — add config handler + route
- Modify: `tests/test_api_management_v2.py` — extend with config tests

Dumps `AppConfig` through the redactor from Task 4 and returns the result. Disabled-subsystem doesn't really apply (config always exists), but if `config=None` was passed to `setup_management_routes`, return 503 — that's a real wiring bug, not a state condition.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_api_management_v2.py`:

```python
@pytest.fixture
def app_with_config():
    """aiohttp app with management routes + an AppConfig instance."""
    from src.api.management import setup_management_routes
    from src.config import AppConfig

    cfg = AppConfig()
    cfg.provider.api_key = "sk-secret-must-not-leak"

    app = web.Application()
    setup_management_routes(app, subagent_registry=None, swarm=None, config=cfg)
    return app


@pytest.mark.asyncio
async def test_get_config_returns_redacted_dump(app_with_config, aiohttp_client):
    client = await aiohttp_client(app_with_config)
    resp = await client.get("/v1/config")
    assert resp.status == 200
    data = await resp.json()
    # Top-level config sections present
    assert "provider" in data
    assert "agent" in data
    assert "subagent" in data
    # api_key MUST be redacted
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_api_management_v2.py::test_get_config_returns_redacted_dump tests/test_api_management_v2.py::test_get_config_503_when_config_not_wired -v
```

Expected: FAIL — no `/v1/config` route.

- [ ] **Step 3: Add config handler**

In `src/api/management.py`, add at the top of the file:

```python
from .redaction import redact_model
```

Add inside `setup_management_routes`:

```python
    async def handle_config_get(request: web.Request) -> web.Response:
        if config is None:
            # Config is a wiring requirement, not an optional subsystem — surface a 503.
            return web.json_response(
                {"error": {
                    "message": "Config not wired into APIChannel",
                    "type": "internal_error",
                    "code": "config_unavailable",
                }},
                status=503,
            )
        try:
            return web.json_response(redact_model(config))
        except Exception as e:
            return internal_error("Failed to render config", exc=e)
```

Register the route:

```python
    app.router.add_get("/v1/config", handle_config_get)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_api_management_v2.py -v
```

Expected: 11 passed (9 prior + 2 new).

- [ ] **Step 5: Commit**

```bash
git add src/api/management.py tests/test_api_management_v2.py
git commit -m "feat(api): add GET /v1/config (redacted)"
```

---

### Task 10: Wire management routes into `APIChannel` + non-loopback WARN + audit `/v1/cost/breakdown`

**Files:**
- Modify: `src/channels/api.py` — accept `subagent_registry` + `swarm` + `config` kwargs; call `management.setup_management_routes`; emit non-loopback WARN
- Modify: `src/main.py` — pass `bundle.subagent_registry`, `bundle.swarm`, `config` into `APIChannel`
- Modify: `tests/test_api_management.py` — add contract test for existing `/v1/cost/breakdown` (audit, no behavior change)

The integration step. Also pins the existing `/v1/cost/breakdown` shape per spec §4.6.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_api_management.py`:

```python
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
```

Add a new test file `tests/test_api_channel_wiring.py`:

```python
"""Test APIChannel wires the new management routes and emits non-loopback WARN."""
import logging
import pytest


def test_apichannel_warns_on_non_loopback_host(caplog):
    """Spec §5: APIChannel must emit a startup WARN when host is not loopback."""
    from src.channels.api import APIChannel
    ch = APIChannel(host="0.0.0.0", port=8901)
    with caplog.at_level(logging.WARNING, logger="src.channels.api"):
        ch._warn_if_non_loopback()
    assert any(
        "non-loopback" in r.message.lower() or "0.0.0.0" in r.message
        for r in caplog.records
    )


def test_apichannel_no_warn_on_loopback(caplog):
    from src.channels.api import APIChannel
    for host in ("127.0.0.1", "localhost", "::1"):
        ch = APIChannel(host=host, port=8901)
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="src.channels.api"):
            ch._warn_if_non_loopback()
        assert not any("non-loopback" in r.message.lower() for r in caplog.records), \
            f"Expected no warning for {host}, got: {[r.message for r in caplog.records]}"


@pytest.mark.asyncio
async def test_apichannel_registers_v1_agents_route():
    """Smoke: starting APIChannel mounts /v1/agents."""
    from aiohttp import web
    from src.channels.api import APIChannel

    ch = APIChannel(host="127.0.0.1", port=0)  # port 0 = ephemeral
    # We don't need to start; we just check route registration.
    app = web.Application()
    # Reach into the registration helper directly:
    ch._register_routes(app)
    routes = [str(r.resource.canonical) for r in app.router.routes()]
    assert "/v1/agents" in routes
    assert "/v1/agents/{agent_id}" in routes
    assert "/v1/teams" in routes
    assert "/v1/tasks" in routes
    assert "/v1/config" in routes
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_api_management.py::test_cost_breakdown_contract tests/test_api_channel_wiring.py -v
```

Expected: cost_breakdown test passes (existing endpoint returns correct shape — green from day 1, contract pinned). Wiring tests FAIL — `_warn_if_non_loopback` and `_register_routes` don't exist yet.

- [ ] **Step 3: Refactor APIChannel + wire management.py**

In `src/channels/api.py`, change the `APIChannel` constructor signature:

```python
    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8900,
        workspace=None,
        cost_tracker=None,
        event_hub=None,
        subagent_registry=None,
        swarm=None,
        config=None,
    ) -> None:
        self._host = host
        self._port = port
        self._workspace = workspace
        self._cost_tracker = cost_tracker
        self._event_hub = event_hub
        self._subagent_registry = subagent_registry
        self._swarm = swarm
        self._config = config
        self._callback = None
        self._runner: web.AppRunner | None = None
        self._response_queues: dict[str, asyncio.Queue] = {}
```

Refactor `start()` — extract route registration into a helper for testability:

```python
    _LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

    def _warn_if_non_loopback(self) -> None:
        if self._host not in self._LOOPBACK_HOSTS:
            logger.warning(
                "APIChannel: bound to non-loopback host %r without authentication. "
                "Management endpoints (/v1/agents, /v1/teams, /v1/tasks, /v1/config) "
                "are exposed to the network. Bind to 127.0.0.1 or add auth.",
                self._host,
            )

    def _register_routes(self, app: web.Application) -> None:
        """Mount all routes on the given app. Extracted for unit testing."""
        # Existing chat routes
        app.router.add_post("/v1/chat/completions", self._handle_chat_completions)
        app.router.add_get("/v1/models", self._handle_models)
        app.router.add_get("/health", self._handle_health)

        # Phase 1B memory + cost routes
        if self._workspace:
            from ..api.routes import setup_management_routes as setup_legacy
            setup_legacy(app, workspace=self._workspace, cost_tracker=self._cost_tracker)

        # WebSocket
        if self._event_hub:
            from ..api.websocket import setup_websocket
            setup_websocket(app, self._event_hub)

        # Phase 2B-I read-only routes
        from ..api.management import setup_management_routes as setup_phase2b
        setup_phase2b(
            app,
            subagent_registry=self._subagent_registry,
            swarm=self._swarm,
            config=self._config,
        )

    async def start(self) -> None:
        self._warn_if_non_loopback()
        app = web.Application()
        self._register_routes(app)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self._host, self._port)
        await site.start()
        logger.info("APIChannel listening on %s:%s", self._host, self._port)
```

In `src/main.py`, in the `if config.channels.api.enabled:` block, update the `APIChannel` construction:

```python
        api = APIChannel(
            host=api_config.host,
            port=api_config.port,
            workspace=config.agent.workspace,
            cost_tracker=bundle.cost_tracker,
            event_hub=event_hub,
            subagent_registry=bundle.subagent_registry,
            swarm=bundle.swarm,
            config=config,
        )
```

- [ ] **Step 4: Run all tests to verify pass**

```bash
pytest tests/test_api_management.py tests/test_api_channel_wiring.py tests/test_api_management_v2.py -v
pytest tests/ -q --tb=line --ignore=tests/test_middleware_bridge.py --ignore=tests/test_middleware_full.py 2>&1 | tail -5
```

Expected: targeted tests all pass; full-suite at the 6-pre-existing baseline + ~22 new passes from Tasks 1–10 = **828 passed**.

- [ ] **Step 5: Commit**

```bash
git add src/channels/api.py src/main.py tests/test_api_management.py tests/test_api_channel_wiring.py
git commit -m "feat(api): wire management routes into APIChannel + non-loopback WARN"
```

---

### Task 11: Final verification + tag `v0.5.0-phase2b-i`

**Files:**
- Modify: `docs/superpowers/plans/README.md` — mark Phase 2B-I as DONE

Verification-only. No code changes; runs the end-to-end import + smoke + suite checks, updates the plan index, tags, pushes.

- [ ] **Step 1: Run full test suite and confirm baseline**

```bash
pytest tests/ -q --tb=line --ignore=tests/test_middleware_bridge.py --ignore=tests/test_middleware_full.py 2>&1 | tail -5
```

Expected: 6 pre-existing failures (same set as v0.4.0-phase2a baseline: cc_handler, gateway_server_handler, router_extended). Total passes ≈ 828.

- [ ] **Step 2: Verify new public API imports**

```bash
python -c "
from src.agent import PlatformBundle
from src.api.errors import not_found, bad_request, internal_error
from src.api.redaction import redact, redact_model
from src.api.management import setup_management_routes
print('Phase 2B-I public API: OK')
"
```

Expected: `Phase 2B-I public API: OK`.

- [ ] **Step 3: Smoke check — exercise each endpoint via aiohttp test client**

```bash
python -c "
import asyncio, aiohttp, json
from aiohttp.test_utils import TestServer, TestClient
from aiohttp import web
from langgraph.store.memory import InMemoryStore

from src.api.management import setup_management_routes
from src.subagent.registry import SubAgentRegistry
from src.config import AppConfig

async def main():
    registry = SubAgentRegistry(InMemoryStore())
    cfg = AppConfig()
    app = web.Application()
    setup_management_routes(app, subagent_registry=registry, swarm=None, config=cfg)
    async with TestClient(TestServer(app)) as client:
        for path in ('/v1/agents', '/v1/teams', '/v1/tasks', '/v1/config'):
            resp = await client.get(path)
            print(f'{path}: {resp.status}')
            assert resp.status == 200, path
    print('All endpoints OK')

asyncio.run(main())
"
```

Expected:
```
/v1/agents: 200
/v1/teams: 200
/v1/tasks: 200
/v1/config: 200
All endpoints OK
```

- [ ] **Step 4: Update plan index**

Edit `docs/superpowers/plans/README.md`. After the Phase 2A row, add Phase 2B-I:

```markdown
| [Phase 2B-I](2026-04-29-phase2b-i-management-api.md) | Management API (read-only) | **DONE** (v0.5.0-phase2b-i) | /v1/agents, /v1/teams, /v1/tasks, /v1/config + Swarm wired into create_agent | Phase 2A |
```

- [ ] **Step 5: Tag, commit README, push**

```bash
git add docs/superpowers/plans/README.md
git commit -m "docs: mark Phase 2B-I as DONE (v0.5.0-phase2b-i)"
git tag v0.5.0-phase2b-i
git push origin feature/implementation-plans
git push origin v0.5.0-phase2b-i
```

Expected: clean push, tag visible on remote.

---

## Exit Criteria

- [ ] `PlatformBundle` dataclass is the return type of `create_agent`
- [ ] `Swarm` is instantiated when `config.swarm.enabled=True`
- [ ] `Swarm._team_agents` populated by `launch()`; `get_team_agents()` accessor present
- [ ] `src/api/errors.py` provides `not_found`, `bad_request`, `internal_error`
- [ ] `src/api/redaction.py` redacts via suffix match + Pydantic `sensitive=True`
- [ ] `cron.list_active_tasks_structured()` returns the `/v1/tasks` shape; `list_tasks` @tool still returns formatted text
- [ ] `GET /v1/agents` returns spec §4.1 shape; empty list when subagent disabled
- [ ] `GET /v1/agents/{id}` returns spec §4.2 shape; 404 with envelope when unknown or disabled
- [ ] `GET /v1/teams` returns spec §4.3 shape; empty list when swarm disabled
- [ ] `GET /v1/tasks` returns spec §4.4 shape; empty list when scheduler disabled
- [ ] `GET /v1/config` returns redacted dump; 503 when config not wired
- [ ] `GET /v1/cost/breakdown` contract test pins existing shape
- [ ] `APIChannel` emits WARNING when bound to non-loopback host
- [ ] Full suite at the 6-pre-existing-fail baseline; no new failures
- [ ] Tag `v0.5.0-phase2b-i` pushed; plan README updated

---

## What's deferred

- Mutation endpoints (POST/DELETE/PATCH) for agents/teams/tasks — Phase 2B-II if needed
- Auth (static token, JWT) — Phase 2B-I.5 if needed
- Web UI — Phase 2B-II
- Discord / Slack channels — Phase 2B-III
- `GET /v1/teams/{id}/board` — Phase 2B-II (designed alongside the UI that consumes it)
