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
