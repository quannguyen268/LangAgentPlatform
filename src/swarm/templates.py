"""TOML team template loader (Pydantic v2 schema).

Templates describe a team: goal, phases, and a list of agents (name/role/tier/
tools/skills/task_prompt). Built-in templates ship under ``src/swarm/templates``
and are resolved via ``load_builtin()``; external templates load via
``load_template(path)``.
"""
from __future__ import annotations

import tomllib
from importlib import resources
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator


class AgentTemplate(BaseModel):
    name: str = Field(min_length=1)
    role: str = Field(min_length=1)
    tier: Literal["lite", "standard", "advanced", "expert"]
    tools: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    task_prompt: str = Field(min_length=1)
    phase: Optional[str] = None

    @field_validator("phase")
    @classmethod
    def _strip_phase(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v2 = v.strip()
        return v2 or None

    @field_validator("name", "role", "task_prompt")
    @classmethod
    def _strip_nonempty(cls, v: str) -> str:
        v2 = v.strip()
        if not v2:
            raise ValueError("must not be blank")
        return v2

    @field_validator("tools", "skills")
    @classmethod
    def _dedupe(cls, v: list[str]) -> list[str]:
        # Preserve order, drop duplicates and empty strings
        seen: dict[str, None] = {}
        for item in v:
            item = item.strip()
            if item and item not in seen:
                seen[item] = None
        return list(seen.keys())


class TeamTemplate(BaseModel):
    name: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    phases: list[str] = Field(default_factory=lambda: ["plan", "execute", "verify"])
    agents: list[AgentTemplate]

    @field_validator("agents")
    @classmethod
    def _nonempty(cls, v: list[AgentTemplate]) -> list[AgentTemplate]:
        if not v:
            raise ValueError("team template must define at least one agent")
        names = [a.name for a in v]
        dupes = {n for n in names if names.count(n) > 1}
        if dupes:
            raise ValueError(f"agent names must be unique; duplicates: {sorted(dupes)}")
        return v

    @model_validator(mode="after")
    def _validate_agent_phases(self) -> "TeamTemplate":
        known = set(self.phases)
        for a in self.agents:
            if a.phase is not None and a.phase not in known:
                raise ValueError(
                    f"agent {a.name!r} references unknown phase {a.phase!r}; "
                    f"known phases: {self.phases}"
                )
        return self

    @property
    def is_phased(self) -> bool:
        """True iff any agent is bound to a phase (enables phased activation)."""
        return any(a.phase is not None for a in self.agents)

    def agents_for_phase(self, phase: str) -> list["AgentTemplate"]:
        """Agents declared for a given phase (order-preserving)."""
        return [a for a in self.agents if a.phase == phase]


def load_template(
    path: str, *, known_tools: Optional[set[str]] = None
) -> TeamTemplate:
    """Load a TOML team template from a file path.

    Raises:
        FileNotFoundError: if ``path`` does not exist (message includes the path).
        ValueError: on malformed TOML or schema violations (message includes
            the path). Pydantic's ``ValidationError`` is a ``ValueError``
            subclass, so callers catching ``ValueError`` cover both.

    If ``known_tools`` is provided, any tool referenced by any agent that is
    not in the set raises ``ValueError`` at load time — catches config drift
    before spawn time. Leave ``None`` to skip this check.
    """
    p = Path(path)
    try:
        with open(p, "rb") as f:
            data = tomllib.load(f)
    except FileNotFoundError as e:
        raise FileNotFoundError(f"Team template not found: {p}") from e
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"Malformed TOML in {p}: {e}") from e

    try:
        tmpl = TeamTemplate(**data)
    except ValidationError as e:
        raise ValueError(f"Invalid team template {p}: {e}") from e

    if known_tools is not None:
        unknown = {
            t for agent in tmpl.agents for t in agent.tools if t not in known_tools
        }
        if unknown:
            raise ValueError(
                f"Unknown tools in template {p}: {sorted(unknown)}. "
                f"Known tools: {sorted(known_tools)}"
            )
    return tmpl


def load_builtin(
    name: str, *, known_tools: Optional[set[str]] = None
) -> TeamTemplate:
    """Load a built-in template shipped under ``src/swarm/templates/``.

    ``name`` is the stem (no ``.toml``). Raises ``FileNotFoundError`` if no
    such built-in exists.
    """
    try:
        ref = resources.files(__package__).joinpath("templates", f"{name}.toml")
    except (ModuleNotFoundError, AttributeError) as e:
        raise FileNotFoundError(f"Built-in template package missing: {e}") from e
    with resources.as_file(ref) as p:
        return load_template(str(p), known_tools=known_tools)
