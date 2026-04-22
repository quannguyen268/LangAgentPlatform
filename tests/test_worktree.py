"""Test WorktreeManager — per-agent git worktree isolation."""
import pytest
import subprocess
from pathlib import Path
from src.subagent.worktree import WorktreeManager


@pytest.fixture
def git_repo(tmp_path):
    """Create a real git repo with one initial commit."""
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("initial\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True)
    return tmp_path


def test_create_and_cleanup(git_repo, tmp_path):
    mgr = WorktreeManager(base_repo=str(git_repo), worktree_root=str(tmp_path / "wt"))
    path = mgr.create("agent-1")
    assert Path(path).exists()
    # Branch should exist
    result = subprocess.run(
        ["git", "branch", "--list", "agent/agent-1"],
        cwd=git_repo, capture_output=True, text=True,
    )
    assert "agent/agent-1" in result.stdout

    mgr.cleanup("agent-1")
    assert not Path(path).exists()


def test_list_agents(git_repo, tmp_path):
    mgr = WorktreeManager(base_repo=str(git_repo), worktree_root=str(tmp_path / "wt"))
    mgr.create("a1")
    mgr.create("a2")
    agents = mgr.list_agents()
    assert set(agents) == {"a1", "a2"}
    mgr.cleanup("a1")
    mgr.cleanup("a2")


def test_merge_clean(git_repo, tmp_path):
    mgr = WorktreeManager(base_repo=str(git_repo), worktree_root=str(tmp_path / "wt"))
    path = mgr.create("a1")
    # Make a commit in the worktree
    (Path(path) / "hello.txt").write_text("hi\n")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "add hello"], cwd=path, check=True, capture_output=True)

    merged = mgr.merge("a1")
    assert merged is True
    # File should appear in base repo
    assert (git_repo / "hello.txt").exists()
    mgr.cleanup("a1")
