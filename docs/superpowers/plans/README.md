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
| Phase 1B | Memory & Observability | **NEXT** | Dream memory (2-stage + Git), management API (/v1/agents, /v1/memory, /v1/cost), WebSocket events | Phase 1A |
| Phase 1C | Sub-Agent System | PENDING | SubAgentMiddleware config, orchestration tools, BaseStore communication, health monitoring | Phase 1A |
| Phase 2A | Swarm & Harness | PENDING | Team templates, phase gates, git worktree, conflict detection, failure recovery | Phase 1C |
| Phase 2B | Channels & Web UI | PENDING | Discord, Slack, WebSocket channels + Web UI dashboard | Phase 1B |
| Phase 3 | Polish & Scale | PENDING | Additional channels, marketplace, LSP, natural language scheduling, Docker sandbox | Phase 2A + 2B |

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
