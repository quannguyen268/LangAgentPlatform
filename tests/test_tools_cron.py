"""Tests for src.tools.cron — init_cron_tools, set_current_context, schedule/list/cancel tasks."""

import asyncio
import json

import pytest

from src.config import SchedulerConfig
from src.tools.cron import (
    init_cron_tools,
    set_current_context,
    get_tasks_lock,
    schedule_task,
    list_tasks,
    cancel_task,
    _current_channel,
    _current_chat_id,
)
from src.tools import cron as cron_module


class TestInitCronTools:
    def test_sets_data_file(self):
        config = SchedulerConfig(data_file="/tmp/tasks.json")
        init_cron_tools(config)
        assert cron_module._data_file == "/tmp/tasks.json"

    def test_default_data_file(self):
        config = SchedulerConfig()
        init_cron_tools(config)
        assert cron_module._data_file == "./data/scheduled_tasks.json"


class TestSetCurrentContext:
    def test_sets_context_vars(self):
        set_current_context("telegram", "12345")
        assert _current_channel.get() == "telegram"
        assert _current_chat_id.get() == "12345"

    def test_overwrite_context(self):
        set_current_context("telegram", "111")
        set_current_context("slack", "222")
        assert _current_channel.get() == "slack"
        assert _current_chat_id.get() == "222"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _init_cron(tmp_path, filename="tasks.json"):
    """Initialize cron tools pointing at a temp tasks file and return the path."""
    tasks_file = tmp_path / filename
    init_cron_tools(SchedulerConfig(data_file=str(tasks_file)))
    return tasks_file


# ---------------------------------------------------------------------------
# TestGetTasksLock
# ---------------------------------------------------------------------------

class TestGetTasksLock:
    def test_raises_when_not_initialized(self):
        cron_module._tasks_lock = None
        with pytest.raises(RuntimeError, match="not initialized"):
            get_tasks_lock()

    def test_returns_lock_after_init(self, tmp_path):
        _init_cron(tmp_path)
        lock = get_tasks_lock()
        assert isinstance(lock, asyncio.Lock)


# ---------------------------------------------------------------------------
# TestScheduleTask
# ---------------------------------------------------------------------------

class TestScheduleTask:
    @pytest.mark.asyncio
    async def test_valid_cron_task(self, tmp_path):
        tasks_file = _init_cron(tmp_path)
        set_current_context("telegram", "123")

        result = await schedule_task.ainvoke({
            "prompt": "say hello",
            "schedule_type": "cron",
            "schedule_value": "* * * * *",
        })

        assert "Task scheduled" in result
        assert "cron" in result
        data = json.loads(tasks_file.read_text())
        assert len(data) == 1
        assert data[0]["type"] == "cron"
        assert data[0]["value"] == "* * * * *"
        assert data[0]["prompt"] == "say hello"
        assert data[0]["channel"] == "telegram"
        assert data[0]["chat_id"] == "123"
        assert data[0]["active"] is True

    @pytest.mark.asyncio
    async def test_valid_interval_task(self, tmp_path):
        tasks_file = _init_cron(tmp_path)
        set_current_context("telegram", "456")

        result = await schedule_task.ainvoke({
            "prompt": "check status",
            "schedule_type": "interval",
            "schedule_value": "3600",
        })

        assert "Task scheduled" in result
        data = json.loads(tasks_file.read_text())
        assert len(data) == 1
        assert data[0]["type"] == "interval"
        assert data[0]["value"] == "3600"

    @pytest.mark.asyncio
    async def test_valid_once_task(self, tmp_path):
        tasks_file = _init_cron(tmp_path)
        set_current_context("telegram", "789")

        result = await schedule_task.ainvoke({
            "prompt": "one-shot reminder",
            "schedule_type": "once",
            "schedule_value": "2026-03-01T10:00:00Z",
        })

        assert "Task scheduled" in result
        data = json.loads(tasks_file.read_text())
        assert len(data) == 1
        assert data[0]["type"] == "once"

    @pytest.mark.asyncio
    async def test_with_model_tier(self, tmp_path):
        tasks_file = _init_cron(tmp_path)
        set_current_context("telegram", "123")

        result = await schedule_task.ainvoke({
            "prompt": "analyze portfolio",
            "schedule_type": "cron",
            "schedule_value": "0 9 * * *",
            "model_tier": "advanced",
        })

        assert "Task scheduled" in result
        data = json.loads(tasks_file.read_text())
        assert len(data) == 1
        assert data[0]["model_tier"] == "advanced"

    @pytest.mark.asyncio
    async def test_without_model_tier(self, tmp_path):
        tasks_file = _init_cron(tmp_path)
        set_current_context("telegram", "123")

        result = await schedule_task.ainvoke({
            "prompt": "say hello",
            "schedule_type": "cron",
            "schedule_value": "* * * * *",
        })

        assert "Task scheduled" in result
        data = json.loads(tasks_file.read_text())
        assert len(data) == 1
        assert "model_tier" not in data[0]

    @pytest.mark.asyncio
    async def test_invalid_type(self, tmp_path):
        _init_cron(tmp_path)
        set_current_context("telegram", "123")

        result = await schedule_task.ainvoke({
            "prompt": "bad task",
            "schedule_type": "invalid",
            "schedule_value": "whatever",
        })

        assert "Invalid schedule_type" in result


