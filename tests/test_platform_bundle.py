"""Test PlatformBundle replaces create_agent's tuple return."""
import sys

import pytest


def _ensure_real_deepagents():
    """Undo any sys.modules pollution from earlier test files.

    test_backend.py installs a MagicMock for ``deepagents`` (and submodules)
    via ``sys.modules.setdefault`` so it can run without the real package.
    When that mock wins, importing ``src.agent`` fails on
    ``import deepagents.middleware.skills`` because the mock is not a real
    package. Drop the mocks here so the real package gets loaded.
    """
    for name in list(sys.modules):
        if name == "deepagents" or name.startswith("deepagents."):
            mod = sys.modules[name]
            if mod.__class__.__module__ == "unittest.mock":
                del sys.modules[name]


def test_platform_bundle_is_frozen():
    """PlatformBundle must be a frozen dataclass — no field mutation after construction."""
    _ensure_real_deepagents()
    from src.agent import PlatformBundle
    from dataclasses import fields, FrozenInstanceError

    field_names = {f.name for f in fields(PlatformBundle)}
    assert field_names == {
        "agent", "checkpointer", "mcp_client",
        "subagent_registry", "cost_tracker",
        "recovery_executor", "broadcaster", "swarm",
    }

    # Frozen check
    bundle = PlatformBundle(
        agent=object(), checkpointer=object(), mcp_client=None,
        subagent_registry=None, cost_tracker=object(),
        recovery_executor=None, broadcaster=None, swarm=None,
    )
    with pytest.raises(FrozenInstanceError):
        bundle.agent = object()


def test_platform_bundle_defaults_optional_fields_to_none():
    """All Optional[...] fields default to None so callers can construct minimally,
    and required fields round-trip the values they were given."""
    _ensure_real_deepagents()
    from src.agent import PlatformBundle
    a, c, t = object(), object(), object()
    bundle = PlatformBundle(agent=a, checkpointer=c, cost_tracker=t)
    # Required fields round-trip
    assert bundle.agent is a
    assert bundle.checkpointer is c
    assert bundle.cost_tracker is t
    # Optional fields default to None
    assert bundle.mcp_client is None
    assert bundle.subagent_registry is None
    assert bundle.recovery_executor is None
    assert bundle.broadcaster is None
    assert bundle.swarm is None


def test_platform_bundle_required_fields_must_be_provided():
    """``agent``, ``checkpointer``, ``cost_tracker`` have no defaults — pin the contract."""
    _ensure_real_deepagents()
    from src.agent import PlatformBundle
    with pytest.raises(TypeError):
        PlatformBundle(agent=object(), checkpointer=object())  # missing cost_tracker
