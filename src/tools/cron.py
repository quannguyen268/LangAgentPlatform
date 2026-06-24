"""Scheduled task tools - create, list, cancel tasks."""

import asyncio
import json
import logging
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path

from langchain_core.tools import tool

from ..config import SchedulerConfig

logger = logging.getLogger(__name__)

PROMPT_PREVIEW_LEN = 60

# Module-level config, set by init_cron_tools()
_data_file: str = "./data/scheduled_tasks.json"

# Per-task context (propagated automatically by asyncio.create_task in Python 3.12+)
_current_channel: ContextVar[str | None] = ContextVar("_current_channel", default=None)
_current_chat_id: ContextVar[str | None] = ContextVar("_current_chat_id", default=None)

# Shared lock for read-modify-write on the tasks JSON file
_tasks_lock: asyncio.Lock | None = None


def get_tasks_lock() -> asyncio.Lock:
    """Return the shared lock for task file operations."""
    if _tasks_lock is None:
        raise RuntimeError("cron tools not initialized — call init_cron_tools() first")
    return _tasks_lock


def init_cron_tools(config: SchedulerConfig) -> None:
    """Initialize cron tools with config."""
    global _data_file, _tasks_lock
    _data_file = config.data_file
    _tasks_lock = asyncio.Lock()


def set_current_context(channel: str, chat_id: str) -> None:
    """Set the current channel/chat context for new tasks."""
    _current_channel.set(channel)
    _current_chat_id.set(chat_id)


def _load_tasks() -> list[dict]:
    path = Path(_data_file)
    if not path.exists():
        return []
    with open(path) as f:
        return json.load(f)


def _save_tasks(tasks: list[dict]) -> None:
    path = Path(_data_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(tasks, f, indent=2)


@tool
async def schedule_task(prompt: str, schedule_type: str, schedule_value: str, model_tier: str = "") -> str:
    """Schedule a task to run later or on a recurring basis.

    Args:
        prompt: What the agent should do when the task runs.
        schedule_type: One of 'cron' (cron expression), 'interval' (seconds), 'once' (ISO timestamp).
        schedule_value: The schedule value matching the type.
        model_tier: Optional model tier for execution (e.g. 'lite', 'advanced', 'expert'). Empty = default.
    """
    if schedule_type not in ("cron", "interval", "once"):
        return f"Invalid schedule_type: {schedule_type}. Use 'cron', 'interval', or 'once'."

    # Validate schedule_value based on type
    if schedule_type == "cron":
        try:
            from croniter import croniter
            croniter(schedule_value)
        except (ValueError, KeyError) as e:
            return f"Invalid cron expression '{schedule_value}': {e}"
    elif schedule_type == "interval":
        try:
            interval = int(schedule_value)
            if interval <= 0:
                return f"Invalid interval: must be a positive number of seconds, got '{schedule_value}'."
        except ValueError:
            return f"Invalid interval: '{schedule_value}' is not a valid integer."
    elif schedule_type == "once":
        try:
            datetime.fromisoformat(schedule_value)
        except ValueError:
            return f"Invalid ISO timestamp: '{schedule_value}'. Use format like '2025-01-15T10:00:00'."

    channel = _current_channel.get()
    chat_id = _current_chat_id.get()

    task = {
        "id": str(uuid.uuid4())[:8],
        "prompt": prompt,
        "type": schedule_type,
        "value": schedule_value,
        "channel": channel,
        "chat_id": chat_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "last_run": None,
        "active": True,
    }
    if model_tier:
        task["model_tier"] = model_tier

    async with get_tasks_lock():
        tasks = _load_tasks()
        tasks.append(task)
        _save_tasks(tasks)

    logger.info("Scheduled task %s: %s (%s: %s) -> %s/%s",
                task["id"], prompt[:PROMPT_PREVIEW_LEN], schedule_type, schedule_value,
                channel, chat_id)
    return f"Task scheduled: id={task['id']}, type={schedule_type}, value={schedule_value}"


def _to_utc_iso(dt: datetime) -> str:
    """Return ``dt`` as a UTC ISO-8601 string. Naive inputs are assumed to be UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _compute_next_run(task: dict) -> str | None:
    """Best-effort next-run ISO timestamp (always UTC).

    Returns ``None`` if the task has no future fire time:
      - "once" tasks already fired (``last_run`` is set)
      - "cron" / "interval" tasks whose schedule fails to parse
      - unknown schedule types
    """
    schedule_type = task.get("type")
    schedule_value = task.get("value", "")
    if schedule_type == "once":
        # A "once" task fires exactly once. Once last_run is recorded, there
        # is no further next_run — the task is conceptually finished.
        if task.get("last_run"):
            return None
        return schedule_value
    if schedule_type == "cron":
        try:
            from croniter import croniter
            base = datetime.now(timezone.utc)
            return _to_utc_iso(croniter(schedule_value, base).get_next(datetime))
        except Exception as e:
            logger.warning(
                "Failed to compute cron next_run for task %s: %s",
                task.get("id"), e,
            )
            return None
    if schedule_type == "interval":
        try:
            from datetime import timedelta
            secs = int(schedule_value)
            last_run_iso = task.get("last_run")
            if last_run_iso:
                base = datetime.fromisoformat(last_run_iso)
            else:
                base = datetime.fromisoformat(
                    task.get("created_at", datetime.now(timezone.utc).isoformat())
                )
            return _to_utc_iso(base + timedelta(seconds=secs))
        except Exception as e:
            logger.warning(
                "Failed to compute interval next_run for task %s: %s",
                task.get("id"), e,
            )
            return None
    return None


def _to_api_dict(task: dict) -> dict:
    """Project a stored task to the /v1/tasks response shape."""
    return {
        "task_id": task.get("id"),
        "prompt": task.get("prompt", ""),
        "schedule_type": task.get("type"),
        "schedule_value": task.get("value"),
        "model_tier": task.get("model_tier"),
        "next_run": _compute_next_run(task),
        "created_at": task.get("created_at"),
    }


async def list_active_tasks_structured() -> list[dict]:
    """Return all active scheduled tasks in the /v1/tasks response shape.

    Excludes inactive tasks (cancelled or completed). Used by both the
    Management API endpoint and the ``list_tasks`` @tool.
    """
    async with get_tasks_lock():
        tasks = _load_tasks()
    return [_to_api_dict(t) for t in tasks if t.get("active", True)]


@tool
async def list_tasks() -> str:
    """List all active scheduled tasks."""
    structured = await list_active_tasks_structured()
    if not structured:
        return "No active scheduled tasks."

    lines = []
    for t in structured:
        lines.append(
            f"- [{t['task_id']}] {t['schedule_type']}={t['schedule_value']} | "
            f"{t['prompt'][:PROMPT_PREVIEW_LEN]}"
            f" | next_run={t['next_run'] or 'unknown'}"
        )
    return "\n".join(lines)


@tool
async def cancel_task(task_id: str) -> str:
    """Cancel a scheduled task by its ID."""
    async with get_tasks_lock():
        tasks = _load_tasks()
        for t in tasks:
            if t["id"] == task_id:
                t["active"] = False
                _save_tasks(tasks)
                logger.info("Cancelled task %s", task_id)
                return f"Task {task_id} cancelled."
    return f"Task {task_id} not found."
