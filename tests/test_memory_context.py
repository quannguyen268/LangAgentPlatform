"""Test memory context injection."""
import pytest
from pathlib import Path

def test_context_builder_imports():
    from src.memory.context import build_memory_context
    assert build_memory_context is not None

def test_build_context_from_workspace(tmp_path):
    from src.memory.context import build_memory_context
    (tmp_path / "IDENTITY.md").write_text("I am LangAgent.")
    (tmp_path / "AGENT.md").write_text("Be helpful.")
    (tmp_path / "MEMORY.md").write_text("User likes Python.")
    context = build_memory_context(str(tmp_path))
    assert "I am LangAgent" in context
    assert "Be helpful" in context
    assert "User likes Python" in context

def test_build_context_missing_files(tmp_path):
    from src.memory.context import build_memory_context
    (tmp_path / "IDENTITY.md").write_text("I am LangAgent.")
    context = build_memory_context(str(tmp_path))
    assert "I am LangAgent" in context

def test_build_context_empty_workspace(tmp_path):
    from src.memory.context import build_memory_context
    context = build_memory_context(str(tmp_path))
    assert isinstance(context, str)

def test_build_context_per_user(tmp_path):
    from src.memory.context import build_memory_context
    (tmp_path / "IDENTITY.md").write_text("I am LangAgent.")
    user_dir = tmp_path / "users" / "alice"
    user_dir.mkdir(parents=True)
    (user_dir / "USER.md").write_text("Alice prefers dark mode.")
    context = build_memory_context(str(tmp_path), user_id="alice")
    assert "Alice prefers dark mode" in context
    assert "I am LangAgent" in context
