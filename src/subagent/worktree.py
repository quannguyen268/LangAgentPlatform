"""WorktreeManager — per-agent git worktree lifecycle.

Each sub-agent that works on code gets its own branch ``agent/{agent_id}`` and
a worktree under ``worktree_root/{agent_id}``. On ``recall_agent`` the master
asks the manager to ``merge()`` and then ``cleanup()``.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


class WorktreeManager:
    """Manage git worktrees for sub-agents."""

    def __init__(self, base_repo: str, worktree_root: str, base_branch: str = "main"):
        self._base_repo = Path(base_repo).resolve()
        self._worktree_root = Path(worktree_root).resolve()
        self._worktree_root.mkdir(parents=True, exist_ok=True)
        self._base_branch = base_branch

    def _branch(self, agent_id: str) -> str:
        return f"agent/{agent_id}"

    def _path(self, agent_id: str) -> Path:
        return self._worktree_root / agent_id

    def create(self, agent_id: str) -> str:
        """Create a worktree with a fresh branch off base_branch. Returns the path."""
        path = self._path(agent_id)
        if path.exists():
            logger.warning("Worktree for %s already exists at %s", agent_id, path)
            return str(path)
        branch = self._branch(agent_id)
        subprocess.run(
            ["git", "worktree", "add", "-b", branch, str(path), self._base_branch],
            cwd=self._base_repo, check=True, capture_output=True,
        )
        logger.info("Created worktree %s on branch %s", path, branch)
        return str(path)

    def merge(self, agent_id: str) -> bool:
        """Merge the agent's branch back into base_branch.

        Returns True on clean merge, False if git reports conflicts. The caller
        (typically recall_agent) can then inspect the base repo state or invoke
        ConflictDetector for diagnostics.
        """
        branch = self._branch(agent_id)
        try:
            subprocess.run(
                ["git", "merge", "--no-edit", branch],
                cwd=self._base_repo, check=True, capture_output=True,
            )
            logger.info("Merged %s into %s", branch, self._base_branch)
            return True
        except subprocess.CalledProcessError as e:
            logger.warning("Merge of %s failed: %s", branch, e.stderr.decode("utf-8", "replace"))
            # Abort so the base repo is left clean
            subprocess.run(["git", "merge", "--abort"], cwd=self._base_repo, capture_output=True)
            return False

    def cleanup(self, agent_id: str) -> None:
        """Remove the worktree and delete the branch."""
        path = self._path(agent_id)
        branch = self._branch(agent_id)
        if path.exists():
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(path)],
                cwd=self._base_repo, capture_output=True,
            )
            # Belt-and-suspenders: remove dir if git didn't
            if path.exists():
                shutil.rmtree(path, ignore_errors=True)
        # Delete the branch (may fail if branch is current — that's OK)
        subprocess.run(
            ["git", "branch", "-D", branch],
            cwd=self._base_repo, capture_output=True,
        )
        logger.info("Cleaned up worktree for %s", agent_id)

    def list_agents(self) -> list[str]:
        """List agent_ids with active worktrees."""
        if not self._worktree_root.exists():
            return []
        return [p.name for p in self._worktree_root.iterdir() if p.is_dir()]

    def path_for(self, agent_id: str) -> str | None:
        """Return the worktree path for an agent, or None if no worktree."""
        path = self._path(agent_id)
        return str(path) if path.exists() else None
