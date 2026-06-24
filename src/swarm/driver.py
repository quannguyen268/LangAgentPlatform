"""SwarmDriver — autonomously advances launched teams through their phases.

A single background loop ticks every team in the Swarm. For each unfinished team
it builds a team-scoped HarnessContext and calls ``HarnessRunner.try_advance``;
when a phase's gate passes it advances and activates the next phase's agents via
``Swarm.activate_phase``. A team is reported ``complete`` exactly once when its
harness finishes. Per-team errors are caught and logged so one wedged team cannot
stall the others.
"""
from __future__ import annotations

import logging
from typing import Any

from ..subagent.broadcaster import EventBroadcaster
from ..subagent.registry import SubAgentRegistry
from .phases import HarnessContext

logger = logging.getLogger(__name__)


class SwarmDriver:
    """Drives autonomous phase advancement across all teams in a Swarm."""

    def __init__(
        self,
        swarm: Any,
        registry: SubAgentRegistry,
        broadcaster: EventBroadcaster,
        workspace: str,
    ):
        self._swarm = swarm
        self._registry = registry
        self._broadcaster = broadcaster
        self._workspace = workspace
        self._completed: set[str] = set()

    async def tick(self) -> None:
        """Advance every team one step where its current phase's gate allows."""
        for team_id, runner in list(self._swarm.iter_teams()):
            try:
                await self._tick_team(team_id, runner)
            except Exception as e:
                logger.error("SwarmDriver: team %s tick failed: %s", team_id, e)

    async def _tick_team(self, team_id: str, runner) -> None:
        if runner.is_finished:
            self._mark_complete(team_id)
            return

        ctx = HarnessContext(
            workspace=self._workspace,
            registry=self._registry,
            approvals=self._swarm.get_approvals(team_id),
            agent_ids=set(self._swarm.get_team_agents(team_id)),
        )
        advanced = await runner.try_advance(ctx)
        if not advanced:
            return

        if runner.is_finished:
            self._mark_complete(team_id)
            return

        new_phase = runner.current_phase
        await self._swarm.activate_phase(team_id, new_phase)
        self._broadcaster.team_phase(team_id, phase=new_phase, status="active")

    def _mark_complete(self, team_id: str) -> None:
        if team_id not in self._completed:
            self._completed.add(team_id)
            self._broadcaster.team_phase(team_id, phase="", status="complete")
            logger.info("Team %s finished all phases", team_id)