# ---------------------------------------------------------------------------
# TestListTasks
# ---------------------------------------------------------------------------

class TestListTasks:
    @pytest.mark.asyncio
    async def test_empty_file(self, tmp_path):
        tasks_file = _init_cron(tmp_path)
        tasks_file.write_text(json.dumps([]))

        result = await list_tasks.ainvoke({})
        assert "No active" in result

    @pytest.mark.asyncio
    async def test_with_active_tasks(self, tmp_path):
        tasks_file = _init_cron(tmp_path)
        tasks_data = [
            {
                "id": "abc",
                "prompt": "say hello every minute",
                "type": "cron",
                "value": "* * * * *",
                "channel": "telegram",
                "chat_id": "123",
                "created_at": "2026-01-01T00:00:00Z",
                "last_run": None,
                "active": True,
            },
            {
                "id": "def",
                "prompt": "inactive task",
                "type": "interval",
                "value": "60",
                "channel": "telegram",
                "chat_id": "123",
                "created_at": "2026-01-01T00:00:00Z",
                "last_run": None,
                "active": False,
            },
        ]
        tasks_file.write_text(json.dumps(tasks_data))

        result = await list_tasks.ainvoke({})
        assert "abc" in result
        assert "cron" in result
        assert "say hello" in result
        # Inactive task should NOT appear
        assert "def" not in result

    @pytest.mark.asyncio
    async def test_no_file(self, tmp_path):
        _init_cron(tmp_path, filename="nonexistent.json")
        # File does not exist on disk
        result = await list_tasks.ainvoke({})
        assert "No active" in result


# ---------------------------------------------------------------------------
# TestCancelTask
# ---------------------------------------------------------------------------

class TestCancelTask:
    @pytest.mark.asyncio
    async def test_cancel_found(self, tmp_path):
        tasks_file = _init_cron(tmp_path)
        tasks_data = [
            {
                "id": "abc",
                "prompt": "test task",
                "type": "cron",
                "value": "* * * * *",
                "channel": "telegram",
                "chat_id": "123",
                "created_at": "2026-01-01T00:00:00Z",
                "last_run": None,
                "active": True,
            },
        ]
        tasks_file.write_text(json.dumps(tasks_data))

        result = await cancel_task.ainvoke({"task_id": "abc"})
        assert "cancelled" in result

        updated = json.loads(tasks_file.read_text())
        assert updated[0]["active"] is False

    @pytest.mark.asyncio
    async def test_cancel_not_found(self, tmp_path):
        tasks_file = _init_cron(tmp_path)
        tasks_data = [
            {
                "id": "abc",
                "prompt": "test task",
                "type": "cron",
                "value": "* * * * *",
                "channel": "telegram",
                "chat_id": "123",
                "created_at": "2026-01-01T00:00:00Z",
                "last_run": None,
                "active": True,
            },
        ]
        tasks_file.write_text(json.dumps(tasks_data))

        result = await cancel_task.ainvoke({"task_id": "zzz"})
        assert "not found" in result


