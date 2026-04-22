"""ConflictDetector — detect overlapping changes across agent worktrees (GAP-6).

Runs ``git diff`` for each worktree against the base branch, then compares the
changed-line ranges pairwise:
  - same lines modified by both agents → severity="high"
  - same file modified by both but disjoint hunks → severity="medium"
"""
from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass
from itertools import combinations

logger = logging.getLogger(__name__)

# Matches "@@ -L,S +L,S @@" hunk headers (S optional on either side)
_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")

_GIT_TIMEOUT_SECONDS = 30


@dataclass
class Conflict:
    file: str
    agent_a: str
    agent_b: str
    severity: str  # "high" | "medium"


def _changed_files(worktree: str, base_branch: str) -> set[str]:
    """Return the set of files changed in worktree vs base_branch."""
    result = subprocess.run(
        ["git", "diff", "--name-only", base_branch, "HEAD"],
        cwd=worktree, capture_output=True, text=True, check=False,
        timeout=_GIT_TIMEOUT_SECONDS,
    )
    return {f.strip() for f in result.stdout.splitlines() if f.strip()}


def _changed_line_ranges(worktree: str, base_branch: str, file: str) -> list[tuple[int, int]]:
    """Return list of (start_line, line_count) tuples for changed regions in file."""
    result = subprocess.run(
        ["git", "diff", "-U0", base_branch, "HEAD", "--", file],
        cwd=worktree, capture_output=True, text=True, check=False,
        timeout=_GIT_TIMEOUT_SECONDS,
    )
    ranges: list[tuple[int, int]] = []
    for line in result.stdout.splitlines():
        m = _HUNK_RE.match(line)
        if not m:
            continue
        start = int(m.group(1))
        count = int(m.group(2)) if m.group(2) else 1
        ranges.append((start, count))
    return ranges


def _ranges_overlap(a: list[tuple[int, int]], b: list[tuple[int, int]]) -> bool:
    for (a_start, a_count) in a:
        a_end = a_start + a_count - 1
        for (b_start, b_count) in b:
            b_end = b_start + b_count - 1
            if not (a_end < b_start or b_end < a_start):
                return True
    return False


class ConflictDetector:
    """Pairwise comparison of git diffs across agent worktrees."""

    def __init__(self, base_repo: str, base_branch: str = "main"):
        self._base_repo = base_repo
        self._base_branch = base_branch

    def detect(self, worktrees: dict[str, str]) -> list[Conflict]:
        """Analyze pairwise conflicts across worktrees.

        Args:
            worktrees: mapping of agent_id → worktree path

        Returns:
            List of Conflict records. Empty list means no overlaps.
        """
        # Collect changed files per agent
        files_by_agent: dict[str, set[str]] = {
            aid: _changed_files(path, self._base_branch) for aid, path in worktrees.items()
        }

        conflicts: list[Conflict] = []
        for (agent_a, files_a), (agent_b, files_b) in combinations(files_by_agent.items(), 2):
            overlap_files = files_a & files_b
            for f in overlap_files:
                ranges_a = _changed_line_ranges(worktrees[agent_a], self._base_branch, f)
                ranges_b = _changed_line_ranges(worktrees[agent_b], self._base_branch, f)
                severity = "high" if _ranges_overlap(ranges_a, ranges_b) else "medium"
                conflicts.append(Conflict(file=f, agent_a=agent_a, agent_b=agent_b, severity=severity))
        return conflicts
