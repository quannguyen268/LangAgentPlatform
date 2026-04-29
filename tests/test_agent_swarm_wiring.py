"""Structural test: src/agent.py wires a Swarm into PlatformBundle when enabled."""
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


def test_create_agent_imports_swarm():
    """src/agent.py must import Swarm from .swarm.coordinator (statically findable)."""
    _ensure_real_deepagents()
    import src.agent
    src_text = open(src.agent.__file__).read()
    assert "from .swarm.coordinator import Swarm" in src_text, (
        "Expected `from .swarm.coordinator import Swarm` in src/agent.py — "
        "the Swarm wiring branch must be discoverable by code search."
    )


def test_create_agent_branch_on_swarm_enabled():
    """src/agent.py must have a `if config.swarm.enabled:` branch that constructs Swarm."""
    _ensure_real_deepagents()
    import src.agent
    src_text = open(src.agent.__file__).read()
    assert "if config.swarm.enabled" in src_text
    # Find the line with the Swarm() construction
    assert "Swarm(" in src_text


def test_platform_bundle_includes_swarm_field():
    """PlatformBundle must declare a swarm field (T1 contract; T2 sets it)."""
    _ensure_real_deepagents()
    from dataclasses import fields
    from src.agent import PlatformBundle
    field_names = {f.name for f in fields(PlatformBundle)}
    assert "swarm" in field_names
