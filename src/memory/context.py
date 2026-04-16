"""Build memory context from workspace files for system prompt injection."""
from __future__ import annotations
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

MEMORY_FILES = [
    ("IDENTITY.md", "Identity"),
    ("AGENT.md", "Agent Instructions"),
    ("MEMORY.md", "Memory"),
    ("AGENT_REGISTRY.md", "Agent Registry"),
    ("TEAM_PLAYBOOK.md", "Team Playbook"),
]

def build_memory_context(workspace: str, user_id: str = "") -> str:
    workspace_path = Path(workspace)
    sections = []
    for filename, label in MEMORY_FILES:
        fpath = workspace_path / filename
        if fpath.exists():
            try:
                content = fpath.read_text(encoding="utf-8").strip()
                if content:
                    sections.append(f"## {label}\n\n{content}")
            except Exception as e:
                logger.warning("Failed to read %s: %s", filename, e)
    if user_id:
        user_file = workspace_path / "users" / user_id / "USER.md"
        if user_file.exists():
            try:
                content = user_file.read_text(encoding="utf-8").strip()
                if content:
                    sections.append(f"## User Preferences\n\n{content}")
            except Exception as e:
                logger.warning("Failed to read USER.md for %s: %s", user_id, e)
    return "\n\n---\n\n".join(sections)
