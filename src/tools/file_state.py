# src/tools/file_state.py
"""FileStateTracker — read-before-edit warnings and staleness detection."""
from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ReadState:
    mtime: float
    content_hash: str
    offset: int = 0
    limit: int = 0


def _hash_content(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()


class FileStateTracker:
    """Track file reads to warn before stale edits."""

    def __init__(self):
        self._states: dict[str, ReadState] = {}

    def record_read(self, path: str, content: str, offset: int = 0, limit: int = 0) -> None:
        """Record that a file was read with given content."""
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = 0.0
        self._states[path] = ReadState(
            mtime=mtime,
            content_hash=_hash_content(content),
            offset=offset,
            limit=limit,
        )

    def check_before_edit(self, path: str) -> str | None:
        """Check if it's safe to edit. Returns warning string or None if OK."""
        if path not in self._states:
            return f"Warning: {path} has not been read yet. Read before editing."

        state = self._states[path]
        try:
            current_mtime = os.path.getmtime(path)
        except OSError:
            return f"Warning: {path} no longer exists."

        if current_mtime != state.mtime:
            # mtime changed — check content hash to avoid false positives from touch
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    current_hash = _hash_content(f.read())
            except OSError:
                return f"Warning: {path} cannot be read for staleness check."

            if current_hash != state.content_hash:
                return f"Warning: {path} was modified since last read. Re-read before editing."

        return None  # Safe to edit

    def clear(self) -> None:
        """Reset all tracked state."""
        self._states.clear()
