"""Test CostTracker."""
import pytest


def test_cost_tracker_imports():
    from src.observability.cost import CostTracker
    assert CostTracker is not None


def test_default_pricing():
    from src.observability.cost import CostTracker
    tracker = CostTracker()
    assert tracker.get_price("anthropic", "claude-sonnet-4-6") is not None


def test_record_usage():
    from src.observability.cost import CostTracker
    tracker = CostTracker()
    tracker.record(provider="anthropic", model="claude-sonnet-4-6", prompt_tokens=1000, completion_tokens=500, user_id="user1", tier="standard")
    summary = tracker.summary()
    assert summary["total_tokens"] > 0
    assert summary["total_cost_cents"] > 0


def test_per_user_tracking():
    from src.observability.cost import CostTracker
    tracker = CostTracker()
    tracker.record(provider="anthropic", model="claude-sonnet-4-6", prompt_tokens=1000, completion_tokens=500, user_id="alice", tier="standard")
    tracker.record(provider="anthropic", model="claude-sonnet-4-6", prompt_tokens=2000, completion_tokens=1000, user_id="bob", tier="standard")
    by_user = tracker.by_user()
    assert "alice" in by_user
    assert "bob" in by_user
    assert by_user["bob"]["total_tokens"] > by_user["alice"]["total_tokens"]


def test_per_tier_tracking():
    from src.observability.cost import CostTracker
    tracker = CostTracker()
    tracker.record(provider="anthropic", model="claude-sonnet-4-6", prompt_tokens=1000, completion_tokens=500, user_id="u1", tier="standard")
    tracker.record(provider="groq", model="llama-3.3-70b-versatile", prompt_tokens=5000, completion_tokens=2000, user_id="u1", tier="lite")
    by_tier = tracker.by_tier()
    assert "standard" in by_tier
    assert "lite" in by_tier


def test_budget_check():
    from src.observability.cost import CostTracker
    tracker = CostTracker()
    tracker.record(provider="anthropic", model="claude-sonnet-4-6", prompt_tokens=100000, completion_tokens=50000, user_id="u1", tier="standard")
    assert tracker.is_over_budget("u1", budget_cents=1.0)
    assert not tracker.is_over_budget("u1", budget_cents=99999.0)
