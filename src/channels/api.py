"""OpenAI-compatible REST API channel with SSE streaming support."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Optional

from aiohttp import web

from .base import AbstractChannel, IncomingMessage, SendResult

logger = logging.getLogger(__name__)

_FAKE_MODEL_LIST = [
    {"id": "lang-agent", "object": "model", "created": 1700000000, "owned_by": "lang-agent-platform"},
    {"id": "default", "object": "model", "created": 1700000000, "owned_by": "lang-agent-platform"},
]


# ---------------------------------------------------------------------------
# Helper functions (used by tests)
# ---------------------------------------------------------------------------

def format_chat_completion(content: str, model: str, usage: dict | None = None) -> dict:
    """Format non-streaming response in OpenAI format."""
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": usage,
    }


def format_sse_chunk(delta: str, model: str, finish_reason: str | None = None) -> dict:
    """Format a single SSE streaming chunk."""
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": {"content": delta},
                "finish_reason": finish_reason,
            }
        ],
    }


# ---------------------------------------------------------------------------
# APIChannel
# ---------------------------------------------------------------------------

class APIChannel(AbstractChannel):
    """OpenAI-compatible REST API channel."""

    name = "api"

    _LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

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
        # Maps request_id -> asyncio.Queue[str | None]
        # None sentinel signals end of stream
        self._response_queues: dict[str, asyncio.Queue] = {}

    # ------------------------------------------------------------------
    # AbstractChannel interface
    # ------------------------------------------------------------------

    def _warn_if_non_loopback(self) -> None:
        """Emit a WARN when bound to a non-loopback host (Phase 2B-I is localhost-only)."""
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

        # Phase 2B-I read-only management routes
        from ..api.management import setup_management_routes as setup_phase2b
        setup_phase2b(
            app,
            subagent_registry=self._subagent_registry,
            swarm=self._swarm,
            config=self._config,
        )

    async def start(self) -> None:
        """Start the aiohttp web server."""
        self._warn_if_non_loopback()
        app = web.Application()
        self._register_routes(app)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self._host, self._port)
        await site.start()
        logger.info("APIChannel listening on %s:%s", self._host, self._port)

    async def stop(self) -> None:
        """Gracefully stop the web server."""
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
            logger.info("APIChannel stopped")

    async def send(
        self,
        chat_id: str,
        text: str,
        *,
        reply_to_message_id: Optional[str] = None,
        disable_notification: bool = False,
    ) -> Optional[SendResult]:
        """Push text to the per-request queue identified by chat_id (= request_id)."""
        queue = self._response_queues.get(chat_id)
        if queue is not None:
            await queue.put(text)
        return SendResult(message_id=None)

    async def send_file(self, chat_id: str, path: str, caption: str = "") -> None:
        """Not meaningfully supported over REST; sends caption as text."""
        await self.send(chat_id, caption or path)

    # ------------------------------------------------------------------
    # HTTP handlers
    # ------------------------------------------------------------------

    async def _handle_health(self, request: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

    async def _handle_models(self, request: web.Request) -> web.Response:
        return web.json_response(
            {"object": "list", "data": _FAKE_MODEL_LIST}
        )

    async def _handle_chat_completions(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            raise web.HTTPBadRequest(reason="Invalid JSON body")

        messages: list[dict] = body.get("messages", [])
        model: str = body.get("model", "default")
        stream: bool = body.get("stream", False)

        # Extract user text from last user message
        user_text = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str):
                    user_text = content
                elif isinstance(content, list):
                    # multi-part content
                    parts = [p.get("text", "") for p in content if p.get("type") == "text"]
                    user_text = " ".join(parts)
                break

        # Create a unique request ID that doubles as chat_id for this request
        request_id = uuid.uuid4().hex
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        self._response_queues[request_id] = queue

        try:
            if self._callback is not None:
                incoming = IncomingMessage(
                    channel=self.name,
                    chat_id=request_id,
                    user_id=request_id,
                    user_name="api-user",
                    text=user_text,
                    is_private=True,
                )
                asyncio.ensure_future(self._callback(incoming))
            else:
                # No callback registered — echo back a placeholder
                await queue.put("(no agent callback registered)")
                await queue.put(None)

            if stream:
                return await self._stream_response(queue, model)
            else:
                return await self._non_stream_response(queue, model)
        finally:
            self._response_queues.pop(request_id, None)

    async def _non_stream_response(
        self, queue: asyncio.Queue, model: str
    ) -> web.Response:
        """Collect all chunks and return a single JSON response."""
        parts: list[str] = []
        while True:
            chunk = await queue.get()
            if chunk is None:
                break
            parts.append(chunk)
        content = "".join(parts)
        payload = format_chat_completion(content, model)
        return web.json_response(payload)

    async def _stream_response(
        self, queue: asyncio.Queue, model: str
    ) -> web.StreamResponse:
        """Return SSE stream, one chunk per queue item."""
        response = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )
        await response.prepare(response._req)  # type: ignore[attr-defined]

        while True:
            chunk = await queue.get()
            if chunk is None:
                # Send final [DONE] sentinel
                await response.write(b"data: [DONE]\n\n")
                break
            sse_payload = format_sse_chunk(chunk, model)
            data_line = f"data: {json.dumps(sse_payload)}\n\n"
            await response.write(data_line.encode())

        await response.write_eof()
        return response
