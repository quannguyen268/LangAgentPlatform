"""Test APIChannel serves the Vite dist at /web/* and redirects / → /web/."""
import logging
from pathlib import Path

import pytest
from aiohttp import web


@pytest.mark.asyncio
async def test_static_handler_serves_index_html(tmp_path, aiohttp_client):
    """When web_dist_path is set, GET /web/ returns the index.html content."""
    from src.channels.api import APIChannel

    dist = tmp_path / "static"
    dist.mkdir()
    (dist / "index.html").write_text("<html><body>hello dashboard</body></html>")

    ch = APIChannel(host="127.0.0.1", port=0, web_dist_path=str(dist))
    app = web.Application()
    ch._register_routes(app)
    client = await aiohttp_client(app)

    resp = await client.get("/web/")
    assert resp.status == 200
    body = await resp.text()
    assert "hello dashboard" in body


@pytest.mark.asyncio
async def test_static_handler_serves_nested_asset(tmp_path, aiohttp_client):
    from src.channels.api import APIChannel

    dist = tmp_path / "static"
    (dist / "assets").mkdir(parents=True)
    (dist / "assets" / "main.js").write_text("console.log('ok');")

    ch = APIChannel(host="127.0.0.1", port=0, web_dist_path=str(dist))
    app = web.Application()
    ch._register_routes(app)
    client = await aiohttp_client(app)

    resp = await client.get("/web/assets/main.js")
    assert resp.status == 200
    body = await resp.text()
    assert "console.log" in body


@pytest.mark.asyncio
async def test_root_redirects_to_web(tmp_path, aiohttp_client):
    from src.channels.api import APIChannel

    dist = tmp_path / "static"
    dist.mkdir()
    (dist / "index.html").write_text("<html></html>")

    ch = APIChannel(host="127.0.0.1", port=0, web_dist_path=str(dist))
    app = web.Application()
    ch._register_routes(app)
    client = await aiohttp_client(app)

    resp = await client.get("/", allow_redirects=False)
    assert resp.status in (301, 302)
    assert resp.headers["Location"] == "/web/"


@pytest.mark.asyncio
async def test_no_web_routes_when_dist_path_not_set(aiohttp_client):
    """When web_dist_path is None, /web/ and / return 404 (no static handler)."""
    from src.channels.api import APIChannel

    ch = APIChannel(host="127.0.0.1", port=0)  # web_dist_path defaults to None
    app = web.Application()
    ch._register_routes(app)
    client = await aiohttp_client(app)

    resp = await client.get("/web/")
    assert resp.status == 404
    resp = await client.get("/", allow_redirects=False)
    assert resp.status == 404


def test_apichannel_logs_static_serve_path(tmp_path, caplog):
    """Operators should see at INFO which directory is being served, to debug
    mismatches between build output and configured path."""
    from src.channels.api import APIChannel

    dist = tmp_path / "static"
    dist.mkdir()
    ch = APIChannel(host="127.0.0.1", port=0, web_dist_path=str(dist))
    with caplog.at_level(logging.INFO, logger="src.channels.api"):
        app = web.Application()
        ch._register_routes(app)
    assert any(str(dist) in r.message for r in caplog.records)
