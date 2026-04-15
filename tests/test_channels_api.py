"""Tests for APIChannel — OpenAI-compatible REST API channel."""

from __future__ import annotations

import pytest
from aiohttp.test_utils import TestClient, TestServer

from src.channels.api import APIChannel, format_chat_completion, format_sse_chunk
from src.channels.base import AbstractChannel


# ---------------------------------------------------------------------------
# 1. Import test
# ---------------------------------------------------------------------------

def test_api_channel_imports():
    """Verify the module and its public names load without error."""
    from src.channels import api  # noqa: F401
    assert hasattr(api, "APIChannel")
    assert hasattr(api, "format_chat_completion")
    assert hasattr(api, "format_sse_chunk")


# ---------------------------------------------------------------------------
# 2. Inheritance test
# ---------------------------------------------------------------------------

def test_api_channel_is_abstract_channel():
    """APIChannel must be a subclass of AbstractChannel."""
    assert issubclass(APIChannel, AbstractChannel)
    ch = APIChannel()
    assert isinstance(ch, AbstractChannel)


# ---------------------------------------------------------------------------
# 3. Name attribute test
# ---------------------------------------------------------------------------

def test_api_channel_name():
    """APIChannel.name must be 'api'."""
    assert APIChannel.name == "api"
    assert APIChannel().name == "api"


# ---------------------------------------------------------------------------
# 4. format_chat_completion structure test
# ---------------------------------------------------------------------------

def test_api_chat_completion_format():
    """format_chat_completion must return correct OpenAI-style structure."""
    content = "Hello, world!"
    model = "test-model"
    usage = {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8}

    result = format_chat_completion(content, model, usage)

    assert result["object"] == "chat.completion"
    assert result["model"] == model
    assert isinstance(result["id"], str)
    assert result["id"].startswith("chatcmpl-")
    assert isinstance(result["created"], int)

    choices = result["choices"]
    assert isinstance(choices, list)
    assert len(choices) == 1

    choice = choices[0]
    assert choice["index"] == 0
    assert choice["finish_reason"] == "stop"
    assert choice["message"]["role"] == "assistant"
    assert choice["message"]["content"] == content

    assert result["usage"] == usage


def test_api_chat_completion_format_no_usage():
    """format_chat_completion works without usage."""
    result = format_chat_completion("hi", "m")
    assert result["usage"] is None


# ---------------------------------------------------------------------------
# 5. format_sse_chunk structure test
# ---------------------------------------------------------------------------

def test_api_sse_format():
    """format_sse_chunk must return correct OpenAI chunk structure."""
    delta = "partial text"
    model = "chunk-model"

    result = format_sse_chunk(delta, model)

    assert result["object"] == "chat.completion.chunk"
    assert result["model"] == model
    assert isinstance(result["id"], str)
    assert result["id"].startswith("chatcmpl-")
    assert isinstance(result["created"], int)

    choices = result["choices"]
    assert isinstance(choices, list)
    assert len(choices) == 1

    choice = choices[0]
    assert choice["index"] == 0
    assert choice["delta"]["content"] == delta
    assert choice["finish_reason"] is None


def test_api_sse_format_with_finish_reason():
    """format_sse_chunk passes finish_reason correctly."""
    result = format_sse_chunk("", "m", finish_reason="stop")
    assert result["choices"][0]["finish_reason"] == "stop"


# ---------------------------------------------------------------------------
# 6. /health endpoint test
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_api_health_endpoint():
    """GET /health must return 200 with {status: ok}."""
    channel = APIChannel(host="127.0.0.1", port=0)

    from aiohttp import web

    app = web.Application()
    app.router.add_get("/health", channel._handle_health)

    async with TestClient(TestServer(app)) as client:
        resp = await client.get("/health")
        assert resp.status == 200
        data = await resp.json()
        assert data == {"status": "ok"}


@pytest.mark.asyncio
async def test_api_models_endpoint():
    """GET /v1/models must return a list of models."""
    channel = APIChannel(host="127.0.0.1", port=0)

    from aiohttp import web

    app = web.Application()
    app.router.add_get("/v1/models", channel._handle_models)

    async with TestClient(TestServer(app)) as client:
        resp = await client.get("/v1/models")
        assert resp.status == 200
        data = await resp.json()
        assert data["object"] == "list"
        assert isinstance(data["data"], list)
        assert len(data["data"]) > 0
