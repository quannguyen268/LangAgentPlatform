"""TOML team template loader (Pydantic v2 schema)."""
from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class AgentTemplate(BaseModel):
    name: str
    role: str
    tier: Literal["lite", "standard", "advanced", "expert"]
    tools: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    task_prompt: str


class TeamTemplate(BaseModel):
    name: str
    goal: str
    phases: list[str] = Field(default_factory=lambda: ["plan", "execute", "verify"])
    agents: list[AgentTemplate]

    @field_validator("agents")
    @classmethod
    def _nonempty(cls, v):
        if not v:
            raise ValueError("team template must define at least one agent")
        return v


def load_template(path: str) -> TeamTemplate:
    """Load a TOML team template from a file path."""
    p = Path(path)
    with open(p, "rb") as f:
        data = tomllib.load(f)
    return TeamTemplate(**data)
