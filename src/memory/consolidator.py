# src/memory/consolidator.py
"""Consolidator — Stage 1 memory compression.

Summarizes old conversation messages into history.jsonl entries.
Cursor-based and incremental — only processes new messages.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_MAX_CHUNK_MESSAGES = 60


class Consolidator:
    """Summarize conversations into persistent history entries."""

    def __init__(self, memory_dir: str):
        self.memory_dir = Path(memory_dir)
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.history_path = self.memory_dir / "history.jsonl"
        self.cursor_path = self.memory_dir / ".cursor"
        self.dream_cursor_path = self.memory_dir / ".dream_cursor"

    def append(self, messages: list[dict], summary: str) -> None:
        """Append a consolidated summary entry to history.jsonl.

        Args:
            messages: The original messages that were summarized
            summary: LLM-generated summary of the messages
        """
        entry = {
            "timestamp": time.time(),
            "summary": summary,
            "message_count": len(messages),
        }
        with open(self.history_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        # Advance cursor
        cursor = self.get_cursor()
        self._write_cursor(self.cursor_path, cursor + 1)

    def get_cursor(self) -> int:
        """Get the current consolidation cursor (number of entries written)."""
        return self._read_cursor(self.cursor_path)

    def get_dream_cursor(self) -> int:
        """Get the dream cursor (last entry processed by Dream)."""
        return self._read_cursor(self.dream_cursor_path)

    def set_dream_cursor(self, value: int) -> None:
        """Set the dream cursor to a specific position."""
        self._write_cursor(self.dream_cursor_path, value)

    def get_entries_since_dream_cursor(self) -> list[dict]:
        """Get all history entries since the dream cursor."""
        dream_cursor = self.get_dream_cursor()
        all_entries = self._read_all_entries()
        return all_entries[dream_cursor:]

    def get_all_entries(self) -> list[dict]:
        """Read all history entries."""
        return self._read_all_entries()

    def _read_all_entries(self) -> list[dict]:
        if not self.history_path.exists():
            return []
        entries = []
        for line in self.history_path.read_text(encoding="utf-8").strip().split("\n"):
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return entries

    def _read_cursor(self, path: Path) -> int:
        if path.exists():
            try:
                return int(path.read_text().strip())
            except (ValueError, OSError):
                return 0
        return 0

    def _write_cursor(self, path: Path, value: int) -> None:
        path.write_text(str(value))
