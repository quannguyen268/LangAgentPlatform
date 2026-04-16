"""Test context compression — micro-compact and reactive compaction."""
import pytest
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage


def test_compaction_imports():
    from src.core.compaction import estimate_tokens, micro_compact, should_compact


def test_estimate_tokens():
    from src.core.compaction import estimate_tokens
    from langchain_core.messages import HumanMessage
    messages = [HumanMessage(content="Hello " * 100)]  # ~600 chars
    tokens = estimate_tokens(messages)
    assert 100 < tokens < 200  # ~150 tokens at 4 chars/token


def test_should_compact_below_threshold():
    from src.core.compaction import should_compact
    from langchain_core.messages import HumanMessage
    messages = [HumanMessage(content="Hello")]
    assert should_compact(messages, max_tokens=128000, threshold=0.8) == False


def test_should_compact_above_threshold():
    from src.core.compaction import should_compact
    from langchain_core.messages import HumanMessage
    # Create messages that exceed 80% of a tiny context window
    messages = [HumanMessage(content="x" * 4000)]  # ~1000 tokens
    assert should_compact(messages, max_tokens=1000, threshold=0.8) == True


def test_micro_compact_preserves_recent():
    from src.core.compaction import micro_compact
    messages = []
    for i in range(20):
        messages.append(HumanMessage(content=f"User message {i}"))
        messages.append(AIMessage(content=f"Assistant response {i} " + "padding " * 50))

    result = micro_compact(messages, preserve_recent=5)
    # Should have fewer messages than original
    assert len(result) < len(messages)
    # Last 5 turns (10 messages) should be preserved
    assert result[-1].content == messages[-1].content


def test_micro_compact_empty_messages():
    from src.core.compaction import micro_compact
    result = micro_compact([], preserve_recent=5)
    assert result == []


def test_micro_compact_few_messages():
    """If messages fewer than preserve_recent, return as-is."""
    from src.core.compaction import micro_compact
    messages = [HumanMessage(content="Hello"), AIMessage(content="Hi")]
    result = micro_compact(messages, preserve_recent=5)
    assert len(result) == 2
