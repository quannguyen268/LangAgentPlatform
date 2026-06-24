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
from .phases import AllTasksCompleteGate, PhaseGate
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
        self._team_templates: dict[str, TeamTemplate] = {}
        self._team_goals: dict[str, str] = {}
        self._team_approvals: dict[str, set[str]] = {}

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

    async def _spawn_one(self, team_id: str, agent_tpl, goal: str) -> str:
        """Spawn + register one agent for a team. Returns the agent_id."""
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
        self._team_agents[team_id].append(agent_id)
        logger.info(
            "Spawned team member %s (agent_id=%s, role=%s, phase=%s)",
            agent_tpl.name, agent_id, agent_tpl.role, agent_tpl.phase,
        )
        return agent_id

    async def launch(
        self,
        template: TeamTemplate,
        goal_override: str | None = None,
        gates: dict[str, PhaseGate] | None = None,
    ) -> str:
        """Spawn the initial agents for the template. Returns a team_id.

        For phased templates (``template.is_phased``), only the first phase's
        agents are spawned immediately; remaining phases are activated later via
        ``activate_phase``. Phased phases with agents but no explicit gate
        default to ``AllTasksCompleteGate``.

        For legacy (non-phased) templates, all agents are spawned at once,
        preserving the previous behavior.

        Raises:
            ValueError: if ``gates`` keys are not a subset of ``template.phases``
                (checked up-front — no agents are spawned on a failed validation).
            Exception: propagates any exception from ``spawner.spawn``; all
                agents already spawned for this team are rolled back
                (cancelled + deregistered) before re-raising.
        """
        # Fail-fast validation before any spawn, so an invalid gate set does
        # not leave partially-launched agents behind.
        gates = dict(gates or {})
        unknown_gates = set(gates) - set(template.phases)
        if unknown_gates:
            raise ValueError(
                f"Swarm.launch: gates reference unknown phases: {sorted(unknown_gates)}"
            )

        # For phased templates, default-gate every phase that has agents.
        if template.is_phased:
            for ph in template.phases:
                if ph not in gates and template.agents_for_phase(ph):
                    gates[ph] = AllTasksCompleteGate()

        team_id = self._new_team_id()
        goal = goal_override or template.goal
        self._team_agents[team_id] = []
        self._team_templates[team_id] = template
        self._team_goals[team_id] = goal
        self._team_approvals[team_id] = set()

        try:
            if template.is_phased:
                for agent_tpl in template.agents_for_phase(template.phases[0]):
                    await self._spawn_one(team_id, agent_tpl, goal)
            else:
                for agent_tpl in template.agents:
                    await self._spawn_one(team_id, agent_tpl, goal)
        except Exception:
            logger.exception("Team %s launch failed; rolling back", team_id)
            await self._rollback(self._team_agents.get(team_id, []))
            self._team_agents.pop(team_id, None)
            self._team_templates.pop(team_id, None)
            self._team_goals.pop(team_id, None)
            self._team_approvals.pop(team_id, None)
            raise

        # Invariant: ``team_id`` is present in ``_teams`` iff present in
        # ``_team_agents``. These two writes must stay paired with no awaits
        # between them so the API view (`GET /v1/teams`) cannot observe a
        # team without its agent ids.
        self._teams[team_id] = HarnessRunner(phases=template.phases, gates=gates)
        logger.info(
            "Team %s launched (%s mode) with %d agent(s); phases=%s",
            team_id, "phased" if template.is_phased else "legacy",
            len(self._team_agents[team_id]), template.phases,
        )
        return team_id

    async def activate_phase(self, team_id: str, phase: str) -> list[str]:
        """Spawn the agents declared for ``phase``. Returns their agent_ids.

        Returns [] for an unknown team or a phase with no declared agents.
        """
        template = self._team_templates.get(team_id)
        if template is None:
            return []
        goal = self._team_goals.get(team_id, template.goal)
        new_ids: list[str] = []
        for agent_tpl in template.agents_for_phase(phase):
            new_ids.append(await self._spawn_one(team_id, agent_tpl, goal))
        if new_ids:
            logger.info(
                "Team %s activated phase %s with %d agent(s)",
                team_id, phase, len(new_ids),
            )
        return new_ids

    def get_approvals(self, team_id: str) -> set[str]:
        """The mutable approvals set for a team (consumed by HumanApprovalGate)."""
        return self._team_approvals.setdefault(team_id, set())

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

    def iter_teams(self):
        """Iterate over ``(team_id, HarnessRunner)`` pairs.

        Iteration order is dict-insertion (Python 3.7+) but should not be
        relied on as part of the public contract — sort downstream if a
        stable ordering is required.
        """
        return iter(self._teams.items())
