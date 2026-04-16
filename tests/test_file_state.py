# tests/test_file_state.py
"""Test FileStateTracker for read-before-edit warnings."""
import pytest
import os
import hashlib
from pathlib import Path


def test_file_state_imports():
    from src.tools.file_state import FileStateTracker
    assert FileStateTracker is not None


def test_record_and_check_ok(tmp_path):
    from src.tools.file_state import FileStateTracker
    tracker = FileStateTracker()
    f = tmp_path / "test.py"
    f.write_text("print('hello')")

    tracker.record_read(str(f), f.read_text())
    warning = tracker.check_before_edit(str(f))
    assert warning is None  # No warning — file was read and unchanged


def test_check_without_read(tmp_path):
    from src.tools.file_state import FileStateTracker
    tracker = FileStateTracker()
    f = tmp_path / "test.py"
    f.write_text("print('hello')")

    warning = tracker.check_before_edit(str(f))
    assert warning is not None
    assert "not been read" in warning


def test_check_after_modification(tmp_path):
    from src.tools.file_state import FileStateTracker
    tracker = FileStateTracker()
    f = tmp_path / "test.py"
    f.write_text("print('hello')")
    tracker.record_read(str(f), f.read_text())

    # Modify the file externally
    f.write_text("print('modified')")

    warning = tracker.check_before_edit(str(f))
    assert warning is not None
    assert "modified" in warning.lower()


def test_no_false_positive_on_touch(tmp_path):
    """Touch (mtime change without content change) should NOT warn."""
    from src.tools.file_state import FileStateTracker
    tracker = FileStateTracker()
    f = tmp_path / "test.py"
    f.write_text("print('hello')")
    tracker.record_read(str(f), f.read_text())

    # Touch the file (change mtime, same content)
    os.utime(str(f), (os.path.getatime(str(f)) + 1, os.path.getmtime(str(f)) + 1))

    warning = tracker.check_before_edit(str(f))
    assert warning is None  # Content hash matches, no warning