# ---------------------------------------------------------------------------
# TestListActiveTasksStructured — structured task listing for /v1/tasks endpoint
# ---------------------------------------------------------------------------


@pytest.fixture
def cron_data_file(tmp_path, monkeypatch):
    """Initialize cron tools with a tmp data file."""
    from src.tools import cron

    data_file = tmp_path / "tasks.json"
    monkeypatch.setattr(cron, "_data_file", str(data_file))
    monkeypatch.setattr(cron, "_tasks_lock", asyncio.Lock())
    return data_file


@pytest.mark.asyncio
async def test_list_active_tasks_structured_returns_api_shape(cron_data_file):
    """The structured listing must produce the keys the API endpoint promises."""
    from src.tools.cron import list_active_tasks_structured

    raw_tasks = [
        {
            "id": "abc12345",
            "prompt": "Daily standup summary",
            "type": "cron",
            "value": "0 9 * * *",
            "channel": "telegram",
            "chat_id": "100",
            "created_at": "2026-04-20T11:23:00+00:00",
            "last_run": None,
            "active": True,
            "model_tier": "standard",
        },
        {
            "id": "deadbeef",
            "prompt": "old job",
            "type": "interval",
            "value": "60",
            "channel": "cli",
            "chat_id": None,
            "created_at": "2026-04-20T11:00:00+00:00",
            "last_run": "2026-04-21T11:00:00+00:00",
            "active": False,  # MUST be excluded
        },
    ]
    cron_data_file.write_text(json.dumps(raw_tasks))

    out = await list_active_tasks_structured()
    assert isinstance(out, list)
    assert len(out) == 1  # Inactive is excluded
    t = out[0]
    # API-shape keys (matches spec §4.4)
    assert t["task_id"] == "abc12345"
    assert t["prompt"] == "Daily standup summary"
    assert t["schedule_type"] == "cron"
    assert t["schedule_value"] == "0 9 * * *"
    assert t["model_tier"] == "standard"
    assert t["created_at"] == "2026-04-20T11:23:00+00:00"
    assert "next_run" in t  # ISO-8601 string or null


@pytest.mark.asyncio
async def test_list_active_tasks_structured_empty(cron_data_file):
    from src.tools.cron import list_active_tasks_structured
    out = await list_active_tasks_structured()
    assert out == []


@pytest.mark.asyncio
async def test_list_active_tasks_structured_handles_missing_optional_fields(cron_data_file):
    """A task without model_tier or last_run must still serialize cleanly."""
    from src.tools.cron import list_active_tasks_structured

    raw = [{"id": "x1", "prompt": "p", "type": "once", "value": "2099-01-01T00:00:00",
            "channel": None, "chat_id": None, "created_at": "2026-04-20T00:00:00+00:00",
            "last_run": None, "active": True}]
    cron_data_file.write_text(json.dumps(raw))

    out = await list_active_tasks_structured()
    assert len(out) == 1
    assert out[0]["model_tier"] is None
    assert out[0]["task_id"] == "x1"
    assert out[0]["next_run"] is not None  # 'once' → use the value as next_run


@pytest.mark.asyncio
async def test_list_tasks_tool_still_returns_string(cron_data_file):
    """The existing @tool contract must keep working — it just consumes the structured data."""
    from src.tools.cron import list_tasks

    raw = [{"id": "abc12345", "prompt": "p", "type": "cron", "value": "* * * * *",
            "channel": None, "chat_id": None, "created_at": "2026-04-20T00:00:00+00:00",
            "last_run": None, "active": True}]
    cron_data_file.write_text(json.dumps(raw))

    result = await list_tasks.ainvoke({})
    assert isinstance(result, str)
    assert "abc12345" in result
