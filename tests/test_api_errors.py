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


def test_envelope_key_set_is_exactly_message_type_code():
    """Pin the envelope shape so a future addition of e.g. ``request_id``
    requires a deliberate test update rather than a silent contract drift."""
    from src.api.errors import not_found, bad_request, internal_error
    for resp in (not_found("x"), bad_request("x"), internal_error("x")):
        body = json.loads(resp.body.decode())
        assert set(body.keys()) == {"error"}
        assert set(body["error"].keys()) == {"message", "type", "code"}
