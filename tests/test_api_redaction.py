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
    """Integration: AppConfig.model_dump() through redact_model masks provider.api_key.

    Even though the field defaults to None, the redacted output must show
    ``***REDACTED***`` because the path is in sensitive_paths — otherwise a
    future regression that skips redaction for None values could silently
    leak the field once it gets populated.
    """
    from src.api.redaction import redact_model
    from src.config import AppConfig
    cfg = AppConfig()
    out = redact_model(cfg)
    assert out["provider"]["api_key"] == "***REDACTED***"


def test_provider_api_key_default_is_still_none():
    """The Field(default=None, json_schema_extra=...) migration must not change
    the default-None semantics."""
    from src.config import ProviderConfig
    cfg = ProviderConfig()
    assert cfg.api_key is None


def test_redact_does_not_mutate_input():
    from src.api.redaction import redact
    raw = {"api_key": "sk-x", "name": "alice"}
    redact(raw)
    assert raw["api_key"] == "sk-x"  # original unchanged


def test_sensitive_paths_pass_through_redacts_non_matching_keys():
    """The public ``sensitive_paths`` parameter must redact paths that don't
    match the suffix rules, regardless of any Pydantic involvement."""
    from src.api.redaction import redact
    out = redact({"foo": "x", "bar": "y"}, sensitive_paths={("foo",)})
    assert out["foo"] == "***REDACTED***"
    assert out["bar"] == "y"


def test_redact_handles_empty_and_none_inputs():
    """Empty dicts/lists pass through; primitives (None, scalars) are returned as-is."""
    from src.api.redaction import redact
    assert redact({}) == {}
    assert redact([]) == []
    assert redact(None) is None
    assert redact("plain string") == "plain string"
    assert redact(42) == 42


def test_collect_sensitive_paths_handles_optional_basemodel():
    """Optional[Inner] must be peeled so Inner's sensitive fields are still found."""
    from typing import Optional
    from src.api.redaction import _collect_sensitive_paths

    class Inner(BaseModel):
        secret_id: str = Field(default="x", json_schema_extra={"sensitive": True})

    class Outer(BaseModel):
        inner: Optional[Inner] = None

    paths = _collect_sensitive_paths(Outer)
    assert ("inner", "secret_id") in paths


def test_collect_sensitive_paths_handles_dict_of_basemodel():
    """dict[str, Inner] must be peeled so the inner sensitive fields are discovered."""
    from src.api.redaction import _collect_sensitive_paths

    class Tier(BaseModel):
        oauth_state: str = Field(default="x", json_schema_extra={"sensitive": True})

    class Outer(BaseModel):
        tiers: dict[str, Tier] = Field(default_factory=dict)

    paths = _collect_sensitive_paths(Outer)
    assert ("tiers", "oauth_state") in paths


def test_collect_sensitive_paths_does_not_infinite_loop_on_self_reference():
    """A model that references itself (or a cycle) must not infinite-recurse."""
    from typing import Optional
    from src.api.redaction import _collect_sensitive_paths

    class Node(BaseModel):
        token_value: str = Field(default="x", json_schema_extra={"sensitive": True})
        # Self-reference via forward ref
        child: "Optional[Node]" = None

    Node.model_rebuild()
    paths = _collect_sensitive_paths(Node)
    # Should terminate and find the top-level path at minimum
    assert ("token_value",) in paths
