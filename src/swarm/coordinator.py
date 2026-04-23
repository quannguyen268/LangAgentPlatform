"""Swarm — team-level launch + harness orchestration."""
from __future__ import annotations

import logging
import uuid

from ..subagent.broadcaster import EventBroadcaster
from ..subagent.registry import SubAgentRegistry
from ..subagent.state import AgentInfo
from .harness import HarnessRunner
from .phases import PhaseGate
from .templates import TeamTemplate

logger = logging.getLogger(__name__)


class Swarm:
    """Launch a team from a TeamTemplate, wire its harness, track its state."""

    def __init__(
        self,
        registry: SubAgentRegistry,
        broadcaster: EventBroadcaster,
        spawner,
        workspace: str,
    ):
        self._registry = registry
        self._broadcaster = broadcaster
        self._spawner = spawner
        self._workspace = workspace
        self._teams: dict[str, HarnessRunner] = {}

    async def launch(
        self,
        template: TeamTemplate,
        goal_override: str | None = None,
        gates: dict[str, PhaseGate] | None = None,
    ) -> str:
        """Spawn every agent in the template. Returns a team_id."""
        team_id = f"team-{uuid.uuid4().hex[:8]}"
        goal = goal_override or template.goal

        for agent_tpl in template.agents:
            agent_id = f"agent-{uuid.uuid4().hex[:8]}"
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
            logger.info("Launched team member %s (agent_id=%s, role=%s)",
                        agent_tpl.name, agent_id, agent_tpl.role)

        # Register a harness for this team (callers manage advancement)
        self._teams[team_id] = HarnessRunner(
            phases=template.phases,
            gates=gates or {},
        )
        logger.info("Team %s launched with %d agents across %d phases",
                    team_id, len(template.agents), len(template.phases))
        return team_id

    def get_harness(self, team_id: str) -> HarnessRunner | None:
        return self._teams.get(team_id)
