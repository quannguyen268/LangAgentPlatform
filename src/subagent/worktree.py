"""WorktreeManager — per-agent git worktree lifecycle.

Each sub-agent that works on code gets its own branch ``agent/{agent_id}`` and
a worktree under ``worktree_root/{agent_id}``. On ``recall_agent`` the master
asks the manager to ``merge()`` and then ``cleanup()``.

The sync API is the primary surface and is used directly in tests and CLI
tools. For callers running inside an asyncio loop (the agent runtime), use
``acreate`` / ``amerge`` / ``acleanup`` / ``apath_for`` / ``alist_agents``,
which wrap the sync methods in ``asyncio.to_thread`` so git I/O does not
block the event loop.

Agent IDs are validated against ``_AGENT_ID_RE`` before any subprocess call.
This guards against path traversal (``../``) and shell-metacharacter abuse
if an ID is ever partially LLM-generated.
"""
from __future__ import annotations

import asyncio
import logging
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Agent IDs must start alphanumeric, then letters/digits/underscore/hyphen only.
# Disallows "/", "..", spaces, and control characters. Caps length at 64.
_AGENT_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_\-]{0,63}$")

_GIT_TIMEOUT_SECONDS = 30


@dataclass
class MergeResult:
    """Result of attempting to merge an agent's branch into base.

    Attributes:
        ok: True if the merge completed cleanly.
        conflict: True if the merge stopped due to conflicts (distinct from
            other failure modes like "branch does not exist" or "index
            locked"). Only meaningful when ``ok`` is False.
        stderr: Stderr from the failing git command (empty on success).
    """
    ok: bool
    conflict: bool = False
    stderr: str = ""


