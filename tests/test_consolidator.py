# tests/test_consolidator.py
"""Test Consolidator — Stage 1 memory compression."""
import pytest
import json
from pathlib import Path


def test_consolidator_imports():
    from src.memory.consolidator import Consolidator
    assert Consolidator is not None


def test_consolidator_init(tmp_path):
    from src.memory.consolidator import Consolidator
    c = Consolidator(str(tmp_path))
    assert c.history_path == tmp_path / "history.jsonl"
    assert c.cursor_path == tmp_path / ".cursor"


def test_append_to_history(tmp_path):
    from src.memory.consolidator import Consolidator
    c = Consolidator(str(tmp_path))

    c.append([
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"},
    ], summary="Greeting exchange")

    history = tmp_path / "history.jsonl"
    assert history.exists()
    lines = history.read_text().strip().split("\n")
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["summary"] == "Greeting exchange"
    assert entry["message_count"] == 2


def test_cursor_tracking(tmp_path):
    from src.memory.consolidator import Consolidator
    c = Consolidator(str(tmp_path))

    c.append([{"role": "user", "content": "msg1"}], summary="s1")
    c.append([{"role": "user", "content": "msg2"}], summary="s2")

    cursor = c.get_cursor()
    assert cursor == 2  # Two entries appended


def test_get_new_entries_since_cursor(tmp_path):
    from src.memory.consolidator import Consolidator
    c = Consolidator(str(tmp_path))

    c.append([{"role": "user", "content": "msg1"}], summary="s1")
    # Simulate a previous cursor at position 0
    c.set_dream_cursor(0)

    c.append([{"role": "user", "content": "msg2"}], summary="s2")

    new_entries = c.get_entries_since_dream_cursor()
    assert len(new_entries) == 2  # Both entries since cursor was 0


def test_dream_cursor_advances(tmp_path):
    from src.memory.consolidator import Consolidator
    c = Consolidator(str(tmp_path))

    c.append([{"role": "user", "content": "msg1"}], summary="s1")
    c.append([{"role": "user", "content": "msg2"}], summary="s2")

    c.set_dream_cursor(2)
    new = c.get_entries_since_dream_cursor()
    assert len(new) == 0  # No new entries since cursor is at end
