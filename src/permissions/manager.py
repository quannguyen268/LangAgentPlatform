"""PermissionManager — multi-mode tool permission enforcement."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


class PermissionMode:
    DEFAULT = "default"
    AUTO = "auto"
    PLAN = "plan"


READ_ONLY_TOOLS = frozenset({
    "read_file", "glob", "grep", "web_search", "web_fetch",
    "list_tasks", "monitor_agents", "review_cost", "switch_model",
})

WRITE_TOOLS = frozenset({
    "write_file", "edit_file", "exec", "host_execute",
    "schedule_task", "cancel_task", "notebook_edit",
    "spawn_agent", "recall_agent", "create_team", "dissolve_team",
})

SENSITIVE_PATHS = [
    ".ssh/", ".gnupg/", ".aws/", ".gcp/", ".azure/",
    ".docker/config.json", ".kube/config",
    "id_rsa", "id_ed25519", "credentials.json",
    ".env", ".netrc", "token", "secret",
]


@dataclass
class PermissionResult:
    action: str   # "allow" | "deny" | "ask"
    reason: str = ""


class PermissionManager:
    """Check tool permissions based on mode and rules."""

    def __init__(self, mode: str = PermissionMode.DEFAULT):
        self.mode = mode

    def check(self, tool_name: str, args: dict[str, Any]) -> PermissionResult:
        """Check if a tool call is allowed.

        Returns:
            PermissionResult with action: "allow", "deny", or "ask"
        """
        # Sensitive path check (always, regardless of mode)
        path = args.get("path", "") or args.get("file", "") or ""
        if path and self._is_sensitive_path(path):
            return PermissionResult(
                action="deny",
                reason=f"Sensitive path detected: {path}",
            )

        # Mode-based checks
        if self.mode == PermissionMode.AUTO:
            return PermissionResult(action="allow")

        if self.mode == PermissionMode.PLAN:
            if tool_name in READ_ONLY_TOOLS:
                return PermissionResult(action="allow")
            return PermissionResult(
                action="deny",
                reason=f"Plan mode: {tool_name} is not a read-only tool",
            )

        # Default mode: read tools allowed, write tools ask
        if tool_name in READ_ONLY_TOOLS:
            return PermissionResult(action="allow")
        if tool_name in WRITE_TOOLS:
            return PermissionResult(
                action="ask",
                reason=f"{tool_name} requires approval",
            )
        # Unknown tools: ask
        return PermissionResult(action="ask", reason=f"Unknown tool: {tool_name}")

    def _is_sensitive_path(self, path: str) -> bool:
        """Check if path matches any sensitive patterns."""
        path_lower = path.lower()
        return any(pattern in path_lower for pattern in SENSITIVE_PATHS)
