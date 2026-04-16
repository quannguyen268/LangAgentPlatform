"""Cost tracking for per-tier, per-user, per-agent LLM usage."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional


# (input_per_1M_cents, output_per_1M_cents)
DEFAULT_PRICING: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-6": (300, 1500),
    "claude-opus-4-6": (1500, 7500),
    "claude-haiku-4-5": (80, 400),
    "gpt-4o": (250, 1000),
    "gpt-4o-mini": (15, 60),
    "llama-3.3-70b-versatile": (59, 79),
    "gemini-2.5-flash": (15, 60),
    "gemini-2.5-pro": (125, 500),
}


@dataclass
class _Bucket:
    total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_cost_cents: float = 0.0
    calls: int = 0

    def add(self, prompt: int, completion: int, cost: float) -> None:
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        self.total_tokens += prompt + completion
        self.total_cost_cents += cost
        self.calls += 1

    def as_dict(self) -> dict:
        return {
            "total_tokens": self.total_tokens,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_cost_cents": self.total_cost_cents,
            "calls": self.calls,
        }


class CostTracker:
    """Track LLM call costs across dimensions: user, tier, agent."""

    def __init__(self, pricing: Optional[dict[str, tuple[float, float]]] = None) -> None:
        self._pricing: dict[str, tuple[float, float]] = pricing or dict(DEFAULT_PRICING)
        self._global = _Bucket()
        self._by_user: dict[str, _Bucket] = defaultdict(_Bucket)
        self._by_tier: dict[str, _Bucket] = defaultdict(_Bucket)
        self._by_agent: dict[str, _Bucket] = defaultdict(_Bucket)

    # ------------------------------------------------------------------
    # Pricing helpers
    # ------------------------------------------------------------------

    def get_price(self, provider: str, model: str) -> Optional[tuple[float, float]]:
        """Return (input_per_1M_cents, output_per_1M_cents) or None if unknown."""
        return self._pricing.get(model)

    def _compute_cost(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        pricing = self._pricing.get(model)
        if pricing is None:
            return 0.0
        input_rate, output_rate = pricing
        return (prompt_tokens * input_rate + completion_tokens * output_rate) / 1_000_000

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record(
        self,
        provider: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        user_id: str,
        tier: str,
        agent_id: Optional[str] = None,
    ) -> float:
        """Record a single LLM call and return its cost in cents."""
        cost = self._compute_cost(model, prompt_tokens, completion_tokens)

        self._global.add(prompt_tokens, completion_tokens, cost)
        self._by_user[user_id].add(prompt_tokens, completion_tokens, cost)
        self._by_tier[tier].add(prompt_tokens, completion_tokens, cost)

        effective_agent = agent_id or "unknown"
        self._by_agent[effective_agent].add(prompt_tokens, completion_tokens, cost)

        return cost

    # ------------------------------------------------------------------
    # Summaries
    # ------------------------------------------------------------------

    def summary(self) -> dict:
        """Return aggregate stats across all calls."""
        return {
            "total_tokens": self._global.total_tokens,
            "prompt_tokens": self._global.prompt_tokens,
            "completion_tokens": self._global.completion_tokens,
            "total_cost_cents": self._global.total_cost_cents,
            "total_calls": self._global.calls,
        }

    def by_user(self) -> dict[str, dict]:
        """Return per-user stats."""
        return {uid: b.as_dict() for uid, b in self._by_user.items()}

    def by_tier(self) -> dict[str, dict]:
        """Return per-tier stats."""
        return {tier: b.as_dict() for tier, b in self._by_tier.items()}

    def by_agent(self) -> dict[str, dict]:
        """Return per-agent stats."""
        return {aid: b.as_dict() for aid, b in self._by_agent.items()}

    # ------------------------------------------------------------------
    # Per-user helpers
    # ------------------------------------------------------------------

    def user_cost(self, user_id: str) -> float:
        """Return total cost in cents for a given user (0.0 if unknown)."""
        bucket = self._by_user.get(user_id)
        return bucket.total_cost_cents if bucket else 0.0

    def is_over_budget(self, user_id: str, budget_cents: float) -> bool:
        """Return True if the user's total cost exceeds budget_cents."""
        return self.user_cost(user_id) > budget_cents
