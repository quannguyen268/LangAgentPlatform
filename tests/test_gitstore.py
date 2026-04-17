# tests/test_gitstore.py
"""Test GitStore for memory file versioning."""
import pytest
from pathlib import Path


def test_gitstore_imports():
    from src.memory.gitstore import GitStore
    assert GitStore is not None


def test_gitstore_init_creates_repo(tmp_path):
    from src.memory.gitstore import GitStore
    store = GitStore(str(tmp_path / "memory"))
    store.init()
    assert (tmp_path / "memory" / ".git").exists()


def test_gitstore_auto_commit(tmp_path):
    from src.memory.gitstore import GitStore
    mem_dir = tmp_path / "memory"
    mem_dir.mkdir()
    store = GitStore(str(mem_dir), tracked_files=["test.md"])
    store.init()

    # Write a file and commit
    (mem_dir / "test.md").write_text("Hello world")
    sha = store.auto_commit("Initial content")
    assert sha is not None
    assert len(sha) >= 7  # Short SHA


def test_gitstore_no_commit_if_unchanged(tmp_path):
    from src.memory.gitstore import GitStore
    mem_dir = tmp_path / "memory"
    mem_dir.mkdir()
    store = GitStore(str(mem_dir), tracked_files=["test.md"])
    store.init()

    (mem_dir / "test.md").write_text("Hello world")
    store.auto_commit("First")

    # No changes — should return None
    sha = store.auto_commit("No changes")
    assert sha is None


def test_gitstore_log_commits(tmp_path):
    from src.memory.gitstore import GitStore
    mem_dir = tmp_path / "memory"
    mem_dir.mkdir()
    store = GitStore(str(mem_dir), tracked_files=["test.md"])
    store.init()

    (mem_dir / "test.md").write_text("Version 1")
    store.auto_commit("v1")
    (mem_dir / "test.md").write_text("Version 2")
    store.auto_commit("v2")

    log = store.log_commits(limit=5)
    assert len(log) >= 2
    assert "v2" in log[0]["message"]


def test_gitstore_get_diff(tmp_path):
    from src.memory.gitstore import GitStore
    mem_dir = tmp_path / "memory"
    mem_dir.mkdir()
    store = GitStore(str(mem_dir), tracked_files=["test.md"])
    store.init()

    (mem_dir / "test.md").write_text("Version 1")
    sha1 = store.auto_commit("v1")
    (mem_dir / "test.md").write_text("Version 2")
    sha2 = store.auto_commit("v2")

    diff = store.get_diff(sha2)
    assert "Version" in diff


def test_gitstore_restore(tmp_path):
    from src.memory.gitstore import GitStore
    mem_dir = tmp_path / "memory"
    mem_dir.mkdir()
    store = GitStore(str(mem_dir), tracked_files=["test.md"])
    store.init()

    (mem_dir / "test.md").write_text("Version 1")
    sha1 = store.auto_commit("v1")
    (mem_dir / "test.md").write_text("Version 2")
    store.auto_commit("v2")

    store.restore_commit(sha1)
    assert (mem_dir / "test.md").read_text() == "Version 1"
