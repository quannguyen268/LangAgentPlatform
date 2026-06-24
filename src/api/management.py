"""Phase 2B-I read-only management endpoints.

Provides handlers for /v1/agents, /v1/agents/{id}, /v1/teams, /v1/tasks, /v1/config.
Distinct from src/api/routes.py which hosts Phase 1B's memory + cost endpoints.
"""
from __future__ import annotations

import logging
from typing import Optional

from aiohttp import web

from .errors import internal_error, not_found, service_unavailable
from .redaction import redact_model

logger = logging.getLogger(__name__)


def _agent_to_dict(info) -> dict:
    """Project AgentInfo to the ``/v1/agents`` response shape (spec §4.1).

    This is the **API-edge projection**: trimmed to fields a Web UI consumer
    cares about, with timestamps in ISO-8601 UTC. ``AgentInfo.to_dict()``
    is the **internal** serializer used for state snapshots; it returns raw
    float timestamps and the full field set. The two intentionally diverge
    because they serve different audiences — keep them that way.
    """
    return {
        "agent_id": info.agent_id,
        "name": info.name,
        "role": info.role,
        "tier": info.tier,
        "state": info.state.value,
        "task": info.task,
        "tools": list(info.tools),
        "skills": list(info.skills),
        "iteration": info.iteration,
        "cost_cents": info.cost_cents,
        "retry_count": info.retry_count,
        "created_at": _iso(info.created_at),
        "last_heartbeat": _iso(info.last_heartbeat),
        # finished_at is set on FINISHED/FAILED agents and is materially
        # useful to UI consumers ("how long did this run?"). Null for
        # agents that haven't terminated yet.
        "finished_at": _iso(info.finished_at),
    }


def _iso(timestamp: float | None) -> str | None:
    """Convert a unix timestamp (float) to ISO-8601 UTC string. None → None."""
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

    async def handle_teams_list(request: web.Request) -> web.Response:
        try:
            if swarm is None:
                return web.json_response({"teams": []})
            teams = []
            for team_id, runner in swarm.iter_teams():
                agent_ids = swarm.get_team_agents(team_id)
                teams.append({
                    "team_id": team_id,
                    "phases": list(runner.phases),
                    "current_phase": runner.current_phase,
                    "is_finished": runner.is_finished,
                    # agent_count is redundant with len(agent_ids) but spares
                    # UI consumers from iterating to render team-card badges.
                    "agent_count": len(agent_ids),
                    "agent_ids": list(agent_ids),
                })
            return web.json_response({"teams": teams})
        except Exception as e:
            return internal_error("Failed to list teams", exc=e)

    async def handle_tasks_list(request: web.Request) -> web.Response:
        # Imports are deferred so the cron module isn't required at import time
        # for callers that only need the agent/team/config endpoints.
        from ..tools import cron
        # Probe the not-initialized condition explicitly so we don't have to
        # swallow every RuntimeError that bubbles out of the cron internals
        # (e.g., a malformed cron expression should still surface as 500).
        if cron._tasks_lock is None:
            logger.debug(
                "GET /v1/tasks returning empty list — cron tools not initialized"
            )
            return web.json_response({"tasks": []})
        try:
            tasks = await cron.list_active_tasks_structured()
            return web.json_response({"tasks": tasks})
        except Exception as e:
            return internal_error("Failed to list scheduled tasks", exc=e)

    async def handle_config_get(request: web.Request) -> web.Response:
        if config is None:
            # Config is a wiring requirement, not an optional subsystem —
            # surface a 503 with a distinct code so operators can tell this
            # apart from a generic 500. Log loudly because this is a wiring
            # bug in the host app, not a runtime condition.
            logger.error(
                "GET /v1/config: config not wired into setup_management_routes — "
                "operators should pass config=AppConfig(...) when constructing the channel"
            )
            return service_unavailable(
                "Config not wired into APIChannel", code="config_unavailable",
            )
        try:
            return web.json_response(redact_model(config))
        except Exception as e:
            return internal_error("Failed to render config", exc=e)

    app.router.add_get("/v1/agents", handle_agents_list)
    app.router.add_get("/v1/agents/{agent_id}", handle_agent_detail)
    app.router.add_get("/v1/teams", handle_teams_list)
    app.router.add_get("/v1/tasks", handle_tasks_list)
    app.router.add_get("/v1/config", handle_config_get)
