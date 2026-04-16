"""Test PermissionManager with modes and rules."""
import pytest


def test_permission_manager_imports():
    from src.permissions.manager import PermissionManager, PermissionMode
    assert PermissionManager is not None


def test_permission_modes():
    from src.permissions.manager import PermissionMode
    assert PermissionMode.DEFAULT == "default"
    assert PermissionMode.AUTO == "auto"
    assert PermissionMode.PLAN == "plan"


def test_auto_mode_allows_everything():
    from src.permissions.manager import PermissionManager, PermissionMode
    pm = PermissionManager(mode=PermissionMode.AUTO)
    result = pm.check("exec", {"command": "rm -rf /"})
    assert result.action == "allow"


def test_plan_mode_blocks_writes():
    from src.permissions.manager import PermissionManager, PermissionMode
    pm = PermissionManager(mode=PermissionMode.PLAN)
    # Read tools should be allowed
    assert pm.check("read_file", {"path": "foo.py"}).action == "allow"
    assert pm.check("glob", {"pattern": "*.py"}).action == "allow"
    assert pm.check("grep", {"pattern": "test"}).action == "allow"
    assert pm.check("web_search", {"query": "test"}).action == "allow"
    assert pm.check("web_fetch", {"url": "http://test"}).action == "allow"
    # Write tools should be denied
    assert pm.check("write_file", {"path": "foo.py"}).action == "deny"
    assert pm.check("edit_file", {"path": "foo.py"}).action == "deny"
    assert pm.check("exec", {"command": "echo hi"}).action == "deny"
    assert pm.check("host_execute", {"bridge": "spotify"}).action == "deny"


def test_default_mode_asks_for_write_tools():
    from src.permissions.manager import PermissionManager, PermissionMode
    pm = PermissionManager(mode=PermissionMode.DEFAULT)
    # Read tools allowed
    assert pm.check("read_file", {"path": "foo.py"}).action == "allow"
    # Write tools require approval
    assert pm.check("exec", {"command": "echo hi"}).action == "ask"
    assert pm.check("write_file", {"path": "foo.py"}).action == "ask"


def test_sensitive_path_always_denied():
    from src.permissions.manager import PermissionManager, PermissionMode
    pm = PermissionManager(mode=PermissionMode.AUTO)
    result = pm.check("read_file", {"path": "/home/user/.ssh/id_rsa"})
    assert result.action == "deny"
    assert "sensitive" in result.reason.lower()
