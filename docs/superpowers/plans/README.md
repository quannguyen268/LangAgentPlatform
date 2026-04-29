# LangAgent Platform — Implementation Plans

Plans are written just-in-time per phase. Each plan depends on the previous phase being complete.

## Architecture (AD-14)

The platform uses **DeepAgents' `create_deep_agent()`** with **LangChain middleware** as the primary agent construction pattern. This replaces the earlier approach of building a custom StateGraph.

**What DeepAgents provides:** graph, filesystem tools (read/write/edit/glob/grep/exec), skills, memory, subagent spawning, summarization, prompt caching, human-in-the-loop (interrupt_on).

**What we add via middleware:** ModelRetryMiddleware, ToolRetryMiddleware, ModelCallLimitMiddleware, ToolCallLimitMiddleware, SummarizationMiddleware, ContextEditingMiddleware.

**What we add via custom modules:** RoutingChatModel, CostTracker, StreamEvent, FileStateTracker, custom tools (web, cron, gateway, model router).

## Plan Index

| Plan | Phase | Status | Scope | Depends On |
|------|-------|--------|-------|------------|
| [Phase 0](2026-04-15-phase0-fork-foundation.md) | Fork & Foundation | **DONE** | Fork ciana-parrot, rebrand, verify, CLI + API channels | — |
| [Phase 1A](2026-04-15-phase1a-core-agent-rewrite.md) | Core Agent Rewrite | **DONE** (refactored to middleware) | Custom modules (CostTracker, StreamEvent, FileStateTracker, PermissionManager) + middleware refactor | Phase 0 |
| [Phase 1B](2026-04-16-phase1b-memory-api-websocket.md) | Memory & Observability | **DONE** (v0.2.0-phase1b) | Dream memory (2-stage + Git), management API (/v1/agents, /v1/memory, /v1/cost), WebSocket events | Phase 1A |
| [Phase 1C](2026-04-16-phase1c-subagent-system.md) | Sub-Agent System | **DONE** (v0.3.0-phase1c) | SubAgentMiddleware config, orchestration tools, BaseStore communication, health monitoring | Phase 1A |
| [Phase 2A](2026-04-16-phase2a-swarm-harness.md) | Swarm & Harness | **DONE** (v0.4.0-phase2a) | Team templates, phase gates, git worktree, conflict detection, failure recovery | Phase 1C |
| [Phase 2B-I](2026-04-29-phase2b-i-management-api.md) | Management API (read-only) | **DONE** (v0.5.0-phase2b-i) | /v1/agents, /v1/teams, /v1/tasks, /v1/config + Swarm wired into create_agent | Phase 2A |
| Phase 2B-II | Web UI v1 | PENDING | Chat panel + Swarm dashboard + Settings (consumes 2B-I API) | Phase 2B-I |
| Phase 2B-III | Discord & Slack channels | PENDING | New chat-channel adapters | Phase 2A |
| Phase 3 | Polish & Scale | PENDING | Marketplace, LSP, natural language scheduling, Docker sandbox | Phase 2B-II + 2B-III |

## What Changed with AD-14 (Middleware Refactor)

The middleware adoption significantly simplifies several phases:

| Phase | Before (custom graph) | After (middleware) |
|-------|----------------------|-------------------|
| 1A | Build StateGraph with 4 custom nodes | Use create_deep_agent + middleware stack. Keep CostTracker, StreamEvent, FileStateTracker. |
| 1B | Build custom compaction + memory injection | SummarizationMiddleware + ContextEditingMiddleware handle compaction. Focus on Dream memory + management API. |
| 1C | Build custom sub-agent spawning + BaseStore | Use SubAgentMiddleware for spawning. Add orchestration tools + health monitoring. |
| 2A | Build harness phase system | Focus on phase gates, git worktree, conflict detection (no graph changes needed). |

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
