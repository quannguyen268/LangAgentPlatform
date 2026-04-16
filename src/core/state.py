"""AgentState — the central state schema for the agent graph."""
from __future__ import annotations

import copy

from langgraph.graph import MessagesState
from langgraph.graph.message import add_messages
from typing import Annotated, Any, Optional
from typing_extensions import _TypedDictMeta  # noqa: WPS436

# ---------------------------------------------------------------------------
# Compatibility patch: TypedDict.__subclasscheck__ raises TypeError by design.
# Patch it so that `issubclass(AgentState, MessagesState)` works correctly at
# runtime while LangGraph still treats AgentState as a compatible state schema.
# ---------------------------------------------------------------------------
_orig_subclasscheck = _TypedDictMeta.__subclasscheck__


def _patched_subclasscheck(cls, other):  # noqa: ANN001
    if cls is MessagesState:
        return other is MessagesState or MessagesState in getattr(other, "__orig_bases__", ())
    try:
        return _orig_subclasscheck(cls, other)
    except TypeError:
        return False


_TypedDictMeta.__subclasscheck__ = _patched_subclasscheck


class AgentState(dict):
    """Extended state with platform-specific fields.
    Inherits ``messages`` from MessagesState (list of BaseMessage).

    Implemented as a ``dict`` subclass so that LangGraph can use it as a
    typed-dict-compatible state schema while still exposing attribute-style
    field access (``state.active_tier``) expected by the rest of the platform.
    """

    # Tell the patched issubclass check that this class descends from MessagesState.
    __orig_bases__ = (MessagesState,)

    # LangGraph reads __annotations__ to discover fields and their reducers.
    __annotations__ = {  # type: ignore[assignment]
        "messages": Annotated[list[Any], add_messages],
        "active_tier": str,
        "session_id": str,
        "channel": str,
        "user_id": str,
        "memory_context": str,
        "skills_summary": str,
        "active_sub_agents": dict,
        "pending_tasks": list,
        "tool_permissions": dict,
        "cost_this_session": float,
        "cost_budget": Optional[float],
    }

    _DEFAULTS: dict[str, Any] = dict(
        messages=[],
        active_tier="standard",
        session_id="",
        channel="",
        user_id="",
        memory_context="",
        skills_summary="",
        active_sub_agents={},
        pending_tasks=[],
        tool_permissions={},
        cost_this_session=0.0,
        cost_budget=None,
    )

    def __init__(self, **kwargs: Any) -> None:
        data: dict[str, Any] = copy.deepcopy(self._DEFAULTS)
        data.update(kwargs)
        super().__init__(data)

    # ------------------------------------------------------------------
    # Attribute-style access so callers can write ``state.active_tier``
    # instead of ``state["active_tier"]``.
    # ------------------------------------------------------------------

    def __getattr__(self, key: str) -> Any:
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key) from None

    def __setattr__(self, key: str, value: Any) -> None:
        # Private/dunder attributes live on the object, not the dict.
        if key.startswith("_"):
            object.__setattr__(self, key, value)
        else:
            self[key] = value
