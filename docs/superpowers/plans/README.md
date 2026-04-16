# LangAgent Platform — Implementation Plans

Plans are written just-in-time per phase. Each plan depends on the previous phase being complete.

## Plan Index

| Plan | Phase | Status | Scope | Depends On |
|------|-------|--------|-------|------------|
| [Phase 0](2026-04-15-phase0-fork-foundation.md) | Fork & Foundation | **DONE** | Fork ciana-parrot, rebrand, verify, CLI + API channels | — |
| [Phase 1A](2026-04-15-phase1a-core-agent-rewrite.md) | Core Agent Rewrite | **READY** | Replace DeepAgents → explicit StateGraph, AgentState, streaming, permissions, context compression | Phase 0 |
| Phase 1B | Memory & Observability | PENDING | Dream memory, consolidation, multi-user USER.md, cost tracking, management API | Phase 1A |
| Phase 1C | Sub-Agent System | PENDING | Orchestration tools, BaseStore communication, health monitoring, recovery chain | Phase 1A |
| Phase 2A | Swarm & Harness | PENDING | Team templates, phase gates, git worktree, conflict detection, failure recovery | Phase 1C |
| Phase 2B | Channels & Web UI | PENDING | Discord, Slack, WebSocket channels + Web UI dashboard | Phase 1B |
| Phase 3 | Polish & Scale | PENDING | Additional channels, marketplace, LSP, natural language scheduling, Docker sandbox | Phase 2A + 2B |

## Execution Order

```
Phase 0 ──→ Phase 1A ──→ Phase 1B ──→ Phase 2B
                │                        │
                └──→ Phase 1C ──→ Phase 2A
                                         │
                              Phase 2A + 2B ──→ Phase 3
```

Phase 1B and 1C can run in parallel after 1A completes.
Phase 2A and 2B can run in parallel.
Phase 3 requires both 2A and 2B.

## Writing New Plans

Each plan is written when the previous phase is complete, because:
1. Exact file paths depend on how the previous phase restructured the code
2. Class names and interfaces may change during implementation
3. Test patterns established in earlier phases inform later plans

Use the `superpowers:writing-plans` skill to create each plan.
