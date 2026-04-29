"""OpenAI-style error envelope helpers for the management API.

Every management handler must return errors in the shape:

    {"error": {"message": str, "type": str, "code": str}}

This establishes the canonical OpenAI-style error contract for the management
API surface introduced in Phase 2B-I. The legacy ``/v1/chat/completions``
handler currently raises ``web.HTTPBadRequest(reason=...)`` (text/plain) and
will be migrated to this envelope in a later phase; do not rely on it being
already aligned.
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


def service_unavailable(
    message: str, *, code: str = "service_unavailable",
) -> web.Response:
    """503 response. Use for wiring/configuration faults that are not transient
    failures (e.g., a required dependency was never injected at construction)
    and won't recover without operator action."""
    return _envelope(message, type_="internal_error", code=code, status=503)
