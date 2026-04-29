"""Swarm — team-level launch + harness orchestration.

``Swarm.launch`` takes a validated ``TeamTemplate``, spawns each declared
agent via a ``Spawner``, registers the agent + task in the ``SubAgentRegistry``,
and registers a ``HarnessRunner`` for the team. Callers drive phase
advancement explicitly; ``Swarm`` does not advance phases itself in Phase 2A.

Launch is transactional: if any ``spawner.spawn`` call raises mid-loop,
the agents already registered for this team are cancelled and deregistered
before the exception propagates. The caller never sees a half-launched team.

``workspace`` and ``broadcaster`` are held on the instance for upcoming
wiring (broadcaster → lifecycle events, workspace → HarnessContext) and
are not yet read by Swarm itself.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Optional, Protocol

from ..subagent.broadcaster import EventBroadcaster
from ..subagent.registry import SubAgentRegistry
from ..subagent.state import AgentInfo
from .harness import HarnessRunner
from .phases import PhaseGate
from .templates import TeamTemplate

logger = logging.getLogger(__name__)


class Spawner(Protocol):
    """Minimal spawner contract — matches DeepAgentsSpawner."""

    async def spawn(
        self, info: AgentInfo, recovery_context: Optional[str] = None
    ) -> asyncio.Task: ...


class Swarm:
    """Launch a team from a TeamTemplate and track its harness."""

    def __init__(
        self,
        registry: SubAgentRegistry,
        broadcaster: EventBroadcaster,
        spawner: Spawner,
        workspace: str,
    ):
        self._registry = registry
        self._broadcaster = broadcaster  # T13: lifecycle event emission
        self._spawner = spawner
        self._workspace = workspace  # T13: fed into HarnessContext at run time
        self._teams: dict[str, HarnessRunner] = {}
        self._team_agents: dict[str, list[str]] = {}

    def _new_team_id(self) -> str:
        while True:
            team_id = f"team-{uuid.uuid4().hex[:8]}"
            if team_id not in self._teams:
                return team_id

    def _new_agent_id(self) -> str:
        while True:
            agent_id = f"agent-{uuid.uuid4().hex[:8]}"
            if self._registry.get_agent(agent_id) is None:
                return agent_id

    async def launch(
        self,
        template: TeamTemplate,
        goal_override: str | None = None,
        gates: dict[str, PhaseGate] | None = None,
    ) -> str:
        """Spawn every agent in the template. Returns a team_id.

        Raises:
            ValueError: if ``gates`` keys are not a subset of ``template.phases``
                (checked up-front — no agents are spawned on a failed validation).
            Exception: propagates any exception from ``spawner.spawn``; all
                agents already spawned for this team are rolled back
                (cancelled + deregistered) before re-raising.
        """
        # Fail-fast validation before any spawn, so an invalid gate set does
        # not leave partially-launched agents behind.
        gates = gates or {}
        unknown_gates = set(gates.keys()) - set(template.phases)
        if unknown_gates:
            raise ValueError(
                f"Swarm.launch: gates reference unknown phases: {sorted(unknown_gates)}"
            )

        team_id = self._new_team_id()
        goal = goal_override or template.goal
        spawned_ids: list[str] = []

        try:
            for agent_tpl in template.agents:
                agent_id = self._new_agent_id()
                info = AgentInfo(
                    agent_id=agent_id,
                    name=agent_tpl.name,
                    role=agent_tpl.role,
                    task=f"Team goal: {goal}\n\n{agent_tpl.task_prompt}",
                    tier=agent_tpl.tier,
                    tools=list(agent_tpl.tools),
                    skills=list(agent_tpl.skills),
                )
                task = await self._spawner.spawn(info)
                self._registry.register(info, task)
                spawned_ids.append(agent_id)
                logger.info(
                    "Launched team member %s (agent_id=%s, role=%s)",
                    agent_tpl.name, agent_id, agent_tpl.role,
                )
        except Exception:
            logger.exception(
                "Team %s launch failed after %d/%d agents; rolling back",
                team_id, len(spawned_ids), len(template.agents),
            )
            await self._rollback(spawned_ids)
            raise

        # Invariant: ``team_id`` is present in ``_teams`` iff present in
        # ``_team_agents``. These two writes must stay paired with no awaits
        # between them so the API view (`GET /v1/teams`) cannot observe a
        # team without its agent ids.
        self._teams[team_id] = HarnessRunner(
            phases=template.phases, gates=gates,
        )
        self._team_agents[team_id] = list(spawned_ids)
        logger.info(
            "Team %s launched with %d agents across %d phases",
            team_id, len(template.agents), len(template.phases),
        )
        return team_id

    async def _rollback(self, spawned_ids: list[str]) -> None:
        """Cancel + deregister every agent registered so far for a failed launch."""
        for aid in spawned_ids:
            try:
                await self._registry.deregister(aid)
            except Exception as e:
                logger.error(
                    "Rollback: deregister %s failed: %s", aid, e,
                )

    def get_harness(self, team_id: str) -> HarnessRunner | None:
        return self._teams.get(team_id)

    def get_team_agents(self, team_id: str) -> list[str]:
        """Return the agent_ids launched for a given team_id, or [] if unknown."""
        return list(self._team_agents.get(team_id, []))
