# src/memory/gitstore.py
"""GitStore — Git versioning for memory files using dulwich (pure Python)."""
from __future__ import annotations

import logging
import time
from pathlib import Path

from dulwich.repo import Repo
from dulwich.objects import Blob, Tree, Commit
from dulwich import porcelain

logger = logging.getLogger(__name__)


class GitStore:
    """Track memory file changes with Git for audit trail and restore."""

    def __init__(self, path: str, tracked_files: list[str] | None = None):
        self.path = Path(path)
        self.tracked_files = tracked_files or ["SOUL.md", "USER.md", "MEMORY.md"]
        self._repo: Repo | None = None

    def init(self) -> None:
        """Initialize git repo if it doesn't exist."""
        self.path.mkdir(parents=True, exist_ok=True)
        git_dir = self.path / ".git"
        if git_dir.exists():
            self._repo = Repo(str(self.path))
        else:
            self._repo = Repo.init(str(self.path))
            # Create .gitignore
            gitignore = self.path / ".gitignore"
            gitignore.write_text("*.jsonl\n.cursor\n.dream_cursor\n")
            porcelain.add(self._repo, paths=[".gitignore"])
            porcelain.commit(
                self._repo,
                message=b"init: memory store",
                author=b"LangAgent <langagent@local>",
                committer=b"LangAgent <langagent@local>",
            )
            logger.info("GitStore initialized at %s", self.path)

    def auto_commit(self, message: str) -> str | None:
        """Stage tracked files and commit if there are changes.

        Returns:
            Short SHA of the commit, or None if nothing changed.
        """
        if not self._repo:
            self.init()

        # Stage tracked files that exist
        paths_to_add = []
        for fname in self.tracked_files:
            fpath = self.path / fname
            if fpath.exists():
                paths_to_add.append(fname)

        if not paths_to_add:
            return None

        porcelain.add(self._repo, paths=paths_to_add)

        # Check if there are staged changes
        status = porcelain.status(self._repo)
        staged_changes = status.staged["add"] or status.staged["modify"] or status.staged["delete"]
        if not staged_changes:
            return None

        sha = porcelain.commit(
            self._repo,
            message=message.encode("utf-8"),
            author=b"LangAgent Dream <langagent@local>",
            committer=b"LangAgent Dream <langagent@local>",
        )
        short_sha = sha.decode("ascii")[:7] if isinstance(sha, bytes) else str(sha)[:7]
        logger.info("GitStore commit: %s — %s", short_sha, message)
        return short_sha

    def log_commits(self, limit: int = 10) -> list[dict]:
        """Return recent commits as list of dicts."""
        if not self._repo:
            return []

        result = []
        try:
            walker = self._repo.get_walker(max_entries=limit)
            for entry in walker:
                commit = entry.commit
                result.append({
                    "sha": commit.id.decode("ascii")[:7],
                    "full_sha": commit.id.decode("ascii"),
                    "message": commit.message.decode("utf-8", errors="replace").strip(),
                    "timestamp": commit.commit_time,
                    "author": commit.author.decode("utf-8", errors="replace"),
                })
        except Exception as e:
            logger.warning("GitStore log failed: %s", e)
        return result

    def get_diff(self, sha: str) -> str:
        """Get the diff for a specific commit."""
        if not self._repo:
            return ""

        try:
            from dulwich.diff_tree import tree_changes
            # Find the full SHA
            full_sha = self._resolve_sha(sha)
            if not full_sha:
                return f"Commit {sha} not found"

            commit = self._repo[full_sha]
            parent_sha = commit.parents[0] if commit.parents else None

            if parent_sha:
                parent_tree = self._repo[self._repo[parent_sha].tree]
                current_tree = self._repo[commit.tree]
                changes = tree_changes(self._repo.object_store, parent_tree.id, current_tree.id)
                lines = []
                for change in changes:
                    old_path = change.old.path.decode() if change.old.path else "/dev/null"
                    new_path = change.new.path.decode() if change.new.path else "/dev/null"
                    lines.append(f"--- {old_path}")
                    lines.append(f"+++ {new_path}")
                    if change.new.sha:
                        new_content = self._repo[change.new.sha].data.decode("utf-8", errors="replace")
                        lines.append(new_content[:500])
                return "\n".join(lines)
            return "Initial commit — no parent to diff against"
        except Exception as e:
            return f"Diff error: {e}"

    def restore_commit(self, sha: str) -> bool:
        """Restore tracked files to the state at a given commit."""
        if not self._repo:
            return False

        try:
            full_sha = self._resolve_sha(sha)
            if not full_sha:
                return False

            commit = self._repo[full_sha]
            tree = self._repo[commit.tree]

            for item in tree.items():
                name = item.path.decode()
                if name in self.tracked_files:
                    blob = self._repo[item.sha]
                    (self.path / name).write_bytes(blob.data)

            self.auto_commit(f"restore: reverted to {sha}")
            return True
        except Exception as e:
            logger.error("GitStore restore failed: %s", e)
            return False

    def _resolve_sha(self, short_sha: str) -> bytes | None:
        """Resolve a short SHA to full SHA bytes."""
        try:
            for entry in self._repo.get_walker():
                full = entry.commit.id.decode("ascii")
                if full.startswith(short_sha):
                    return entry.commit.id
        except Exception:
            pass
        return None
