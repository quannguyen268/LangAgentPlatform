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
