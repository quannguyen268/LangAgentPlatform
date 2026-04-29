"""Management API route handlers.

Endpoints:
- GET/PUT /v1/memory/{filename} — Read/write memory files
- GET /v1/memory — List memory files
- GET /v1/memory/dream/log — Dream change history
- POST /v1/memory/dream/restore/{sha} — Restore memory to a previous state
- GET /v1/cost — Cost summary
- GET /v1/cost/breakdown — Per-user, per-tier, per-agent breakdown
- GET /v1/tasks — List scheduled tasks
"""
from __future__ import annotations

import logging
from pathlib import Path

from aiohttp import web

logger = logging.getLogger(__name__)

ALLOWED_MEMORY_FILES = {
    "IDENTITY.md", "AGENT.md", "MEMORY.md", "SOUL.md", "USER.md",
    "AGENT_REGISTRY.md", "TEAM_PLAYBOOK.md",
}


def setup_legacy_routes(
    app: web.Application,
    workspace: str,
    cost_tracker=None,
    gitstore=None,
) -> None:
    """Register Phase 1B memory + cost + dream routes on an aiohttp Application.

    Renamed from ``setup_management_routes`` in Phase 2B-I to disambiguate from
    the new ``src/api/management.setup_management_routes`` (Phase 2B-I read-only
    state endpoints). This function continues to own ``/v1/memory*``,
    ``/v1/cost*``, and ``/v1/memory/dream/*``.
    """
    workspace_path = Path(workspace)

    # ── Memory endpoints ──

    async def handle_memory_list(request: web.Request) -> web.Response:
        files = []
        for name in ALLOWED_MEMORY_FILES:
            fpath = workspace_path / name
            if fpath.exists():
                files.append({
                    "name": name,
                    "size": fpath.stat().st_size,
                    "modified": fpath.stat().st_mtime,
                })
        return web.json_response(files)

    async def handle_memory_read(request: web.Request) -> web.Response:
        filename = request.match_info["filename"]
        if filename not in ALLOWED_MEMORY_FILES:
            raise web.HTTPNotFound(reason=f"File not found: {filename}")
        fpath = workspace_path / filename
        if not fpath.exists():
            raise web.HTTPNotFound(reason=f"File not found: {filename}")
        content = fpath.read_text(encoding="utf-8")
        return web.json_response({"name": filename, "content": content})

    async def handle_memory_update(request: web.Request) -> web.Response:
        filename = request.match_info["filename"]
        if filename not in ALLOWED_MEMORY_FILES:
            raise web.HTTPForbidden(reason=f"Access denied: {filename}")
        body = await request.json()
        content = body.get("content", "")
        fpath = workspace_path / filename
        fpath.write_text(content, encoding="utf-8")
        return web.json_response({"status": "ok", "name": filename, "size": len(content)})

    async def handle_dream_log(request: web.Request) -> web.Response:
        if not gitstore:
            return web.json_response({"commits": []})
        commits = gitstore.log_commits(limit=20)
        return web.json_response({"commits": commits})

    async def handle_dream_restore(request: web.Request) -> web.Response:
        sha = request.match_info["sha"]
        if not gitstore:
            raise web.HTTPServiceUnavailable(reason="GitStore not available")
        success = gitstore.restore_commit(sha)
        if success:
            return web.json_response({"status": "restored", "sha": sha})
        raise web.HTTPNotFound(reason=f"Commit {sha} not found")

    # ── Cost endpoints ──

    async def handle_cost_summary(request: web.Request) -> web.Response:
        if not cost_tracker:
            return web.json_response({"total_tokens": 0, "total_cost_cents": 0})
        return web.json_response(cost_tracker.summary())

    async def handle_cost_breakdown(request: web.Request) -> web.Response:
        if not cost_tracker:
            return web.json_response({"by_user": {}, "by_tier": {}, "by_agent": {}})
        return web.json_response({
            "by_user": cost_tracker.by_user(),
            "by_tier": cost_tracker.by_tier(),
            "by_agent": cost_tracker.by_agent(),
        })

    # ── Register routes ──

    app.router.add_get("/v1/memory", handle_memory_list)
    app.router.add_get("/v1/memory/dream/log", handle_dream_log)
    app.router.add_post("/v1/memory/dream/restore/{sha}", handle_dream_restore)
    app.router.add_get("/v1/memory/{filename}", handle_memory_read)
    app.router.add_put("/v1/memory/{filename}", handle_memory_update)
    app.router.add_get("/v1/cost", handle_cost_summary)
    app.router.add_get("/v1/cost/breakdown", handle_cost_breakdown)