class WorktreeManager:
    """Manage git worktrees for sub-agents."""

    def __init__(self, base_repo: str, worktree_root: str, base_branch: str = "main"):
        self._base_repo = Path(base_repo).resolve()
        self._worktree_root = Path(worktree_root).resolve()
        self._worktree_root.mkdir(parents=True, exist_ok=True)
        self._base_branch = base_branch

    # ── Internal helpers ──────────────────────────────────────────────

    def _validate(self, agent_id: str) -> None:
        """Reject agent IDs that could escape the worktree root or confuse git."""
        if not _AGENT_ID_RE.match(agent_id):
            raise ValueError(f"Invalid agent_id: {agent_id!r}")

    def _branch(self, agent_id: str) -> str:
        return f"agent/{agent_id}"

    def _path(self, agent_id: str) -> Path:
        return self._worktree_root / agent_id

    def _assert_within_root(self, path: Path) -> None:
        """Belt-and-suspenders: ensure path is inside worktree_root before rmtree."""
        resolved = path.resolve()
        # Python 3.9+ has is_relative_to
        if not resolved.is_relative_to(self._worktree_root):
            raise ValueError(
                f"Refusing to operate on {resolved}: outside worktree_root "
                f"{self._worktree_root}"
            )

    # ── Public sync API ───────────────────────────────────────────────

    def create(self, agent_id: str) -> str:
        """Create a worktree with a fresh branch off base_branch. Returns the path."""
        self._validate(agent_id)
        path = self._path(agent_id)
        if path.exists():
            logger.warning("Worktree for %s already exists at %s", agent_id, path)
            return str(path)
        branch = self._branch(agent_id)
        try:
            subprocess.run(
                ["git", "worktree", "add", "-b", branch, str(path), self._base_branch],
                cwd=self._base_repo, check=True, capture_output=True,
                timeout=_GIT_TIMEOUT_SECONDS,
            )
        except subprocess.CalledProcessError as e:
            logger.error(
                "git worktree add failed for %s: %s",
                agent_id, e.stderr.decode("utf-8", "replace"),
            )
            raise
        logger.info("Created worktree %s on branch %s", path, branch)
        return str(path)

    def merge(self, agent_id: str) -> bool:
        """Merge the agent's branch back into base_branch.

        Returns True on clean merge, False on any failure (conflict or
        otherwise). Callers that need to distinguish conflict-vs-other-failure
        should call ``merge_detailed`` instead.
        """
        return self.merge_detailed(agent_id).ok

    def merge_detailed(self, agent_id: str) -> MergeResult:
        """Merge with distinguished conflict vs other-failure reporting."""
        self._validate(agent_id)
        branch = self._branch(agent_id)
        try:
            subprocess.run(
                ["git", "merge", "--no-edit", branch],
                cwd=self._base_repo, check=True, capture_output=True,
                timeout=_GIT_TIMEOUT_SECONDS,
            )
            logger.info("Merged %s into %s", branch, self._base_branch)
            return MergeResult(ok=True)
        except subprocess.CalledProcessError as e:
            stderr = e.stderr.decode("utf-8", "replace") if e.stderr else ""
            # A merge conflict leaves .git/MERGE_HEAD; other failures (unknown
            # branch, index lock, detached HEAD) don't.
            in_merge = (self._base_repo / ".git" / "MERGE_HEAD").exists()
            if in_merge:
                logger.warning("Merge of %s hit conflicts; aborting", branch)
                subprocess.run(
                    ["git", "merge", "--abort"],
                    cwd=self._base_repo, capture_output=True,
                    timeout=_GIT_TIMEOUT_SECONDS,
                )
                return MergeResult(ok=False, conflict=True, stderr=stderr)
            logger.warning("Merge of %s failed (not a conflict): %s", branch, stderr)
            return MergeResult(ok=False, conflict=False, stderr=stderr)

    def cleanup(self, agent_id: str) -> None:
        """Remove the worktree and delete the branch. Idempotent."""
        self._validate(agent_id)
        path = self._path(agent_id)
        branch = self._branch(agent_id)
        if path.exists():
            self._assert_within_root(path)
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(path)],
                cwd=self._base_repo, capture_output=True,
                timeout=_GIT_TIMEOUT_SECONDS,
            )
            # Belt-and-suspenders: remove dir if git didn't
            if path.exists():
                shutil.rmtree(path, ignore_errors=True)
        # Delete the branch (may fail if branch is current — that's OK)
        result = subprocess.run(
            ["git", "branch", "-D", branch],
            cwd=self._base_repo, capture_output=True,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", "replace") if result.stderr else ""
            logger.debug("git branch -D %s returned non-zero: %s", branch, stderr)
        logger.info("Cleaned up worktree for %s", agent_id)

    def list_agents(self) -> list[str]:
        """List agent_ids with active worktrees."""
        if not self._worktree_root.exists():
            return []
        return [p.name for p in self._worktree_root.iterdir() if p.is_dir()]

    def path_for(self, agent_id: str) -> Optional[str]:
        """Return the worktree path for an agent, or None if no worktree."""
        self._validate(agent_id)
        path = self._path(agent_id)
        return str(path) if path.exists() else None

    # ── Async wrappers ────────────────────────────────────────────────
    # Offload blocking git I/O to a thread so the asyncio event loop
    # isn't starved during a merge on a large repo.

    async def acreate(self, agent_id: str) -> str:
        return await asyncio.to_thread(self.create, agent_id)

    async def amerge(self, agent_id: str) -> bool:
        return await asyncio.to_thread(self.merge, agent_id)

    async def amerge_detailed(self, agent_id: str) -> MergeResult:
        return await asyncio.to_thread(self.merge_detailed, agent_id)

    async def acleanup(self, agent_id: str) -> None:
        return await asyncio.to_thread(self.cleanup, agent_id)

    async def alist_agents(self) -> list[str]:
        return await asyncio.to_thread(self.list_agents)

    async def apath_for(self, agent_id: str) -> Optional[str]:
        return await asyncio.to_thread(self.path_for, agent_id)
