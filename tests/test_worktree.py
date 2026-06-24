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


def test_validate_rejects_path_traversal(git_repo, tmp_path):
    """agent_id must not allow ../ traversal or shell metacharacters."""
    mgr = WorktreeManager(base_repo=str(git_repo), worktree_root=str(tmp_path / "wt"))
    for bad in ["../evil", "a/b", "a b", "-f", "", ".hidden", "a;b"]:
        with pytest.raises(ValueError):
            mgr.create(bad)
        with pytest.raises(ValueError):
            mgr.cleanup(bad)


def test_cleanup_idempotent(git_repo, tmp_path):
    """Calling cleanup twice (or on an unknown agent) must not raise."""
    mgr = WorktreeManager(base_repo=str(git_repo), worktree_root=str(tmp_path / "wt"))
    mgr.create("a1")
    mgr.cleanup("a1")
    # Second cleanup on the same agent — no raise
    mgr.cleanup("a1")
    # Cleanup on an agent that was never created — no raise
    mgr.cleanup("never-existed")


def test_path_for_returns_none_for_unknown(git_repo, tmp_path):
    mgr = WorktreeManager(base_repo=str(git_repo), worktree_root=str(tmp_path / "wt"))
    assert mgr.path_for("never-existed") is None


def test_merge_detailed_distinguishes_conflict(git_repo, tmp_path):
    """merge_detailed reports conflict=True only for actual conflicts."""
    from src.subagent.worktree import MergeResult

    mgr = WorktreeManager(base_repo=str(git_repo), worktree_root=str(tmp_path / "wt"))

    # Case 1: branch doesn't exist → failure, but NOT conflict
    result = mgr.merge_detailed("phantom-agent-id-abc")
    assert result.ok is False
    assert result.conflict is False

    # Case 2: actual merge conflict
    # Modify README on main first
    (git_repo / "README.md").write_text("main line\n")
    subprocess.run(["git", "add", "."], cwd=git_repo, check=True)
    subprocess.run(["git", "commit", "-m", "main edit"], cwd=git_repo, check=True, capture_output=True)

    # Create a branch that changed the same file differently — starts from
    # BEFORE the main edit to ensure a real conflict.
    subprocess.run(
        ["git", "checkout", "-b", "agent/a1", "HEAD~1"],
        cwd=git_repo, check=True, capture_output=True,
    )
    (git_repo / "README.md").write_text("branch line\n")
    subprocess.run(["git", "add", "."], cwd=git_repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "branch edit"],
        cwd=git_repo, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "checkout", "main"],
        cwd=git_repo, check=True, capture_output=True,
    )

    result = mgr.merge_detailed("a1")
    assert result.ok is False
    assert result.conflict is True
    # Base repo should be clean (abort worked)
    assert not (git_repo / ".git" / "MERGE_HEAD").exists()


@pytest.mark.asyncio
async def test_async_wrappers_smoke(git_repo, tmp_path):
    """acreate/apath_for/acleanup match their sync counterparts."""
    mgr = WorktreeManager(base_repo=str(git_repo), worktree_root=str(tmp_path / "wt"))
    path = await mgr.acreate("a1")
    assert Path(path).exists()
    assert await mgr.apath_for("a1") == path
    agents = await mgr.alist_agents()
    assert "a1" in agents
    await mgr.acleanup("a1")
    assert await mgr.apath_for("a1") is None
