"""StreamEvent types and factory functions for the streaming lifecycle."""
from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import Any


class EventType:
    TOKEN = "token"
    THINKING = "thinking"
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_END = "tool_call_end"
    TOOL_ERROR = "tool_error"
    TIER_SWITCH = "tier_switch"
    AGENT_SPAWN = "agent_spawn"
    AGENT_PROGRESS = "agent_progress"
    AGENT_COMPLETE = "agent_complete"
    AGENT_FAILED = "agent_failed"
    APPROVAL_REQUEST = "approval_request"
    COST_UPDATE = "cost_update"
    ERROR = "error"
    DONE = "done"
    TEAM_PHASE = "team_phase"


@dataclass
class StreamEvent:
    type: str
    data: Any
    agent_id: str = "master"
    user_id: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {"type": self.type, "data": self.data, "agent_id": self.agent_id, "user_id": self.user_id, "timestamp": self.timestamp}


def token_event(delta: str, user_id: str = "", agent_id: str = "master") -> StreamEvent:
    return StreamEvent(type=EventType.TOKEN, data={"delta": delta}, agent_id=agent_id, user_id=user_id)

def thinking_event(content: str, user_id: str = "", agent_id: str = "master") -> StreamEvent:
    return StreamEvent(type=EventType.THINKING, data={"content": content}, agent_id=agent_id, user_id=user_id)

def tool_call_start_event(name: str, args: dict, user_id: str = "", agent_id: str = "master") -> StreamEvent:
    return StreamEvent(type=EventType.TOOL_CALL_START, data={"name": name, "args": args}, agent_id=agent_id, user_id=user_id)

def tool_call_end_event(name: str, result: str, user_id: str = "", agent_id: str = "master") -> StreamEvent:
    return StreamEvent(type=EventType.TOOL_CALL_END, data={"name": name, "result": result}, agent_id=agent_id, user_id=user_id)

def tool_error_event(name: str, error: str, user_id: str = "", agent_id: str = "master") -> StreamEvent:
    return StreamEvent(type=EventType.TOOL_ERROR, data={"name": name, "error": error}, agent_id=agent_id, user_id=user_id)

def tier_switch_event(from_tier: str, to_tier: str, user_id: str = "", agent_id: str = "master") -> StreamEvent:
    return StreamEvent(type=EventType.TIER_SWITCH, data={"from": from_tier, "to": to_tier}, agent_id=agent_id, user_id=user_id)

def approval_request_event(tool_name: str, args: dict, user_id: str = "", agent_id: str = "master") -> StreamEvent:
    return StreamEvent(type=EventType.APPROVAL_REQUEST, data={"tool": tool_name, "args": args}, agent_id=agent_id, user_id=user_id)

def cost_update_event(prompt_tokens: int, completion_tokens: int, cost_cents: float, tier: str = "standard", user_id: str = "", agent_id: str = "master") -> StreamEvent:
    return StreamEvent(type=EventType.COST_UPDATE, data={"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens, "cost_cents": cost_cents, "tier": tier}, agent_id=agent_id, user_id=user_id)

def error_event(message: str, user_id: str = "", agent_id: str = "master") -> StreamEvent:
    return StreamEvent(type=EventType.ERROR, data={"message": message}, agent_id=agent_id, user_id=user_id)

def done_event(user_id: str = "", agent_id: str = "master") -> StreamEvent:
    return StreamEvent(type=EventType.DONE, data={}, agent_id=agent_id, user_id=user_id)


def agent_spawn_event(
    agent_id: str, name: str, role: str, tier: str,
    user_id: str = "",
) -> StreamEvent:
    return StreamEvent(
        type=EventType.AGENT_SPAWN,
        data={"name": name, "role": role, "tier": tier},
        agent_id=agent_id,
        user_id=user_id,
    )


def agent_progress_event(
    agent_id: str, message: str, cost_cents: float = 0.0,
    user_id: str = "",
) -> StreamEvent:
    return StreamEvent(
        type=EventType.AGENT_PROGRESS,
        data={"message": message, "cost_cents": cost_cents},
        agent_id=agent_id,
        user_id=user_id,
    )


def agent_complete_event(
    agent_id: str, result: str, cost_total_cents: float = 0.0,
    user_id: str = "",
) -> StreamEvent:
    return StreamEvent(
        type=EventType.AGENT_COMPLETE,
        data={"result": result, "cost_total_cents": cost_total_cents},
        agent_id=agent_id,
        user_id=user_id,
    )


def agent_failed_event(
    agent_id: str, reason: str, action: str,
    user_id: str = "",
) -> StreamEvent:
    return StreamEvent(
        type=EventType.AGENT_FAILED,
        data={"reason": reason, "action": action},
        agent_id=agent_id,
        user_id=user_id,
    )


def team_phase_event(
    team_id: str, phase: str, status: str,
    user_id: str = "", agent_id: str = "master",
) -> StreamEvent:
    return StreamEvent(
        type=EventType.TEAM_PHASE,
        data={"team_id": team_id, "phase": phase, "status": status},
        agent_id=agent_id,
        user_id=user_id,
    )
