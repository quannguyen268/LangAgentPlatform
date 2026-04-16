"""Context compression — micro-compact and reactive compaction.

Two stages:
1. Micro-compact: summarize old tool results, keep recent turns
2. Reactive: triggered by prompt-too-long errors, more aggressive

Token estimation uses character heuristic (4 chars ≈ 1 token).
"""
from __future__ import annotations

import logging
from langchain_core.messages import (
    BaseMessage, HumanMessage, AIMessage, SystemMessage, ToolMessage,
)

logger = logging.getLogger(__name__)

# Constants
_CHARS_PER_TOKEN = 4
_MAX_COMPACT_FAILURES = 3


def estimate_tokens(messages: list[BaseMessage]) -> int:
    """Fast token estimation using character count heuristic.

    ~4 chars per token for English. Accurate to ~10%.
    Adds 20 chars overhead per message for role/metadata.
    """
    total = 0
    for m in messages:
        if isinstance(m.content, str):
            total += len(m.content)
        elif isinstance(m.content, list):
            # Multimodal: sum text blocks, estimate image tokens
            for block in m.content:
                if isinstance(block, dict) and block.get("type") == "text":
                    total += len(block.get("text", ""))
                elif isinstance(block, dict) and block.get("type") == "image_url":
                    total += 1000 * _CHARS_PER_TOKEN  # ~1000 tokens per image
        # Add overhead for role, metadata (~20 chars per message)
        total += 20
    return total // _CHARS_PER_TOKEN


def should_compact(
    messages: list[BaseMessage],
    max_tokens: int = 128000,
    threshold: float = 0.8,
) -> bool:
    """Check if messages exceed the compaction threshold.

    Returns True if estimated tokens > max_tokens * threshold.
    """
    current = estimate_tokens(messages)
    limit = int(max_tokens * threshold)
    return current > limit


def micro_compact(
    messages: list[BaseMessage],
    preserve_recent: int = 10,
) -> list[BaseMessage]:
    """Micro-compact: summarize old messages, preserve recent turns.

    Strategy:
    1. Keep all system messages at the start
    2. Walk backwards counting HumanMessages to find split point
    3. Old ToolMessages with content > 200 chars get truncated to
       first 100 chars + "... [truncated]"
    4. Replace all old messages with a single summary AIMessage:
       "[Context compacted: X older messages summarized, Y recent messages preserved]"
    5. If fewer turns than preserve_recent, return as-is
    6. Empty input returns empty list
    """
    if not messages:
        return []

    # Count HumanMessage turns to decide if compaction is needed
    turn_count = sum(1 for m in messages if isinstance(m, HumanMessage))
    if turn_count <= preserve_recent:
        return list(messages)

    # Split out system messages (kept at start, not compacted)
    system_msgs: list[BaseMessage] = []
    other_msgs: list[BaseMessage] = []
    for m in messages:
        if isinstance(m, SystemMessage):
            system_msgs.append(m)
        else:
            other_msgs.append(m)

    # Walk backwards through other_msgs counting HumanMessages to find split point
    recent_start = len(other_msgs)
    turns_found = 0
    for i in range(len(other_msgs) - 1, -1, -1):
        if isinstance(other_msgs[i], HumanMessage):
            turns_found += 1
            if turns_found >= preserve_recent:
                recent_start = i
                break

    old_msgs = other_msgs[:recent_start]
    recent_msgs = other_msgs[recent_start:]

    # Truncate verbose ToolMessage content in old messages
    compacted_old: list[BaseMessage] = []
    for m in old_msgs:
        if isinstance(m, ToolMessage):
            content = m.content if isinstance(m.content, str) else str(m.content)
            if len(content) > 200:
                truncated = content[:100] + "... [truncated]"
                compacted_old.append(ToolMessage(
                    content=truncated,
                    tool_call_id=m.tool_call_id,
                    name=getattr(m, "name", ""),
                ))
            else:
                compacted_old.append(m)
        else:
            compacted_old.append(m)

    # Replace all old messages with a single summary AIMessage
    if compacted_old:
        summary_text = (
            f"[Context compacted: {len(old_msgs)} older messages summarized, "
            f"{len(recent_msgs)} recent messages preserved]"
        )
        compacted_old = [AIMessage(content=summary_text)]

    return system_msgs + compacted_old + recent_msgs
