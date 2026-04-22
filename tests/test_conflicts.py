"""Test ConflictDetector — overlap between agent worktrees."""
import pytest
import subprocess
from pathlib import Path
from src.subagent.conflicts import ConflictDetector, Conflict
from src.subagent.worktree import WorktreeManager


@pytest.fixture
def git_repo(tmp_path):
    """Create a real git repo with a multi-line file."""
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    (tmp_path / "file.py").write_text("line1\nline2\nline3\nline4\nline5\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True)
    return tmp_path


def test_no_overlap_when_disjoint(git_repo, tmp_path):
    mgr = WorktreeManager(base_repo=str(git_repo), worktree_root=str(tmp_path / "wt"))
    p_a = Path(mgr.create("a"))
    p_b = Path(mgr.create("b"))
    # a edits file.py line 1, b edits unrelated.py
    (p_a / "file.py").write_text("LINE1_NEW\nline2\nline3\nline4\nline5\n")
    (p_b / "unrelated.py").write_text("different file\n")
    for p in (p_a, p_b):
        subprocess.run(["git", "add", "."], cwd=p, check=True)
        subprocess.run(["git", "commit", "-m", "edit"], cwd=p, check=True, capture_output=True)

    detector = ConflictDetector(base_repo=str(git_repo), base_branch="main")
    conflicts = detector.detect({"a": str(p_a), "b": str(p_b)})
    assert conflicts == []


def test_same_file_different_lines_is_medium(git_repo, tmp_path):
    mgr = WorktreeManager(base_repo=str(git_repo), worktree_root=str(tmp_path / "wt"))
    p_a = Path(mgr.create("a"))
    p_b = Path(mgr.create("b"))
    # a edits line 1, b edits line 5 — same file, different hunks
    (p_a / "file.py").write_text("LINE1_NEW\nline2\nline3\nline4\nline5\n")
    (p_b / "file.py").write_text("line1\nline2\nline3\nline4\nLINE5_NEW\n")
    for p in (p_a, p_b):
        subprocess.run(["git", "add", "."], cwd=p, check=True)
        subprocess.run(["git", "commit", "-m", "edit"], cwd=p, check=True, capture_output=True)

    detector = ConflictDetector(base_repo=str(git_repo), base_branch="main")
    conflicts = detector.detect({"a": str(p_a), "b": str(p_b)})
    assert len(conflicts) == 1
    assert conflicts[0].file == "file.py"
    assert conflicts[0].severity == "medium"
    assert {conflicts[0].agent_a, conflicts[0].agent_b} == {"a", "b"}


def test_same_lines_is_high(git_repo, tmp_path):
    mgr = WorktreeManager(base_repo=str(git_repo), worktree_root=str(tmp_path / "wt"))
    p_a = Path(mgr.create("a"))
    p_b = Path(mgr.create("b"))
    # both edit line 3
    (p_a / "file.py").write_text("line1\nline2\nA_EDIT\nline4\nline5\n")
    (p_b / "file.py").write_text("line1\nline2\nB_EDIT\nline4\nline5\n")
    for p in (p_a, p_b):
        subprocess.run(["git", "add", "."], cwd=p, check=True)
        subprocess.run(["git", "commit", "-m", "edit"], cwd=p, check=True, capture_output=True)

    detector = ConflictDetector(base_repo=str(git_repo), base_branch="main")
    conflicts = detector.detect({"a": str(p_a), "b": str(p_b)})
    assert len(conflicts) == 1
    assert conflicts[0].severity == "high"
