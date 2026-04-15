# LangAgent Platform — Design Specification
**Version:** 1.0  
**Date:** 2026-04-15  
**Base:** Fork of ciana-parrot + patterns from OpenHarness, nanobot, ClawTeam  
**Foundation:** LangChain / LangGraph / DeepAgents  

---

## Table of Contents

1. [Overview](#1-overview)
2. [Architectural Decisions](#2-architectural-decisions)
3. [System Architecture](#3-system-architecture)
4. [The Agent (Master + Solo + Swarm)](#4-the-agent)
5. [LLM Engine & Multi-Tier Routing](#5-llm-engine--multi-tier-routing)
6. [Streaming Event Lifecycle](#6-streaming-event-lifecycle)
7. [Tool Ecosystem](#7-tool-ecosystem)
8. [Sub-Agent System (LangGraph-Native)](#8-sub-agent-system)
9. [Skills System](#9-skills-system)
10. [Memory System](#10-memory-system)
11. [Communication Channels](#11-communication-channels)
12. [Host Gateway Bridge](#12-host-gateway-bridge)
13. [Scheduled Tasks](#13-scheduled-tasks)
14. [Permission & Security System](#14-permission--security-system)
15. [Context Compression](#15-context-compression)
16. [Session Management](#16-session-management)
17. [Plugin & Hook System](#17-plugin--hook-system)
18. [MCP Support](#18-mcp-support)
19. [Multi-User Architecture](#19-multi-user-architecture)
20. [Web UI (Management Dashboard)](#20-web-ui)
21. [Observability & Cost Tracking](#21-observability--cost-tracking)
22. [Configuration](#22-configuration)
23. [Docker Deployment](#23-docker-deployment)
24. [Project Structure](#24-project-structure)
25. [Phased Roadmap](#25-phased-roadmap)
26. [Gap Analysis Addendum — 35 Features from Reference Repos](#26-gap-analysis-addendum)
27. [Non-Functional Requirements](#27-non-functional-requirements)

---

## 1. Overview

LangAgent Platform is a production-grade AI agent platform that operates as a personal assistant, multi-agent swarm coordinator, and developer tool — all from a single codebase deployed via Docker.

It is built by forking **ciana-parrot** (which provides the LangGraph/DeepAgents foundation, multi-tier routing, Telegram, gateway, skills, memory, MCP, scheduling, and Docker deployment) and extending it with:

- **LangGraph-native multi-agent swarm** (inspired by ClawTeam's coordination patterns)
- **Dream memory** (from nanobot's 2-stage consolidation with Git versioning)
- **Expanded channel support** (from nanobot's 15+ channel integrations)
- **Permission system** (from OpenHarness's multi-level safety model)
- **Plugin/hook ecosystem** (own format, not Claude Code compatible)
- **Per-user sessions** for multi-user support
- **Full streaming event lifecycle** across all channels
- **Sub-agent failure detection and recovery**

---

## 2. Architectural Decisions

Decisions made during design review, with rationale:

| # | Decision | Rationale |
|---|----------|-----------|
| AD-1 | **LangGraph-native only** — no CLI agent spawning (tmux/subprocess). If we need a tool, we implement it. | Tighter control, full observability, dynamic tool subscription works. CLI processes are opaque to LangGraph. |
| AD-2 | **Fork ciana-parrot and extend** — not build from scratch. | ciana-parrot already has the LangGraph/DeepAgents foundation, RoutingChatModel, Telegram, gateway, skills, memory, MCP, scheduling, Docker. Saves 3-4 weeks. |
| AD-3 | **The agent IS the Master Agent** — one graph, one entry point. Orchestration tools are just more tools in the toolbelt. | No routing overhead. Agent naturally decides solo vs. team based on task complexity. |
| AD-4 | **Async Task Workers with BaseStore** for sub-agents — independent asyncio.Tasks with their own thread_ids, communicating via LangGraph's shared store. | Supports truly independent background agents, ongoing coordination, and independent lifecycles. |
| AD-5 | **6 memory files with clean ownership** — Dream owns {SOUL, USER, MEMORY}, Agent writes {REGISTRY, PLAYBOOK}, User edits {AGENT}. | Prevents write conflicts, keeps each file focused. |
| AD-6 | **Own plugin format only** — drop Claude Code plugin compatibility. MCP for external extensibility. | Clean format, no compatibility shim. MCP already provides unlimited extensibility. |
| AD-7 | **Trust LLM for parallel tools + max_parallel_tools config** as safety valve. | Modern models handle parallel tool calls well. Config throttle prevents resource exhaustion. |
| AD-8 | **Drop CLAUDE.md Discovery** — AGENT.md is the equivalent. Sub-agents read repo docs from their git worktree. | Agent lives in Docker with fixed workspace. No directory tree to walk. |
| AD-9 | **LangGraph interrupt() for permission approvals** — channel-agnostic. Each channel renders its own approval UI. | Works natively with LangGraph checkpointing. Telegram: inline keyboard. CLI: y/n. API: webhook. |
| AD-10 | **Per-user sessions, shared agent identity** — per-user USER.md, shared SOUL/AGENT/MEMORY. | One agent personality, but personalized per user. Session isolation already exists via thread_id. |
| AD-11 | **Heartbeat folded into sub-agent health monitoring** — BaseStore timestamps, not a separate feature. | Simpler architecture, heartbeat is just one aspect of health monitoring. |
| AD-12 | **3-layer failure detection + priority chain recovery** for sub-agents — heartbeat + timeout + iteration limit → retry → escalate → reassign → abort. | Defense in depth. No single detection covers all failure modes. |
| AD-13 | **Web UI + Chat channels** — Chat (Telegram, Discord, CLI) for conversation; Web UI for management (swarm dashboard, config, cost). Not blocking core platform. | Best of both: chat on-the-go, dashboard at desk. Web UI is Phase 2, doesn't block Phase 0-1. |

---

## 3. System Architecture

### 3.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        CHANNELS LAYER                           │
│  Telegram │ Discord │ Slack │ Feishu │ Matrix │ CLI │ API │ WS  │
│                                                                 │
│  Per-channel: allowlists, group policy, approval UI rendering   │
│  Channel adapter: AbstractChannel protocol                      │
└─────────────────────────┬───────────────────────────────────────┘
                          │ IncomingMessage / SendResult
┌─────────────────────────▼───────────────────────────────────────┐
│                      MESSAGE BUS                                │
│  Async queue │ Channel routing │ Thread mapping │ Rate limiting  │
│  User ID extraction │ Per-user session routing                  │
└─────────────────────────┬───────────────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────────────┐
│                   SESSION MANAGER                               │
│  Per-user thread isolation │ SQLite/Postgres checkpointer       │
│  Auto-resume from checkpoint │ Session TTL │ Counter sync       │
└─────────────────────────┬───────────────────────────────────────┘
                          │
┌═════════════════════════▼═══════════════════════════════════════┐
║              THE AGENT (LangGraph State Graph)                  ║
║                                                                 ║
║  One graph. One entry point. Three operating modes:             ║
║                                                                 ║
║  ┌─────────┐  ┌───────────┐  ┌──────────────────────────────┐  ║
║  │  SOLO   │  │ CONDUCTOR │  │        DELEGATOR             │  ║
║  │ handles │  │ spawns    │  │ user manages agents,         │  ║
║  │ simple  │  │ sub-agent │  │ agent assists with           │  ║
║  │ tasks   │  │ teams     │  │ orchestration tools          │  ║
║  │ directly│  │ auto-     │  │                              │  ║
║  └─────────┘  └───────────┘  └──────────────────────────────┘  ║
║                                                                 ║
║  Tools: standard + orchestration + gateway                      ║
║  Memory: SOUL + USER + MEMORY + AGENT + REGISTRY + PLAYBOOK    ║
║  Model: RoutingChatModel (lite → standard → advanced → expert)  ║
╚═════════════════════════╦═══════════════════════════════════════╝
                          │
        ┌─────────────────┼─────────────────┐
        ▼                 ▼                 ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│   MEMORY     │  │  PERMISSIONS │  │  SCHEDULER   │
│   SOUL.md    │  │  interrupt() │  │  Cron        │
│   USER.md/   │  │  Path rules  │  │  Interval    │
│   MEMORY.md  │  │  Tool hooks  │  │  One-shot    │
│   REGISTRY   │  │  Sandbox     │  │  Natural lang│
│   PLAYBOOK   │  │  Gateway ACL │  │  Per-user    │
│   Dream      │  │              │  │              │
└──────────────┘  └──────────────┘  └──────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│              SUB-AGENT POOL (LangGraph-Native)                  │
│                                                                 │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                     │
│  │ Agent A  │  │ Agent B  │  │ Agent C  │  ...                  │
│  │ asyncio  │  │ asyncio  │  │ asyncio  │                      │
│  │ Task     │  │ Task     │  │ Task     │                      │
│  │ own      │  │ own      │  │ own      │                      │
│  │ thread_id│  │ thread_id│  │ thread_id│                      │
│  │ custom   │  │ custom   │  │ custom   │                      │
│  │ tools    │  │ tools    │  │ tools    │                      │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘                     │
│       └──────────────┴──────────────┘                           │
│                      │                                          │
│              BaseStore (shared memory)                           │
│              Health monitor (heartbeat + timeout + iterations)   │
│              Git worktree per agent (for code tasks)             │
│              Cost tracking per agent                             │
└─────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│                    HOST GATEWAY                                 │
│  HTTP bridge │ HMAC auth │ Per-bridge allowlists │ CWD safety   │
│  Bridges: Spotify, Reminders, iMessage, Things, Bear,           │
│           Obsidian, 1Password, HomeKit, Sonos, Camsnap, ...     │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 Data Flow — Single Message

```
1. User sends message via Telegram
2. Telegram channel adapter → IncomingMessage(user_id, chat_id, text, attachments)
3. Message bus → resolves thread_id = f"{channel}_{chat_id}_{user_id}_s{counter}"
4. Session manager → loads checkpoint from SQLite (or creates new)
5. Injects context: SOUL.md + USER.md(user_id) + MEMORY.md + AGENT.md + skills summary
6. Agent graph invoked with astream_events()
7. Agent reasons → decides solo or spawn team
8. If solo: calls tools, streams tokens back to channel
9. If spawn: creates sub-agents as asyncio.Tasks, monitors via BaseStore
10. Response streamed back through channel adapter
11. State checkpointed to SQLite
12. Cost tracked per user_id and tier
```

---

## 4. The Agent

### 4.1 Single Graph, Three Modes

The agent is one LangGraph StateGraph. It does not have separate "master" and "worker" graphs. The distinction is behavioral, driven by which tools it uses:

- **Solo mode**: Agent uses standard tools (read, write, exec, web_search, etc.) to handle a task directly. This is the default for simple requests.
- **Conductor mode**: Agent uses orchestration tools (spawn_agent, assign_task, monitor_agents) to decompose complex goals into sub-agent teams. The agent decides this autonomously based on task complexity.
- **Delegator mode**: User explicitly manages agents via slash commands (/spawn, /assign, /recall). The agent assists but doesn't make autonomous orchestration decisions.

### 4.2 Agent State

```python
from langgraph.graph import StateGraph, MessagesState
from typing import Any

class AgentState(MessagesState):
    # Core
    active_tier: str = "standard"           # Current LLM tier
    session_id: str = ""                    # Thread ID for checkpointing
    channel: str = ""                       # Source channel name
    user_id: str = ""                       # User identifier
    
    # Context (injected before each invocation)
    memory_context: str = ""                # SOUL + USER + MEMORY + AGENT
    skills_summary: str = ""                # Available skills summary
    
    # Orchestration (only populated in conductor/delegator mode)
    active_sub_agents: dict[str, dict] = {} # agent_id → {role, tier, tools, status}
    pending_tasks: list[dict] = []          # Unassigned tasks
    
    # Permissions
    tool_permissions: dict[str, str] = {}   # tool_name → "allow"/"deny"/"ask"
    
    # Cost
    cost_this_session: float = 0.0          # Running cost in cents
    cost_budget: float | None = None        # Optional budget limit
```

### 4.3 Graph Structure

```python
graph = StateGraph(AgentState)

# Nodes
graph.add_node("agent", agent_reasoning_node)       # LLM call with RoutingChatModel
graph.add_node("permission_check", permission_node)  # Check tool permissions
graph.add_node("tools", tool_executor_node)          # Execute tools (parallel capable)
graph.add_node("monitor", sub_agent_monitor_node)    # Check sub-agent health (periodic)

# Edges
graph.add_conditional_edges("agent", route_after_reasoning)
# route_after_reasoning returns:
#   "permission_check" → if tool calls present
#   "monitor"          → if sub-agents active and no tool calls
#   END                → if no tool calls and no active sub-agents

graph.add_conditional_edges("permission_check", route_after_permission)
# route_after_permission returns:
#   "tools"    → all tools approved
#   "agent"    → some tools denied, re-plan
#   interrupt  → needs user approval (LangGraph interrupt())

graph.add_edge("tools", "agent")       # After tool execution, reason again
graph.add_edge("monitor", "agent")     # After monitoring, reason with updated state

# Compile
checkpointer = AsyncSqliteSaver.from_conn_string("data/checkpoints.db")
store = InMemoryStore()  # InMemory for dev; use SQLite/Postgres BaseStore in production
app = graph.compile(checkpointer=checkpointer, store=store)
```

### 4.4 Orchestration Tools

These are standard `@tool` decorated functions available to the agent. They manipulate sub-agents by writing to the BaseStore and managing asyncio.Tasks:

```python
@tool
async def spawn_agent(
    name: str,
    role: str,
    task: str,
    tools: list[str],
    skills: list[str] = [],
    tier: str = "standard",
) -> str:
    """Spawn a sub-agent as a background LangGraph task.
    
    Args:
        name: Human-readable agent name (e.g., "backend-dev")
        role: Agent role (e.g., "executor", "planner", "evaluator")
        task: The task description for this agent
        tools: List of tool names to make available
        skills: List of skill names to load
        tier: LLM tier (lite/standard/advanced/expert)
    
    Returns:
        Agent ID for future reference
    """

@tool
async def subscribe_tool(agent_id: str, tool_name: str) -> str:
    """Add a tool to a running sub-agent's toolset."""

@tool
async def unsubscribe_tool(agent_id: str, tool_name: str) -> str:
    """Remove a tool from a running sub-agent's toolset."""

@tool
async def subscribe_skill(agent_id: str, skill_name: str) -> str:
    """Load a skill into a running sub-agent's context."""

@tool  
async def assign_task(agent_id: str, task: str, priority: str = "medium") -> str:
    """Assign a new task to a running sub-agent via BaseStore."""

@tool
async def monitor_agents() -> str:
    """Get status of all active sub-agents: health, progress, cost."""

@tool
async def recall_agent(agent_id: str) -> str:
    """Terminate a sub-agent, collect its results, merge git worktree if applicable."""

@tool
async def switch_agent_model(agent_id: str, tier: str) -> str:
    """Change the LLM tier of a running sub-agent."""

@tool
async def create_team(template: str, goal: str) -> str:
    """Spawn a full team from a TOML template with a goal."""

@tool
async def dissolve_team(team_id: str) -> str:
    """Terminate all agents in a team, merge work, cleanup."""

@tool
async def escalate(agent_id: str, reason: str) -> str:
    """Bump a sub-agent to the next higher tier."""

@tool
async def review_cost() -> str:
    """Get cost breakdown by agent, tier, team, and user."""
```

### 4.5 Knowledge Files

| File | Owner | Updated by | Purpose |
|------|-------|------------|---------|
| `SOUL.md` | Dream process | Periodic batch reflection | Agent identity, personality, voice, values |
| `USER.md` | Dream process | Periodic batch reflection | User preferences, habits, knowledge (per-user) |
| `MEMORY.md` | Dream + Agent | Dream (periodic) + agent (real-time) | Project facts, decisions, durable context |
| `AGENT.md` | User | Manual editing only | Behavior instructions, tool guidelines |
| `AGENT_REGISTRY.md` | Agent | Direct writes after swarm outcomes | Known agent archetypes and their configs |
| `TEAM_PLAYBOOK.md` | Agent | Direct writes after swarm outcomes | Team configurations that worked well |

---

## 5. LLM Engine & Multi-Tier Routing

### 5.1 Supported Providers

| Provider | Priority | Integration | Notes |
|----------|----------|-------------|-------|
| Anthropic (Claude) | P0 | Native SDK | Extended thinking, prompt caching |
| OpenAI (GPT) | P0 | Native SDK | Reasoning models (o1/o3) |
| Google Gemini | P0 | langchain-google-genai | |
| Groq | P1 | langchain-groq | Fast inference, Whisper transcription |
| Ollama | P1 | langchain-ollama | Local deployment |
| OpenRouter | P1 | OpenAI-compatible | Gateway for 200+ models |
| vLLM | P1 | OpenAI-compatible | Self-hosted inference |
| DeepSeek | P2 | OpenAI-compatible | Chain-of-thought reasoning |
| Moonshot/Kimi | P2 | OpenAI-compatible | |
| Qwen (DashScope) | P2 | OpenAI-compatible | |
| Bedrock (AWS) | P2 | langchain-aws | Enterprise |

### 5.2 RoutingChatModel

Inherited from ciana-parrot. Each tier is an independently configured LLM instance:

```yaml
model_router:
  default_tier: "standard"
  tiers:
    lite:
      provider: "groq"
      model: "llama-3.3-70b-versatile"
    standard:
      provider: "anthropic"
      model: "claude-sonnet-4-6"
    advanced:
      provider: "anthropic"
      model: "claude-opus-4-6"
    expert:
      provider: "anthropic"
      model: "claude-opus-4-6"
      extended_thinking: true
```

**Routing mechanism:**
- `ContextVar(_active_tier)` tracks the current tier per asyncio task
- Agent calls `switch_model(tier="expert")` to upgrade mid-conversation
- Sub-agents can run on different tiers independently
- Scheduled tasks specify tier at creation time
- On provider error: automatic fallback to next lower tier

### 5.3 Retry with Exponential Backoff

```python
RETRYABLE_STATUS = {429, 500, 502, 503, 529}
MAX_RETRIES = 3
BASE_DELAY = 1.0
MAX_DELAY = 30.0

async def call_with_retry(fn, *args, **kwargs):
    for attempt in range(MAX_RETRIES + 1):
        try:
            return await fn(*args, **kwargs)
        except APIError as e:
            if e.status_code not in RETRYABLE_STATUS or attempt == MAX_RETRIES:
                raise
            delay = min(BASE_DELAY * (2 ** attempt) + random.uniform(0, 1), MAX_DELAY)
            retry_after = e.headers.get("Retry-After")
            if retry_after:
                delay = max(delay, float(retry_after))
            await asyncio.sleep(delay)
```

Non-retryable conditions: `billing_hard_limit`, `payment_required`, `insufficient_quota`.

---

## 6. Streaming Event Lifecycle

### 6.1 Event Types

The agent emits a stream of typed events throughout its execution cycle:

```python
@dataclass
class StreamEvent:
    type: str          # Event type
    data: Any          # Event payload
    timestamp: float   # Unix timestamp
    agent_id: str      # "master" or sub-agent ID
    user_id: str       # Target user

# Event types:
# "token"           → LLM generated a text token delta
# "thinking"        → Extended thinking content (for models that support it)
# "tool_call_start" → Agent is about to call a tool (name, args)
# "tool_call_end"   → Tool returned a result (name, result summary)
# "tool_error"      → Tool execution failed (name, error)
# "tier_switch"     → Agent switched LLM tier (from, to)
# "agent_spawn"     → Sub-agent spawned (agent_id, role, task)
# "agent_progress"  → Sub-agent status update (agent_id, message)
# "agent_complete"  → Sub-agent finished (agent_id, result summary)
# "agent_failed"    → Sub-agent failed (agent_id, error, recovery action)
# "approval_request"→ Permission check needs user input (tool, args)
# "cost_update"     → Token usage and cost for this turn
# "error"           → Unrecoverable error
# "done"            → Agent finished responding
```

### 6.2 Full Streaming Cycle

```
User sends "Build me a REST API"
    │
    ▼
[token] "I'll set up a team for this..."
[token] "Let me spawn an architect and a developer."
[tool_call_start] spawn_agent(name="architect", role="planner", ...)
[tool_call_end] spawn_agent → "agent-abc123 spawned"
[agent_spawn] {agent_id: "agent-abc123", role: "planner", task: "Design API schema"}
[tool_call_start] spawn_agent(name="backend-dev", role="executor", ...)
[tool_call_end] spawn_agent → "agent-def456 spawned"
[agent_spawn] {agent_id: "agent-def456", role: "executor", task: "Implement endpoints"}
[token] "Team is working. I'll monitor progress..."
    │
    ... (time passes, sub-agents work) ...
    │
[agent_progress] {agent_id: "agent-abc123", message: "Schema designed, 5 endpoints defined"}
[agent_complete] {agent_id: "agent-abc123", result: "API schema in workspace/api_schema.json"}
[agent_progress] {agent_id: "agent-def456", message: "Implementing endpoint 3/5"}
[cost_update] {total_tokens: 45000, cost_cents: 12.5}
    │
    ... (more time) ...
    │
[agent_complete] {agent_id: "agent-def456", result: "All endpoints implemented and tested"}
[token] "Your REST API is ready! Here's what was built..."
[done]
```

### 6.3 Channel-Specific Rendering

Each channel adapter translates StreamEvents into platform-appropriate output:

| Event | Telegram | CLI | API (SSE) | WebSocket |
|-------|----------|-----|-----------|-----------|
| `token` | Edit message in-place (draft) | Print to stdout | `data: {"delta": "..."}` | JSON frame |
| `thinking` | Collapse into "Thinking..." indicator | Dimmed text | Include if requested | JSON frame |
| `tool_call_start` | "Using web_search..." (collapsible detail) | Spinner with tool name | `data: {"tool": "..."}` | JSON frame |
| `tool_call_end` | Update collapsible with result | Replace spinner | `data: {"result": "..."}` | JSON frame |
| `agent_spawn` | "Spawned architect (advanced tier)" | Status line | `data: {"agent": "..."}` | JSON frame |
| `agent_progress` | Periodic status update message | Status bar | `data: {"progress": "..."}` | JSON frame |
| `approval_request` | Inline keyboard [Approve] [Deny] | y/n prompt | Webhook callback | JSON frame + wait |
| `cost_update` | Suppress (show on /status) | Suppress | Include | Include |

### 6.4 Streaming Configuration

```yaml
streaming:
  enabled: true                    # Global toggle
  token_batching_ms: 50            # Batch tokens for this many ms before sending (reduces Telegram API calls)
  show_thinking: false             # Show extended thinking content to user
  show_tool_details: true          # Show tool arguments and results
  show_sub_agent_progress: true    # Show sub-agent status updates
  show_cost: false                 # Show cost updates in real-time
```

---

## 7. Tool Ecosystem

### 7.1 Core Tools (P0)

Inherited from ciana-parrot:

| Tool | Description | Parallel-safe |
|------|-------------|---------------|
| `read_file` | Read files with line range, PDF/image capable | Yes |
| `write_file` | Create/overwrite files atomically | No |
| `edit_file` | Line-range edit, insert, delete | No |
| `glob` | Fast file pattern matching | Yes |
| `grep` | Content search with regex | Yes |
| `exec` | Sandboxed shell execution | No |
| `web_search` | Multi-provider: Brave, DuckDuckGo, Tavily, SearXNG, Kagi | Yes |
| `web_fetch` | HTML to Markdown with readability extraction | Yes |
| `schedule_task` | Create cron/interval/one-shot tasks | Yes |
| `list_tasks` | List active scheduled tasks | Yes |
| `cancel_task` | Cancel a scheduled task | Yes |
| `host_execute` | Execute host CLI tools via gateway bridge | No |
| `switch_model` | Switch LLM tier mid-conversation | Yes |

### 7.2 Extended Tools (P1)

| Tool | Description | Parallel-safe |
|------|-------------|---------------|
| `notebook_edit` | Jupyter cell manipulation | No |
| `mcp_tool` | Call any MCP server tool | Depends |

### 7.3 Orchestration Tools (P1)

| Tool | Description | Parallel-safe |
|------|-------------|---------------|
| `spawn_agent` | Spawn a LangGraph sub-agent | Yes |
| `subscribe_tool` | Add tool to running sub-agent | Yes |
| `unsubscribe_tool` | Remove tool from sub-agent | Yes |
| `subscribe_skill` | Load skill into sub-agent | Yes |
| `assign_task` | Assign task to sub-agent | Yes |
| `monitor_agents` | Get all sub-agent status | Yes |
| `recall_agent` | Terminate and collect results | No |
| `switch_agent_model` | Change sub-agent tier | Yes |
| `create_team` | Spawn team from template | No |
| `dissolve_team` | Terminate team and merge | No |
| `escalate` | Bump sub-agent to higher tier | Yes |
| `review_cost` | Cost breakdown | Yes |

### 7.4 Parallel Execution

- When the LLM returns multiple tool calls, all are executed concurrently via `asyncio.gather`
- Safety valve: `max_parallel_tools` config (default: 10)
- No tool classification needed — trust the LLM to avoid conflicting calls
- If a tool fails in a parallel batch, other tools still complete; failed result is returned to the LLM

---

## 8. Sub-Agent System (LangGraph-Native)

### 8.1 Architecture

Each sub-agent is:
- An independent LangGraph compiled graph
- Running as an `asyncio.Task`
- With its own `thread_id` in the checkpointer
- With a custom tool subset (configured at spawn time, modifiable at runtime)
- Communicating via LangGraph's `BaseStore` (shared key-value memory)

```python
async def spawn_sub_agent(
    agent_id: str,
    task: str,
    tools: list[BaseTool],
    skills: list[str],
    tier: str,
    store: BaseStore,
    checkpointer: BaseCheckpointSaver,
) -> asyncio.Task:
    """Create and launch a sub-agent as an asyncio task."""
    
    # Build sub-agent graph with custom tool subset
    sub_graph = build_agent_graph(tools=tools, skills=skills)
    sub_app = sub_graph.compile(checkpointer=checkpointer, store=store)
    
    # Create the task
    async def run_agent():
        thread_id = f"sub_{agent_id}"
        config = {"configurable": {"thread_id": thread_id}}
        
        # Write heartbeat and process task
        while not done:
            # Update heartbeat in store
            await store.aput(("agents", agent_id), "heartbeat", {
                "timestamp": time.time(),
                "status": "running",
                "iteration": iteration,
            })
            
            # Run one step of the agent
            result = await sub_app.ainvoke(state, config)
            
            # Write progress to store for master to read
            await store.aput(("agents", agent_id), "progress", {
                "message": extract_progress(result),
                "cost": accumulated_cost,
            })
    
    task = asyncio.create_task(run_agent())
    return task
```

### 8.2 Communication via BaseStore

Sub-agents and the master communicate through namespaced keys in BaseStore:

```
Namespace: ("agents", "{agent_id}")
Keys:
  "config"     → {role, tier, tools, skills, task}     # Written by master at spawn
  "heartbeat"  → {timestamp, status, iteration}        # Written by sub-agent periodically
  "progress"   → {message, cost, artifacts}             # Written by sub-agent after each step
  "result"     → {status, output, cost_total}           # Written by sub-agent on completion
  "inbox"      → [{from, message, timestamp}, ...]      # Written by master or other agents
  "directive"  → {action, params}                        # Written by master (e.g., "change tier")

Namespace: ("teams", "{team_id}")
Keys:
  "config"     → {template, goal, agents, phase}
  "task_board" → [{id, description, assignee, status, depends_on}, ...]
  "cost"       → {total_tokens, total_cost, per_agent}
```

### 8.3 Failure Detection (3 layers)

| Detection | Mechanism | Default Threshold |
|-----------|-----------|-------------------|
| Heartbeat | Sub-agent writes timestamp to BaseStore. Master checks for stale entries. | 120 seconds |
| Timeout | asyncio.Task timeout. Configurable per agent. | 30 minutes |
| Iteration limit | Max tool-call cycles. Inherited from ciana-parrot's `max_tool_iterations`. | 50 iterations |

### 8.4 Recovery (Priority Chain)

When a sub-agent failure is detected:

```
1. RETRY (same tier)
   → Respawn agent with same config
   → Resume from last checkpoint
   → If fails again → step 2

2. ESCALATE (higher tier)
   → Bump tier: lite→standard→advanced→expert
   → Respawn with higher-capability model
   → If already at expert or fails again → step 3

3. REASSIGN (different agent)
   → Create new agent with different role/skills
   → Give it the failed task + context of what was tried
   → If fails → step 4

4. ABORT (notify user)
   → Cancel the task
   → Send failure report to user via channel
   → Include: what was attempted, what failed, partial results
```

### 8.5 Budget Enforcement

```yaml
cost:
  budget_per_session: null          # No limit by default (cents)
  budget_per_agent: 100             # Max 100 cents per sub-agent
  budget_warning_threshold: 0.8     # Warn at 80% of budget
  on_budget_exceeded: "downgrade"   # "downgrade" | "pause" | "abort"
```

When budget threshold is reached:
- `downgrade`: Automatically switch agent to next lower tier
- `pause`: Interrupt graph, ask user for approval to continue
- `abort`: Kill the agent, report partial results

### 8.6 Git Worktree Isolation

For code-related tasks, sub-agents get isolated git worktrees:

```python
@tool
async def spawn_agent(name, role, task, tools, skills, tier, git_worktree=False):
    if git_worktree:
        branch = f"agent/{name}"
        worktree_path = f"/tmp/worktrees/{agent_id}"
        # git worktree add {worktree_path} -b {branch}
        # Sub-agent's file tools are scoped to this path
```

When `recall_agent` is called, the worktree is either merged back to the base branch or discarded.

---

## 9. Skills System

### 9.1 Format

Inherited from ciana-parrot, compatible with anthropics skills format:

```markdown
---
name: spotify
description: "Control Spotify playback and manage playlists via the host gateway"
requires_bridge: "spotify"
requires_env: []
homepage: "https://github.com/..."
---

# Spotify Control

## Available Commands
- `host_execute(bridge="spotify", command="play", args=["song name"])` — Play a song
- `host_execute(bridge="spotify", command="pause")` — Pause playback
...
```

### 9.2 Features

- **Auto-discovery** from `workspace/skills/` and `skills/builtin/`
- **Progressive loading** — skill summary sent first, full content loaded on demand via read_file
- **Conditional activation** — `requires_env` hides skill if env var missing; `requires_bridge` hides if gateway bridge unavailable
- **Hot-reload** — add skill folder at runtime, no restart needed
- **Per-agent skills** — sub-agents can be spawned with a specific skill subset via `subscribe_skill`
- **Skill marketplace** — future: discover and install skills from remote registry

### 9.3 Built-in Skills

| Skill | Description | Requires |
|-------|-------------|----------|
| memory | Memory management and query | — |
| github | GitHub repository operations | GITHUB_TOKEN |
| commit | Git commit best practices | — |
| debug | Systematic debugging methodology | — |
| review | Code review patterns | — |
| plan | Implementation planning | — |
| cron | Scheduled task management | — |
| spotify | Spotify control | spotify bridge |
| apple-reminders | Apple Reminders | apple-reminders bridge |
| 1password | 1Password secrets | 1password bridge |
| bear-notes | Bear Notes | bear-notes bridge |
| obsidian | Obsidian vault | obsidian bridge |
| things | Things task manager | things bridge |
| imessage | iMessage | imessage bridge |
| homekit | HomeKit devices | homekit bridge |
| weather | Weather information | — |
| skill-creator | Create new skills interactively | — |

---

## 10. Memory System

### 10.1 Memory Files

| File | Location | Owner | Updated by |
|------|----------|-------|------------|
| `SOUL.md` | `workspace/SOUL.md` | Dream | Periodic batch reflection |
| `USER.md` | `workspace/users/{user_id}/USER.md` | Dream | Periodic, per-user |
| `MEMORY.md` | `workspace/MEMORY.md` | Dream + Agent | Dream (periodic) + agent (real-time writes) |
| `AGENT.md` | `workspace/AGENT.md` | User | Manual editing only |
| `AGENT_REGISTRY.md` | `workspace/AGENT_REGISTRY.md` | Agent | Direct writes after swarm outcomes |
| `TEAM_PLAYBOOK.md` | `workspace/TEAM_PLAYBOOK.md` | Agent | Direct writes after swarm outcomes |

### 10.2 Stage 1 — Consolidation

When context window pressure increases (token count approaches threshold):

1. Summarize oldest messages in conversation into a compact representation
2. Append summary to `memory/history.jsonl` (cursor-based, incremental)
3. Remove summarized messages from active context
4. Triggered automatically by token threshold or manually via `/consolidate`

### 10.3 Stage 2 — Dream

Periodic process (default: every 2 hours) that studies new history and updates knowledge files:

**Phase 1 — Study:** Read new entries in `history.jsonl` since last cursor. Read current SOUL.md, USER.md, MEMORY.md.

**Phase 2 — Edit:** Make minimal, surgical edits to knowledge files based on what was learned. Only change what's new or corrected. Don't rewrite existing content that's still accurate.

**Audit trail:** All changes tracked via Git in `memory/.git/`. Commands:
- `/dream` — Trigger manually
- `/dream-log` — Show recent changes
- `/dream-restore {sha}` — Revert to a previous state

### 10.4 Context Injection

Before each agent invocation, inject into the system prompt:
1. SOUL.md (full content)
2. USER.md for the current user_id (full content)
3. MEMORY.md (full content)
4. AGENT.md (full content)
5. AGENT_REGISTRY.md (summary — agent reads full on demand)
6. TEAM_PLAYBOOK.md (summary — agent reads full on demand)
7. Skills summary (names + descriptions, agent reads full content via read_file)

---

## 11. Communication Channels

### 11.1 Architecture

```python
class AbstractChannel(ABC):
    """Base class for all communication channels."""
    
    @abstractmethod
    async def start(self) -> None: ...
    
    @abstractmethod
    async def stop(self) -> None: ...
    
    @abstractmethod
    async def send(self, thread_id: str, content: str, **kwargs) -> SendResult: ...
    
    @abstractmethod
    async def send_file(self, thread_id: str, file: bytes, filename: str, **kwargs) -> SendResult: ...
    
    @abstractmethod
    async def render_stream_event(self, thread_id: str, event: StreamEvent) -> None: ...
    
    @abstractmethod
    async def render_approval(self, thread_id: str, tool_name: str, args: dict) -> None: ...
    
    def on_message(self, callback: Callable[[IncomingMessage], Awaitable[None]]): ...
```

### 11.2 Channel Implementations

| Channel | Phase | Key Features |
|---------|-------|--------------|
| **Telegram** | P0 (inherited) | Long-polling, voice transcription, photos, inline keyboards, Markdown→HTML, draft streaming (edit message in-place), approval via inline keyboard |
| **CLI** | P0 | Interactive Rich TUI, streaming to stdout, y/n approval prompt |
| **OpenAI-compatible API** | P0 | REST + SSE, `/v1/chat/completions`, webhook for approvals |
| **Discord** | P1 | Bot websocket, embeds, file attachments, reaction-based approval |
| **Slack** | P1 | Bot token, threads, file upload, Block Kit for approval |
| **WebSocket** | P1 | Real-time bidirectional, JSON frames, approval via message |
| **Feishu/Lark** | P2 | CardKit streaming, media cards |
| **Matrix/Element** | P2 | E2EE support, media |
| **WeChat** | P2 | QR scan, voice memo |
| **Email** | P2 | IMAP/SMTP, queued (no streaming) |
| **WhatsApp** | P3 | Node.js bridge, QR scan |

### 11.3 Per-Channel Configuration

```yaml
channels:
  telegram:
    enabled: true
    token: "${TELEGRAM_BOT_TOKEN}"
    trigger: "@Agent"           # Activation trigger in groups
    allowed_users: [123456]     # User ID allowlist (empty = all)
    group_policy: "mention"     # "mention" | "open" | "allowlist"
    streaming:
      draft_mode: true          # Edit message in-place while streaming
      batch_ms: 100             # Batch token updates
  discord:
    enabled: false
    token: "${DISCORD_BOT_TOKEN}"
  api:
    enabled: true
    host: "0.0.0.0"
    port: 8900
```

### 11.4 Voice Transcription

Inherited from ciana-parrot:

```yaml
transcription:
  enabled: true
  provider: "groq"        # or "openai"
  model: "whisper-large-v3-turbo"
  api_key: "${GROQ_API_KEY}"
```

Voice messages on Telegram (and other channels that support audio) are automatically transcribed and processed as text.

---

## 12. Host Gateway Bridge

### 12.1 Architecture

Inherited from ciana-parrot. Standalone HTTP server on host, async client in Docker:

```
Docker Container                    Host Machine
┌──────────────┐    HTTP/HMAC     ┌──────────────┐
│ Gateway      │ ───────────────→ │ Gateway      │
│ Client       │    port 9842     │ Server       │
│ (httpx)      │ ←─────────────── │ (threading)  │
└──────────────┘                  └──────┬───────┘
                                         │ subprocess.run(shell=False)
                                         ▼
                                  ┌──────────────┐
                                  │ Host CLI     │
                                  │ spogo, memo, │
                                  │ things, op   │
                                  └──────────────┘
```

### 12.2 Security Layers

1. **HMAC token authentication** — shared secret between client and server
2. **Per-bridge command allowlists** — only approved commands per bridge
3. **CWD path traversal prevention** — realpath validation against allowed_cwd
4. **No shell execution** — `subprocess.run(shell=False)` always
5. **Configurable timeouts** — per-bridge timeout settings

### 12.3 Default Bridges

```yaml
gateway:
  host: "host.docker.internal"
  port: 9842
  token: "${GATEWAY_TOKEN}"
  bridges:
    spotify:         { command: "spogo",        allowed_commands: ["play", "pause", "next", "prev", "current", "search"] }
    apple-reminders: { command: "remindctl",    allowed_commands: ["add", "list", "complete", "delete"] }
    things:          { command: "things",        allowed_commands: ["add", "list", "complete", "show"] }
    imessage:        { command: "imsg",          allowed_commands: ["send", "read", "search"] }
    bear-notes:      { command: "grizzly",       allowed_commands: ["create", "search", "open", "list"] }
    obsidian:        { command: "obsidian-cli",  allowed_commands: ["search", "create", "read", "list"] }
    1password:       { command: "op",            allowed_commands: ["item get", "item list"] }
    homekit:         { command: "openhue",       allowed_commands: ["get", "set", "list"] }
    sonos:           { command: "sonos",         allowed_commands: ["play", "pause", "volume", "status"] }
    camsnap:         { command: "camsnap",       allowed_commands: ["snap"] }
```

### 12.4 Avatar Emotion System (Optional)

```yaml
avatar:
  enabled: false
  tier: "lite"
```

When enabled: after each agent response, a lite-tier LLM analyzes the response emotion and POSTs to the gateway's `/avatar/emotion` endpoint, which relays via SSE to a connected browser client displaying a 3D avatar.

---

## 13. Scheduled Tasks

### 13.1 Task Types

Inherited from ciana-parrot:

- **Cron** — Standard 5-field cron expressions with IANA timezone support
- **Interval** — Repeat every N seconds
- **Once** — ISO timestamp for one-shot execution
- **Natural language** (P2) — "Every weekday at 9am", "Tomorrow at 3pm" parsed to cron

### 13.2 Agent-Created Tasks

```python
@tool
async def schedule_task(
    prompt: str,
    schedule_type: str,      # "cron" | "interval" | "once"
    schedule_value: str,     # Cron expression | seconds | ISO timestamp
    model_tier: str = "",    # Override tier for this task (default: use default_tier)
) -> str:
    """Schedule a recurring or one-shot task."""
```

### 13.3 Features

- Agent creates tasks conversationally ("Check my portfolio every morning at 9am")
- Model tier override per task (use lite for routine monitoring)
- Results delivered back to originating channel and user
- Job history: success/failure/duration tracking
- Persistent across container restarts (JSON + asyncio.Lock)
- Per-user task ownership (user A's tasks don't run for user B)

---

## 14. Permission & Security System

### 14.1 Permission Modes

| Mode | Behavior |
|------|----------|
| **default** | Ask before write/execute operations (file writes, shell, gateway) |
| **auto** | Allow everything. For trusted/sandboxed environments. |
| **plan** | Block all write operations. Read-only exploration. |

### 14.2 LangGraph interrupt() for Approvals

When a tool requires permission and mode is `default`:

1. Permission check node evaluates the tool call against rules
2. If approval needed: `interrupt({"tool": name, "args": args})` 
3. Graph checkpoints and pauses
4. Channel adapter renders approval UI (Telegram: inline keyboard, CLI: y/n)
5. User responds → graph resumes from checkpoint
6. If approved: tool executes. If denied: tool skipped, agent re-plans.

### 14.3 Security Layers

| Layer | Mechanism |
|-------|-----------|
| LLM tier | RoutingChatModel prevents expensive models on trivial tasks |
| Tool permissions | PreToolUse hook checks rules before execution |
| Path rules | Glob-based allow/deny lists for filesystem access |
| Command rules | Deny list for dangerous shell commands (rm -rf, etc.) |
| Filesystem sandbox | Docker isolation + workspace confinement (`virtual_mode=True`) |
| Shell sandbox | bwrap for Linux, command allowlist |
| Gateway ACL | Per-bridge command allowlists + CWD restriction |
| Channel ACL | Per-channel user allowlists + group policies |
| Credential protection | Hardcoded deny for SSH, AWS, GCP, Docker credential paths |
| Input validation | Pydantic v2 for all tool inputs + JSON repair for malformed LLM output |
| Budget enforcement | Per-agent and per-session cost limits |

---

## 15. Context Compression

### 15.1 Problem

LangGraph checkpoints save full message history. Long conversations exceed the LLM's context window. We need to compress old messages while preserving task state.

### 15.2 Design

Two-stage compression, triggered by token count threshold:

**Stage 1 — Micro-compact (within conversation):**
- When estimated tokens > 80% of context window
- Summarize oldest tool results (keep tool calls, replace verbose results with summaries)
- Preserve: last N user/assistant turns, all pending tool calls, system prompt
- Implementation: custom LangGraph node that rewrites message history before the agent node

**Stage 2 — Consolidation (to persistent memory):**
- When estimated tokens > 90% of context window after micro-compact
- Summarize entire old conversation segment into history.jsonl
- Reset conversation to: system prompt + summary message + recent turns
- Preserves continuity: "Previous context: [summary]"

### 15.3 Token Estimation

```python
def estimate_tokens(messages: list[BaseMessage]) -> int:
    """Fast token estimation without calling the tokenizer API.
    
    Uses character count heuristic: ~4 chars per token for English.
    Accurate to within ~10%, sufficient for threshold decisions.
    """
    total_chars = sum(len(m.content) for m in messages if isinstance(m.content, str))
    return total_chars // 4
```

### 15.4 Configuration

```yaml
context:
  max_tokens: 128000              # Model context window
  compact_threshold: 0.8          # Trigger micro-compact at 80%
  consolidate_threshold: 0.9      # Trigger consolidation at 90%
  preserve_recent_turns: 10       # Always keep last 10 turns
```

---

## 16. Session Management

### 16.1 Thread ID Format

```
{channel}_{chat_id}_{user_id}_s{counter}
```

Examples:
- `telegram_12345_67890_s0` — User 67890 in Telegram chat 12345, session 0
- `cli_local_user1_s3` — CLI user, 4th session

### 16.2 Automatic Resume

Sessions resume automatically from the last checkpoint. When a user sends a message:
1. Session manager resolves thread_id from channel + chat_id + user_id
2. Checkpointer loads the latest checkpoint for that thread_id
3. Agent continues from where it left off
4. No explicit `/resume` command needed

### 16.3 Session Reset

`/new` command increments the session counter, creating a fresh thread_id. Old session data remains in the checkpoint DB (queryable but not loaded).

### 16.4 Session Persistence

- SQLite checkpoint DB in `data/checkpoints.db` (Docker volume)
- Survives container restarts
- JSONL session logs in `workspace/sessions/` for audit trail
- Future: Postgres for multi-instance deployment

---

## 17. Plugin & Hook System

### 17.1 Our Plugin Format

Own format — not Claude Code compatible. Three plugin types:

**Command plugins** — Add slash commands:
```python
# plugins/my_plugin/commands.py
from langagent.plugins import command

@command("/mycommand", description="Does something useful")
async def my_command(args: str, context: CommandContext) -> str:
    return "Result"
```

**Hook plugins** — Lifecycle hooks:
```python
# plugins/my_plugin/hooks.py
from langagent.plugins import hook

@hook("pre_tool_use")
async def check_tool(tool_name: str, args: dict, context: HookContext) -> HookResult:
    if tool_name == "exec" and "rm" in args.get("command", ""):
        return HookResult(action="deny", reason="Dangerous command")
    return HookResult(action="allow")
```

**Agent plugins** — Define agent archetypes for swarm:
```python
# plugins/my_plugin/agents.py
from langagent.plugins import agent_archetype

@agent_archetype("security-reviewer")
def security_reviewer():
    return {
        "role": "evaluator",
        "tier": "advanced",
        "tools": ["read_file", "grep", "glob", "web_search"],
        "skills": ["review", "debug"],
        "system_prompt_addon": "Focus on OWASP top 10 vulnerabilities...",
    }
```

### 17.2 Hook Events

| Event | Timing | Can Veto |
|-------|--------|----------|
| `pre_tool_use` | Before any tool execution | Yes (deny the tool call) |
| `post_tool_use` | After tool returns | No (informational) |
| `pre_agent_spawn` | Before sub-agent creation | Yes |
| `post_agent_spawn` | After sub-agent starts | No |
| `agent_complete` | Sub-agent finished | No |
| `agent_failed` | Sub-agent failed | No |
| `pre_send` | Before sending message to channel | Yes (suppress message) |
| `session_start` | New session created | No |
| `session_end` | Session concluded | No |
| `dream_complete` | Dream process finished | No |
| `budget_warning` | Cost approaching budget limit | No |
| `budget_exceeded` | Cost exceeded budget | No |

### 17.3 Plugin Discovery

Plugins are Python packages in `workspace/plugins/` or installed via pip. Discovery:
1. Scan `workspace/plugins/` for directories with `__init__.py`
2. Import and register commands, hooks, agent archetypes
3. Hot-reload on file change (development mode)

---

## 18. MCP Support

### 18.1 Client (Connect to External MCP Servers)

Inherited from ciana-parrot. Supports:
- **Stdio transport** — spawn process, communicate via stdin/stdout
- **HTTP transport** — connect to remote MCP server
- **SSE transport** — streaming server-sent events

MCP tools are automatically wrapped as LangGraph-compatible tools.

### 18.2 Configuration

```yaml
mcp_servers:
  filesystem:
    transport: "stdio"
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/data"]
  github:
    transport: "stdio"
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-github"]
    env:
      GITHUB_TOKEN: "${GITHUB_TOKEN}"
```

### 18.3 Server (Expose Platform as MCP)

FastMCP server exposing platform capabilities to external agents:
- Memory read/write
- Scheduling
- Gateway bridge access
- Agent status
- Tool invocation

This enables other MCP-compatible tools to interact with LangAgent Platform.

---

## 19. Multi-User Architecture

### 19.1 Design

One agent instance serves multiple users with per-user isolation:

| Resource | Scope | Storage |
|----------|-------|---------|
| SOUL.md | Shared | `workspace/SOUL.md` |
| AGENT.md | Shared | `workspace/AGENT.md` |
| MEMORY.md | Shared | `workspace/MEMORY.md` |
| USER.md | Per-user | `workspace/users/{user_id}/USER.md` |
| Session checkpoint | Per-user per-chat | SQLite keyed by thread_id |
| Session logs | Per-user per-chat | `workspace/sessions/{thread_id}.jsonl` |
| Scheduled tasks | Per-user | Filtered by `owner_user_id` |
| Cost tracking | Per-user | Aggregated by user_id |
| Sub-agents | Per-user session | Scoped to the spawning session |

### 19.2 User ID Resolution

Each channel extracts user_id differently:
- Telegram: `update.effective_user.id`
- Discord: `message.author.id`
- Slack: `event.user`
- CLI: configured in config or `$USER`
- API: from auth token or `X-User-ID` header

### 19.3 Dream Process with Multiple Users

Dream runs per-user:
1. For each user_id with activity since last dream:
   - Read that user's history.jsonl
   - Read that user's USER.md
   - Edit USER.md with new learnings
2. For shared files (SOUL.md, MEMORY.md):
   - Aggregate all users' recent history
   - Edit shared files based on overall patterns

---

## 20. Web UI (Management Dashboard)

### 20.1 Design Philosophy

Two interaction modes, each optimized for its context:

| Mode | Interface | Best For |
|------|-----------|----------|
| **Conversational** | Telegram, Discord, Slack, CLI | Quick tasks, questions, on-the-go interaction, notifications |
| **Management** | Web UI dashboard | Swarm monitoring, agent config, task boards, cost analysis, memory editing |

The Web UI is **not** a chat replacement — it's a management console. Users chat via their preferred channel, then open the dashboard when they need visibility or control over complex operations.

### 20.2 Architecture

```
┌──────────────────────────────────────────────────┐
│                   WEB UI (React)                  │
│  Next.js / Vite │ TailwindCSS │ shadcn/ui        │
│                                                   │
│  ┌─────────┐ ┌──────────┐ ┌───────────────────┐  │
│  │  Chat   │ │  Swarm   │ │  Settings &       │  │
│  │  Panel  │ │  Board   │ │  Management       │  │
│  └────┬────┘ └────┬─────┘ └────────┬──────────┘  │
│       └───────────┴────────────────┘              │
│                    │                              │
│              WebSocket + REST                     │
└────────────────────┬─────────────────────────────┘
                     │
┌────────────────────▼─────────────────────────────┐
│         AGENT API (OpenAI-compatible + extensions) │
│  /v1/chat/completions (SSE)                       │
│  /v1/agents          (sub-agent management)       │
│  /v1/tasks           (scheduled tasks)            │
│  /v1/memory          (read/edit memory files)     │
│  /v1/config          (runtime configuration)      │
│  /v1/cost            (usage & cost data)          │
│  /ws                 (real-time stream events)    │
└───────────────────────────────────────────────────┘
```

The API server (already in spec as the OpenAI-compatible API channel) is extended with management endpoints. The Web UI is a static frontend that talks to this API.

### 20.3 Pages & Features

#### Chat Panel
- Real-time conversation with the agent (via WebSocket)
- Streaming token display
- Tool call visualization (expandable cards)
- Sub-agent activity feed (live progress)
- Approval dialogs rendered inline (approve/deny buttons)
- Session picker (switch between conversations)
- User selector (for multi-user setups)

#### Swarm Dashboard
- **Agent cards** — each sub-agent as a card showing: name, role, tier, status, current task, cost, health indicator
- **Task board** — Kanban-style: pending → in_progress → completed/failed. Drag to reassign.
- **Team view** — agents grouped by team, with harness phase indicator (plan → execute → verify → ship)
- **Live logs** — real-time stream of agent events (tool calls, messages, errors)
- **Cost chart** — per-agent and per-tier cost over time (line chart)
- **Git activity** — commits per agent worktree (simple list, not Gource)

#### Settings & Management
- **Memory editor** — view and edit SOUL.md, USER.md, MEMORY.md, AGENT.md with live preview
- **AGENT_REGISTRY.md** and **TEAM_PLAYBOOK.md** — view learned configurations
- **Skills browser** — installed skills with enable/disable toggles, requirements status
- **Plugin manager** — installed plugins with hook event list
- **MCP servers** — connection status, available tools per server
- **Gateway bridges** — status, recent calls, error log
- **Scheduled tasks** — list, create, edit, delete with cron preview
- **Configuration** — edit config.yaml sections (provider, tiers, channels, permissions)
- **Cost report** — per-user, per-tier, per-agent breakdown with date range filter
- **Dream log** — history of memory changes with Git diff view and restore button

### 20.4 Real-Time Updates

The Web UI subscribes to the same `StreamEvent` system defined in Section 6:

```
WebSocket connection: ws://localhost:8900/ws?token=...

→ Receives all StreamEvents in real-time:
  - token deltas (chat panel)
  - tool_call_start/end (tool visualization)
  - agent_spawn/progress/complete/failed (swarm dashboard)
  - cost_update (cost chart)
  - approval_request (inline dialog)
```

No polling. All updates are push-based via WebSocket.

### 20.5 Technology Stack

| Component | Technology | Rationale |
|-----------|-----------|-----------|
| Framework | Next.js or Vite + React | Fast, modern, good DX |
| Styling | TailwindCSS + shadcn/ui | Clean, consistent, fast to build |
| State | Zustand or TanStack Query | Lightweight, WebSocket-friendly |
| Charts | Recharts | Simple cost/usage visualization |
| Real-time | Native WebSocket | Already have the SSE/WS API |
| Markdown | react-markdown | For memory file preview |
| Code editor | Monaco (lightweight) | For editing YAML config and .md files |

### 20.6 API Extensions

The OpenAI-compatible API channel (Section 11) is extended with management endpoints:

```
# Chat (existing)
POST   /v1/chat/completions          # Send message, receive SSE stream
GET    /v1/models                     # List available models/tiers

# Sub-Agent Management (new)
GET    /v1/agents                     # List all active sub-agents
GET    /v1/agents/{id}                # Get agent details
POST   /v1/agents                     # Spawn agent (same as spawn_agent tool)
DELETE /v1/agents/{id}                # Recall agent
PATCH  /v1/agents/{id}                # Modify agent (tier, tools, skills)
GET    /v1/agents/{id}/logs           # Stream agent events

# Teams (new)
GET    /v1/teams                      # List active teams
POST   /v1/teams                      # Create team from template
DELETE /v1/teams/{id}                 # Dissolve team
GET    /v1/teams/{id}/board           # Get task board state

# Scheduled Tasks (new)
GET    /v1/tasks                      # List scheduled tasks
POST   /v1/tasks                      # Create task
DELETE /v1/tasks/{id}                 # Cancel task
GET    /v1/tasks/{id}/history         # Run history

# Memory (new)
GET    /v1/memory                     # List memory files
GET    /v1/memory/{filename}          # Read file content
PUT    /v1/memory/{filename}          # Update file content
GET    /v1/memory/dream/log           # Dream change history
POST   /v1/memory/dream/restore/{sha} # Restore to previous state

# Config (new)
GET    /v1/config                     # Get current config (redacted secrets)
PATCH  /v1/config                     # Update config sections

# Cost (new)
GET    /v1/cost                       # Cost summary
GET    /v1/cost/breakdown             # Per-user, per-tier, per-agent

# WebSocket (new)
WS     /ws                            # Real-time StreamEvent subscription
```

### 20.7 Authentication

Web UI authenticates via a static token (for personal use) or JWT (for multi-user):

```yaml
api:
  enabled: true
  host: "0.0.0.0"
  port: 8900
  auth:
    type: "token"                # "token" | "jwt"
    token: "${API_TOKEN}"        # For token auth
    jwt_secret: "${JWT_SECRET}"  # For JWT auth
```

### 20.8 Phase Delivery

| Phase | Deliverable |
|-------|-------------|
| Phase 0 | API channel (OpenAI-compatible, chat only) |
| Phase 1 | Management API extensions (agents, tasks, memory, cost endpoints) |
| Phase 2 | Web UI v1: Chat panel + Swarm dashboard + Settings |
| Phase 3 | Web UI v2: Polish, cost charts, Dream log viewer, team templates UI |

The Web UI does **not** block core platform development. Phases 0-1 are fully functional via chat channels. The Web UI lands in Phase 2 as a management add-on.

---

## 21. Observability & Cost Tracking

### 23.1 Tracing

```yaml
observability:
  langsmith:
    enabled: false
    api_key: "${LANGSMITH_API_KEY}"
    project: "langagent"
  langfuse:
    enabled: false
    public_key: "${LANGFUSE_PUBLIC_KEY}"
    secret_key: "${LANGFUSE_SECRET_KEY}"
    host: "https://cloud.langfuse.com"
```

LangGraph natively emits trace events. Both LangSmith and langfuse are supported as backends.

### 23.2 Cost Tracking

| Granularity | Tracked |
|-------------|---------|
| Per-call | Prompt tokens, completion tokens, cached tokens, cost |
| Per-tier | Aggregated by tier (lite/standard/advanced/expert) |
| Per-agent | Aggregated by sub-agent ID |
| Per-user | Aggregated by user_id |
| Per-session | Aggregated by thread_id |
| Per-team | Aggregated across all agents in a team |

Model-specific pricing loaded from config or defaults:
```yaml
cost:
  pricing:
    anthropic/claude-sonnet-4-6: { input: 3.0, output: 15.0 }   # per 1M tokens
    anthropic/claude-opus-4-6:   { input: 15.0, output: 75.0 }
    groq/llama-3.3-70b:          { input: 0.59, output: 0.79 }
```

### 23.3 Metrics

- Token usage per request
- Tool execution duration and success rate
- Sub-agent lifecycle events
- Channel message delivery latency
- Context compression frequency
- Dream process duration and changes

### 23.4 Session Logging

Every message logged to `workspace/sessions/{thread_id}.jsonl`:
```json
{"role": "user", "content": "...", "timestamp": "...", "channel": "telegram", "user_id": "123"}
{"role": "assistant", "content": "...", "timestamp": "...", "tier": "standard", "cost_cents": 0.5}
{"role": "tool", "name": "web_search", "result": "...", "timestamp": "...", "duration_ms": 450}
```

---

## 22. Configuration

### 23.1 Single YAML File

```yaml
# config.yaml — all settings in one file
agent:
  workspace: "./workspace"
  max_tool_iterations: 30
  max_parallel_tools: 10
  timezone: "Asia/Ho_Chi_Minh"

provider:
  name: "anthropic"
  model: "claude-sonnet-4-6"
  api_key: "${ANTHROPIC_API_KEY}"
  temperature: 0
  max_tokens: 8192

model_router:
  default_tier: "standard"
  tiers:
    lite: { provider: "groq", model: "llama-3.3-70b-versatile", api_key: "${GROQ_API_KEY}" }
    standard: { provider: "anthropic", model: "claude-sonnet-4-6", api_key: "${ANTHROPIC_API_KEY}" }
    advanced: { provider: "anthropic", model: "claude-opus-4-6", api_key: "${ANTHROPIC_API_KEY}" }
    expert: { provider: "anthropic", model: "claude-opus-4-6", api_key: "${ANTHROPIC_API_KEY}", extended_thinking: true }

channels:
  telegram: { enabled: true, token: "${TELEGRAM_BOT_TOKEN}", trigger: "@Agent", allowed_users: [] }
  discord: { enabled: false, token: "${DISCORD_BOT_TOKEN}" }
  slack: { enabled: false, bot_token: "${SLACK_BOT_TOKEN}", app_token: "${SLACK_APP_TOKEN}" }
  api: { enabled: true, host: "0.0.0.0", port: 8900 }
  cli: { enabled: false }

scheduler:
  poll_interval: 60

gateway:
  host: "host.docker.internal"
  port: 9842
  token: "${GATEWAY_TOKEN}"
  bridges: { ... }

memory:
  dream: { interval_hours: 2 }

context:
  max_tokens: 128000
  compact_threshold: 0.8
  consolidate_threshold: 0.9
  preserve_recent_turns: 10

mcp_servers: { ... }

skills:
  enabled: true
  directories: ["./skills/builtin", "./workspace/skills"]

permissions:
  mode: "default"

cost:
  budget_per_session: null
  budget_per_agent: 100
  on_budget_exceeded: "downgrade"
  pricing: { ... }

streaming:
  enabled: true
  token_batching_ms: 50
  show_thinking: false
  show_tool_details: true

observability:
  langsmith: { enabled: false }
  langfuse: { enabled: false }

logging:
  level: "INFO"

avatar:
  enabled: false
  tier: "lite"
```

### 23.2 Local Overrides

`config.local.yaml` (gitignored) overrides any key in `config.yaml`. Environment variables expand via `${VAR}` syntax. Pydantic v2 validates all config at startup.

---

## 23. Docker Deployment

### 23.1 Services

```yaml
# docker-compose.yml
services:
  agent-gateway:
    build: .
    ports: ["18790:18790"]
    volumes:
      - ./workspace:/app/workspace
      - ./config.yaml:/app/config.yaml:ro
      - ./data:/app/data
      - ./skills:/app/skills:ro
    env_file: .env
    restart: unless-stopped

  agent-api:
    build: .
    command: ["serve"]
    ports: ["8900:8900"]
    volumes:
      - ./workspace:/app/workspace
      - ./config.yaml:/app/config.yaml:ro
      - ./data:/app/data
    env_file: .env
    restart: unless-stopped

  web-ui:                          # Management dashboard (Phase 2+)
    build:
      context: ./web
    ports: ["3000:3000"]
    environment:
      - API_URL=http://agent-api:8900
    depends_on:
      - agent-api
    restart: unless-stopped
```

### 23.2 Dockerfile

- Base: `python:3.13-slim`
- System deps: curl, jq, ffmpeg, poppler-utils
- Non-root user (uid 1000)
- Health check: SQLite connectivity
- Multi-stage build for minimal image size

### 23.3 One-Command Install

```bash
curl -sSL https://raw.githubusercontent.com/.../install.sh | bash
```

The installer: checks prerequisites, clones repo, prompts for API keys, writes .env, builds Docker image, optionally starts gateway server.

---

## 24. Project Structure

```
lang-agent-platform/
├── src/
│   ├── core/
│   │   ├── graph.py              # Agent StateGraph definition
│   │   ├── state.py              # AgentState schema
│   │   ├── nodes.py              # Graph nodes (agent, tools, permission, monitor)
│   │   ├── router.py             # RoutingChatModel (inherited from ciana-parrot)
│   │   ├── streaming.py          # StreamEvent types and emission
│   │   └── compaction.py         # Context compression (micro-compact + consolidation)
│   │
│   ├── providers/
│   │   ├── base.py               # Provider interface
│   │   ├── anthropic.py          # Claude (native SDK)
│   │   ├── openai_compat.py      # OpenAI + compatible providers
│   │   ├── google.py             # Gemini
│   │   └── registry.py           # Auto-detection by model name
│   │
│   ├── tools/
│   │   ├── filesystem.py         # read, write, edit, glob, grep
│   │   ├── shell.py              # exec (sandboxed)
│   │   ├── web.py                # web_search, web_fetch
│   │   ├── scheduling.py         # schedule_task, list_tasks, cancel_task
│   │   ├── gateway.py            # host_execute
│   │   ├── model.py              # switch_model
│   │   ├── orchestration.py      # spawn_agent, subscribe_tool, monitor_agents, etc.
│   │   ├── notebook.py           # notebook_edit
│   │   └── registry.py           # Tool registration + MCP wrapping
│   │
│   ├── subagent/
│   │   ├── manager.py            # Sub-agent lifecycle (spawn, monitor, recall)
│   │   ├── worker.py             # Sub-agent graph builder
│   │   ├── health.py             # Heartbeat, timeout, iteration detection
│   │   ├── recovery.py           # Retry → escalate → reassign → abort chain
│   │   ├── store.py              # BaseStore namespaces and schemas
│   │   └── worktree.py           # Git worktree creation/merge/cleanup
│   │
│   ├── skills/
│   │   ├── loader.py             # Auto-discovery + progressive loading
│   │   ├── filter.py             # requires_env / requires_bridge
│   │   └── builtin/              # Built-in skills (.md files)
│   │
│   ├── memory/
│   │   ├── files.py              # SOUL/USER/MEMORY/AGENT/REGISTRY/PLAYBOOK
│   │   ├── consolidator.py       # Stage 1: conversation → history.jsonl
│   │   ├── dream.py              # Stage 2: history → knowledge edits
│   │   ├── search.py             # Memory search
│   │   └── context.py            # Context injection builder
│   │
│   ├── channels/
│   │   ├── base.py               # AbstractChannel
│   │   ├── manager.py            # Channel lifecycle + message bus
│   │   ├── telegram.py           # Inherited from ciana-parrot
│   │   ├── discord.py            # New
│   │   ├── slack.py              # New
│   │   ├── websocket.py          # New
│   │   ├── api.py                # OpenAI-compatible REST
│   │   └── cli.py                # Interactive CLI
│   │
│   ├── permissions/
│   │   ├── manager.py            # Permission modes
│   │   ├── rules.py              # Path + command rules
│   │   ├── sandbox.py            # bwrap + Docker sandbox
│   │   └── sensitive.py          # Credential path protection
│   │
│   ├── scheduler/
│   │   ├── engine.py             # Poll loop + execution
│   │   ├── store.py              # Task persistence
│   │   └── natural.py            # Natural language → cron (P2)
│   │
│   ├── gateway/
│   │   ├── client.py             # Async httpx client (in Docker)
│   │   └── avatar.py             # Emotion SSE relay
│   │
│   ├── plugins/
│   │   ├── loader.py             # Discovery + registration
│   │   ├── schema.py             # Command, Hook, AgentArchetype
│   │   └── hooks.py              # Hook event dispatch
│   │
│   ├── mcp/
│   │   ├── client.py             # Stdio + HTTP + SSE
│   │   ├── server.py             # FastMCP (expose platform)
│   │   └── wrapper.py            # MCP tool → LangGraph adapter
│   │
│   ├── observability/
│   │   ├── tracer.py             # LangSmith / langfuse
│   │   ├── cost.py               # Token counting + pricing
│   │   └── metrics.py            # General metrics
│   │
│   ├── config/
│   │   ├── schema.py             # Pydantic v2 models
│   │   └── loader.py             # YAML + env expansion + local override
│   │
│   ├── session/
│   │   ├── manager.py            # Thread ID resolution + routing
│   │   └── history.py            # JSONL logging
│   │
│   ├── commands/
│   │   ├── router.py             # Slash command registry
│   │   └── builtin.py            # /help, /new, /status, /dream, /stop, /spawn, etc.
│   │
│   └── main.py                   # Entry point
│
├── gateway/                      # Host-side gateway (standalone)
│   └── server.py
│
├── workspace/                    # Agent workspace (Docker volume)
│   ├── SOUL.md
│   ├── USER.md                   # Default (single-user fallback)
│   ├── MEMORY.md
│   ├── AGENT.md
│   ├── AGENT_REGISTRY.md
│   ├── TEAM_PLAYBOOK.md
│   ├── users/                    # Per-user data
│   ├── memory/
│   ├── skills/
│   ├── sessions/
│   ├── plugins/
│   └── templates/
│
├── skills/                       # Built-in skills
│   └── (17 skills)
│
├── templates/                    # Team launch templates (TOML)
│   ├── software-dev.toml
│   ├── code-review.toml
│   ├── research.toml
│   └── hedge-fund.toml
│
├── web/                          # Web UI (management dashboard)
│   ├── src/
│   │   ├── app/                  # Next.js pages / Vite routes
│   │   │   ├── chat/             # Chat panel
│   │   │   ├── swarm/            # Swarm dashboard + task board
│   │   │   ├── settings/         # Memory editor, skills, plugins, config
│   │   │   └── cost/             # Cost reports
│   │   ├── components/           # Shared UI components
│   │   ├── hooks/                # WebSocket subscription, API calls
│   │   └── lib/                  # API client, types, utils
│   ├── package.json
│   └── tailwind.config.ts
│
├── config.yaml
├── config.local.yaml
├── docker-compose.yml
├── Dockerfile
├── install.sh
├── pyproject.toml
└── tests/
```

---

## 25. Phased Roadmap

### Phase 0 — Fork & Foundation (Week 1)

**Goal:** Fork ciana-parrot, rebrand, verify everything works.

| Deliverable | Source |
|-------------|--------|
| Fork ciana-parrot | Direct |
| Rename to LangAgent Platform | New |
| Verify: LangGraph agent loop works | Inherited |
| Verify: Telegram channel works | Inherited |
| Verify: RoutingChatModel (multi-tier) works | Inherited |
| Verify: Host gateway works | Inherited |
| Verify: Skills auto-discovery works | Inherited |
| Verify: MCP support works | Inherited |
| Verify: Scheduling works | Inherited |
| Verify: Memory files load | Inherited |
| Verify: Docker deployment works | Inherited |
| Add CLI channel | New (simple, Rich TUI) |
| Add OpenAI-compatible API channel | New |

**Exit criteria:** Platform runs under new name, all inherited features work, CLI and API channels functional.

### Phase 1 — Core Extensions (Weeks 2-4)

**Goal:** Add the major missing features that differentiate us.

| Deliverable | Inspiration |
|-------------|-------------|
| Dream memory (2-stage + Git) | nanobot |
| Context compression (micro-compact + consolidation) | nanobot/OpenHarness |
| Permission system (modes + rules + interrupt()) | OpenHarness |
| Plugin/hook system (own format) | OpenHarness/ClawTeam |
| Sub-agent system (asyncio + BaseStore + health) | New (LangGraph-native) |
| Orchestration tools (spawn, subscribe, monitor, recall) | New |
| Streaming event lifecycle | New |
| Per-user session isolation (multi-user) | New |
| Cost tracking (per-tier, per-agent, per-user) | ClawTeam/OpenHarness |
| Additional providers (OpenAI, Gemini, Groq, Ollama) | nanobot |
| Management API extensions (/v1/agents, /v1/tasks, /v1/memory, /v1/cost) | New |
| WebSocket event stream endpoint (/ws) | New |

**Exit criteria:** Agent can spawn sub-agents, manage them via tools, dream to consolidate memory, enforce permissions with user approval, track costs per user. Management API operational for future Web UI.

### Phase 2 — Swarm & Channels (Weeks 5-7)

**Goal:** Full swarm coordination + more channels.

| Deliverable | Inspiration |
|-------------|-------------|
| Team templates (TOML) | ClawTeam |
| Harness phases (plan → execute → verify → ship) | ClawTeam |
| Git worktree isolation per sub-agent | ClawTeam |
| Sub-agent failure recovery (retry → escalate → reassign → abort) | New |
| Budget enforcement (per-agent, per-session) | New |
| AGENT_REGISTRY.md + TEAM_PLAYBOOK.md | New |
| Discord channel | nanobot |
| Slack channel | nanobot |
| WebSocket channel | nanobot |
| Voice transcription (inherited but verify) | ciana-parrot |
| **Web UI v1** — Chat panel + Swarm dashboard + Settings | New |
| Management API extensions (agents, tasks, memory, cost) | New |

**Exit criteria:** Launch a 5-agent software dev team from template, complete a coding task autonomously. Three new channels working. Web UI shows swarm activity in real-time.

### Phase 3 — Polish & Scale (Weeks 8+)

| Deliverable | Notes |
|-------------|-------|
| **Web UI v2** — Cost charts, Dream log viewer, team templates UI | New |
| Feishu, Matrix, WeChat channels | From nanobot patterns |
| Email channel | IMAP/SMTP |
| WhatsApp bridge | Node.js |
| Skill marketplace (remote discovery) | ClawHub |
| Natural language scheduling | "Every weekday at 9am" |
| FastMCP server (expose platform as MCP) | New |
| Postgres checkpointer | Multi-instance production |
| Avatar emotion system | ciana-parrot |
| Performance optimization | Connection pooling, caching |
| Advanced sandbox (bwrap) | nanobot |

---

## 26. Gap Analysis Addendum — 35 Features from Reference Repos

*Added 2026-04-15 after deep-dive gap analysis across all 5 reference repos (ClawTeam, OpenHarness, ciana-parrot, nanobot, claw-code). Each gap was found by reading actual source code, not just READMEs.*

---

### 26.1 Sub-Agent Lifecycle & Recovery

#### GAP-1: Context Recovery for Agent Re-Spawns (ClawTeam)

When a sub-agent crashes and our recovery chain (AD-12) retries it, the respawned agent starts with zero context. ClawTeam's `ContextRecovery` class builds a 5-layer recovery prompt scoped by role:

1. **Iteration context** — what iteration the agent was on
2. **Task progress** — which tasks were complete, which in-flight
3. **Git summary** — recent commits from the agent's branch
4. **Artifacts** — files/outputs the agent produced before crashing
5. **Teammate status** — what other agents are doing (for coordination)

Executors see only their own tasks; evaluators see all contracts.

**Spec addition to Section 8.4 (Recovery):**
```python
async def build_recovery_context(agent_id: str, role: str, store: BaseStore) -> str:
    """Build role-scoped recovery prompt for a re-spawned agent."""
    ctx = []
    ctx.append(f"You are resuming after a failure. Your role: {role}")
    ctx.append(f"Task progress: {await get_task_status(agent_id, store)}")
    ctx.append(f"Your recent work: {await get_git_log(agent_id)}")
    ctx.append(f"Artifacts produced: {await get_artifacts(agent_id, store)}")
    if role != "executor":
        ctx.append(f"Team status: {await get_all_agents_status(store)}")
    return "\n".join(ctx)
```

#### GAP-2: Worker State Machine (claw-code)

Our sub-agent lifecycle needs explicit states for health monitoring to work. Adopted from claw-code's `WorkerRegistry`:

```
SPAWNING → READY → RUNNING → FINISHED
    │         │        │
    │         │        ├→ BLOCKED (waiting on approval/resource)
    │         │        │
    │         │        └→ FAILED
    │         │
    │         └→ (trust prompt auto-resolution if needed)
    │
    └→ FAILED (spawn error)
```

**State transitions emit events** via BaseStore for the master to observe.

**Spec addition to Section 8:**
```python
class SubAgentState(str, Enum):
    SPAWNING = "spawning"           # asyncio.Task created, graph compiling
    READY = "ready"                 # Graph compiled, awaiting first invocation
    RUNNING = "running"             # Processing messages/tools
    BLOCKED = "blocked"             # Waiting on permission approval or resource
    FINISHED = "finished"           # Completed successfully
    FAILED = "failed"              # Unrecoverable error
```

#### GAP-3: Graceful Shutdown Protocol (ClawTeam)

`recall_agent` needs a handshake, not just `task.cancel()`:

1. Master writes `{"action": "shutdown"}` to agent's BaseStore directive
2. Agent sees directive, finishes current tool call, writes final result
3. Agent writes `{"status": "shutting_down", "partial_results": ...}` to BaseStore
4. Master reads partial results, merges git worktree if applicable
5. Master cancels asyncio.Task only after agent acknowledges or timeout (30s)

This prevents mid-flight interrupts that corrupt files or lose work.

#### GAP-4: Dead Agent Detection with Task Rebalancing (ClawTeam)

When a sub-agent dies, its assigned tasks should be reassigned:

1. Health monitor detects stale heartbeat (>120s)
2. Mark agent as FAILED
3. Collect unfinished tasks from the dead agent's BaseStore
4. Reassign to another agent with compatible role/skills
5. If no compatible agent exists, spawn a replacement

This is distinct from our retry chain (which retries the same agent). Rebalancing redistributes work.

---

### 26.2 Harness Phase System

#### GAP-5: Phase Gates (ClawTeam)

Phases without gates are just labels. Each phase transition must pass through gates:

```python
class PhaseGate(ABC):
    @abstractmethod
    async def check(self, context: HarnessContext) -> GateResult:
        """Return (passed: bool, reason: str)"""

class ArtifactRequiredGate(PhaseGate):
    """Blocks advance until specified artifacts exist in BaseStore."""
    required_artifacts: list[str]

class AllTasksCompleteGate(PhaseGate):
    """Blocks until all tasks in the task board are completed."""

class HumanApprovalGate(PhaseGate):
    """Blocks until user approves via channel (uses LangGraph interrupt())."""

class CustomGate(PhaseGate):
    """Plugin-provided gate with custom logic."""
```

**Phase transitions:**
```
discuss ──[HumanApprovalGate]──→ plan
plan ──[ArtifactRequiredGate("plan.md")]──→ execute
execute ──[AllTasksCompleteGate]──→ verify
verify ──[ArtifactRequiredGate("test_report.md")]──→ ship
```

Gates are extensible via plugins (`contribute_gates()` hook).

#### GAP-6: Git Conflict Detection Between Agent Worktrees (ClawTeam)

When multiple agents edit code in separate worktrees, detect overlaps before merge:

```python
async def detect_conflicts(agent_worktrees: dict[str, str]) -> list[Conflict]:
    """Analyze git diffs across all agent worktrees for overlapping changes."""
    conflicts = []
    for (agent_a, path_a), (agent_b, path_b) in combinations(agent_worktrees.items(), 2):
        diff_a = git_diff(path_a, base_branch)
        diff_b = git_diff(path_b, base_branch)
        overlapping_files = set(diff_a.files) & set(diff_b.files)
        for file in overlapping_files:
            hunks_a = diff_a.hunks[file]
            hunks_b = diff_b.hunks[file]
            if lines_overlap(hunks_a, hunks_b):
                severity = "high"  # Same lines modified
            else:
                severity = "medium"  # Same file, different lines
            conflicts.append(Conflict(file, agent_a, agent_b, severity))
    return conflicts
```

Run before `recall_agent` merges a worktree. On high-severity conflicts, notify the master agent to resolve.

#### GAP-7: Green-Level Contracts (claw-code)

When the verify phase runs tests, distinguish between test levels:

| Level | Meaning | Merge policy |
|-------|---------|-------------|
| `targeted` | Only tests related to changed code pass | Not merge-ready |
| `package` | All tests in affected package pass | Conditional merge |
| `workspace` | All tests in workspace pass | Merge-ready |
| `merge_ready` | All tests + linting + type-checking pass | Ship-ready |

The verify agent must specify which green level was achieved. The ship gate requires `merge_ready`.

---

### 26.3 Memory & Context

#### GAP-8: Dream Phase 1/Phase 2 Separation (nanobot)

Dream is not one LLM call — it's two distinct phases with different capabilities:

**Phase 1 — Analysis (no tools):**
- Plain LLM call analyzing new history entries
- Produces a text summary of what changed and what to remember
- Max batch: 20 history entries per run
- No tools available — pure reflection

**Phase 2 — Editing (restricted tools):**
- Uses `AgentRunner` with only 3 tools: `read_file`, `edit_file`, `write_file`
- Makes surgical edits to SOUL.md, USER.md, MEMORY.md
- Max iterations: 10 tool calls
- No web search, no exec, no gateway — prevents side effects during reflection

#### GAP-9: Task Focus State Tracking (OpenHarness)

Maintain interim state across turns that survives compaction:

```python
@dataclass
class TaskFocusState:
    goal: str = ""                          # Current user goal (max 240 chars)
    recent_goals: list[str] = field(default_factory=list)  # Last 5 goals
    active_artifacts: list[str] = field(default_factory=list)  # Files being worked on
    verified_state: dict = field(default_factory=dict)  # What's been tested/verified
    next_step: str = ""                     # Agent's planned next action
```

Updated after each turn, carried across compaction as structured metadata (not in message history). Injected into system prompt so agent maintains continuity even after context compression.

#### GAP-10: Fact Extraction Engine (OpenHarness)

Auto-discover environment facts from conversation and inject into USER.md:

```python
FACT_PATTERNS = {
    "ssh_host": r"ssh\s+[\w@.-]+",
    "ip_address": r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
    "api_endpoint": r"https?://[\w.-]+(?:/[\w.-]*)*",
    "conda_env": r"conda activate (\w+)",
    "python_version": r"python(\d+\.\d+)",
    "git_remote": r"git@[\w.-]+:[\w/.-]+\.git",
    "env_var": r"export (\w+)=",
    "data_path": r"(?:/[\w.-]+){3,}",
}
```

Each match gets a confidence score. Deduplicated by key. Merged into USER.md during Dream process. Means the agent learns about the user's environment automatically.

#### GAP-11: Provider-Aware Token Counting (nanobot)

Replace the "4 chars per token" heuristic with actual provider tokenizers:

```python
async def estimate_tokens(messages: list, provider: str) -> int:
    """Use provider's actual tokenizer when available, fall back to heuristic."""
    if provider == "anthropic":
        return await anthropic_client.count_tokens(messages)  # Exact
    elif provider == "openai":
        import tiktoken
        enc = tiktoken.encoding_for_model(model)
        return sum(len(enc.encode(m.content)) for m in messages)
    else:
        return sum(len(m.content) for m in messages) // 4  # Fallback heuristic
```

Use exact counting for threshold decisions (compaction triggers, budget enforcement). Use heuristic only for display/estimation.

#### GAP-12: Prompt Cache Optimization (nanobot)

Optimize tool ordering for Anthropic prompt caching:

```python
def get_tool_definitions(tools: list[BaseTool]) -> list[dict]:
    """Sort tools for cache-friendly ordering."""
    builtin = sorted([t for t in tools if t.is_builtin], key=lambda t: t.name)
    mcp = sorted([t for t in tools if t.is_mcp], key=lambda t: t.name)
    dynamic = sorted([t for t in tools if t.is_dynamic], key=lambda t: t.name)
    return [t.schema() for t in builtin + mcp + dynamic]
```

Stable tool ordering means the tool definitions prefix is the same across requests, maximizing cache hits. Track cache metrics:
- `cached_tokens` per request
- Cache hit rate per session
- Break-even analysis (is caching saving money?)

---

### 26.4 Agent Loop & Error Recovery

#### GAP-13: Runner-Level Error Recovery (nanobot)

Beyond provider retries (Section 5.3), the agent runner needs its own recovery layer:

| Recovery | Trigger | Action | Limit |
|----------|---------|--------|-------|
| Empty response | LLM returns blank/only-thinking | Retry with nudge message | 2 retries |
| Length recovery | Response suspiciously short | Inject "please continue" | 3 recoveries |
| Injection cycling | Tool result injection fails | Re-inject with simplified result | 3 per turn, 5 total |
| Tool result truncation | Tool output exceeds limit | Truncate with "[result truncated]" | 1024-byte safety buffer |
| Microcompact | Tool results bloating context | Summarize old tool results, keep recent 10 | On demand |

```python
_MAX_EMPTY_RETRIES = 2
_MAX_LENGTH_RECOVERIES = 3
_MAX_INJECTIONS_PER_TURN = 3
_MAX_INJECTION_CYCLES = 5
_MICROCOMPACT_KEEP_RECENT = 10
```

#### GAP-14: Reactive Compaction (OpenHarness)

When a prompt-too-long error occurs (not caught by threshold-based compaction):

1. Catch `PromptTooLongError` or HTTP 400 with "prompt is too long"
2. Trigger emergency compaction (more aggressive than threshold-based)
3. Retry the same request after compaction
4. If compaction fails 3 times consecutively, abort with error

```python
_MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES = 3

async def submit_with_reactive_compact(messages, ...):
    for attempt in range(MAX_RETRIES):
        try:
            return await llm.ainvoke(messages)
        except PromptTooLongError:
            if compact_failures >= _MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES:
                raise
            messages = await emergency_compact(messages)
            compact_failures += 1
```

#### GAP-15: File State Tracking (nanobot)

Track read/edit history to prevent common agent mistakes:

```python
@dataclass
class ReadState:
    mtime: float          # File modification time when last read
    content_hash: str     # SHA256 of content when read
    offset: int           # Line offset of read
    limit: int            # Lines read

class FileStateTracker:
    _states: dict[str, ReadState] = {}
    
    def record_read(self, path: str, content: str) -> None: ...
    
    def check_before_edit(self, path: str) -> str | None:
        """Returns warning if file not read or stale, None if OK."""
        if path not in self._states:
            return f"Warning: {path} has not been read yet. Read before editing."
        state = self._states[path]
        current_mtime = os.path.getmtime(path)
        if current_mtime != state.mtime:
            current_hash = hash_file(path)
            if current_hash != state.content_hash:
                return f"Warning: {path} was modified since last read. Re-read before editing."
        return None  # Safe to edit
```

Inject warnings into tool results so the LLM knows to re-read.

#### GAP-16: Recovery Recipes (claw-code)

Encode known failure-to-recovery mappings for smarter auto-recovery:

```python
RECOVERY_RECIPES = {
    "stale_branch": {
        "detection": lambda e: "merge conflict" in str(e) or "behind main" in str(e),
        "recovery": "git fetch origin && git rebase origin/main",
        "escalation": "reassign to fresh worktree",
    },
    "mcp_startup": {
        "detection": lambda e: "MCP server" in str(e) and "connection refused" in str(e),
        "recovery": "restart MCP server, retry tool call",
        "escalation": "disable MCP server, continue without it",
    },
    "compile_error": {
        "detection": lambda e: "SyntaxError" in str(e) or "ModuleNotFoundError" in str(e),
        "recovery": "inject error context, ask agent to fix",
        "escalation": "escalate to higher tier",
    },
    "test_failure": {
        "detection": lambda e: "FAILED" in str(e) and "test" in str(e).lower(),
        "recovery": "inject test output, ask agent to fix",
        "escalation": "escalate to higher tier with full test context",
    },
}
```

Match failure to recipe before falling through to the generic retry→escalate→reassign→abort chain.

---

### 26.5 Permission & Security

#### GAP-17: Bash Validation Submodules (claw-code)

Replace simple command allowlist with semantic command analysis:

```python
class BashValidator:
    """Multi-stage validation for shell commands."""
    
    validators = [
        DestructiveCommandDetector(),   # rm -rf, git reset --hard, DROP TABLE
        ReadOnlyGatekeeper(),           # In plan mode, only allow read-only commands
        SedValidator(),                 # Validate sed expressions for safety
        PathValidator(),                # Check paths are within workspace
        PipeChainAnalyzer(),            # Analyze piped commands (curl | bash)
        EnvironmentModifier(),          # Detect export, unset, source
        NetworkAccessDetector(),        # Detect curl, wget, ssh
        PackageManagerDetector(),       # Detect pip install, npm install
    ]
    
    def validate(self, command: str, mode: PermissionMode) -> ValidationResult:
        """Run all validators, return aggregate result."""
        for v in self.validators:
            result = v.check(command, mode)
            if result.action == "deny":
                return result
            if result.action == "escalate":
                return result  # Needs user approval
        return ValidationResult(action="allow")
```

Each validator classifies the command semantically, not just by keyword matching.

#### GAP-18: Workspace-Root Binding (claw-code)

Sessions store explicit workspace root to prevent cross-CWD contamination:

```python
@dataclass  
class SessionMetadata:
    session_id: str
    thread_id: str
    workspace_root: str  # Absolute path, validated at session creation
    created_at: float
    
    def validate_path(self, path: str) -> bool:
        """Ensure path is within this session's workspace."""
        return os.path.realpath(path).startswith(self.workspace_root)
```

Prevents phantom bugs when multiple agents/sessions operate on different directories.

---

### 26.6 MCP & Tool Integration

#### GAP-19: Degraded-Mode MCP Reporting (claw-code)

MCP startup should report partial success instead of all-or-nothing:

```python
@dataclass
class McpStartupReport:
    total_servers: int
    ready: list[str]           # Servers that initialized successfully
    failed: list[tuple[str, str]]  # (server_name, error_message)
    degraded: bool             # True if some servers failed
    
    @property
    def summary(self) -> str:
        if not self.failed:
            return f"All {self.total_servers} MCP servers ready"
        return (f"{len(self.ready)}/{self.total_servers} MCP servers ready. "
                f"Failed: {', '.join(n for n, _ in self.failed)}")
```

Agent is informed which MCP tools are unavailable so it can work around missing servers.

#### GAP-20: MCP Schema Normalization (nanobot)

MCP tools return JSON Schema that may not be OpenAI-compatible. Normalize:

```python
def normalize_mcp_schema(schema: dict) -> dict:
    """Normalize MCP JSON Schema for LangChain/OpenAI compatibility."""
    # Handle nullable unions: {"anyOf": [{"type": "string"}, {"type": "null"}]}
    if "anyOf" in schema:
        non_null = [s for s in schema["anyOf"] if s.get("type") != "null"]
        if len(non_null) == 1:
            return {**non_null[0], "nullable": True}
    # Recursively normalize properties
    if "properties" in schema:
        schema["properties"] = {
            k: normalize_mcp_schema(v) for k, v in schema["properties"].items()
        }
    return schema
```

Tool naming convention: `mcp_{server_name}_{tool_name}` to avoid collisions.

#### GAP-21: LSP Integration (OpenHarness)

Language Server Protocol for code intelligence — enables go-to-definition, hover, completions:

```python
@tool
async def lsp(
    action: str,       # "symbols" | "references" | "definition" | "hover" | "diagnostics"
    file: str,
    line: int = 0,
    character: int = 0,
    query: str = "",
) -> str:
    """Query Language Server for code intelligence."""
```

Phase: P3 (nice-to-have for code-heavy swarm tasks). Requires LSP servers installed in Docker image.

---

### 26.7 Scheduling & Background Tasks

#### GAP-22: Heartbeat Service (nanobot)

Distinct from sub-agent health monitoring. A periodic "should I wake up?" decision:

```python
class HeartbeatService:
    """Periodic service that wakes the agent to check on tasks."""
    interval: int = 1800  # 30 minutes default
    
    async def tick(self):
        # Phase 1: Decision (lightweight LLM call with virtual tool)
        decision = await llm.ainvoke(
            system=HEARTBEAT_PROMPT,  # Loaded from HEARTBEAT.md
            tools=[heartbeat_virtual_tool],  # Returns {"action": "skip"|"run", "tasks": "..."}
        )
        if decision.action == "skip":
            return
        
        # Phase 2: Execution (full agent invocation)
        await agent.ainvoke({"messages": [{"role": "user", "content": decision.tasks}]})
```

Uses a virtual tool (not a real tool — just structured output) to decide whether to act. Prevents wasting tokens on "nothing to do" heartbeats.

#### GAP-23: Notification Evaluator (nanobot)

When a scheduled task or heartbeat produces a result, decide whether to deliver it:

```python
async def evaluate_notification(task_result: str, user_context: str) -> bool:
    """LLM decides whether this result is worth notifying the user about."""
    response = await lite_llm.ainvoke(
        system="You are a notification filter. Decide if this result is important enough to notify the user.",
        tools=[evaluate_tool],  # Returns {"should_notify": bool, "reason": "..."}
        messages=[{"role": "user", "content": f"Task result: {task_result}\nUser context: {user_context}"}],
    )
    return response.should_notify  # Default: True on error
```

Uses lite tier to minimize cost. Prevents spam from routine cron jobs that find nothing interesting.

#### GAP-24: Cron Job History & State Machine (nanobot)

Enrich the scheduler with execution history and job states:

```python
@dataclass
class CronJob:
    id: str
    schedule: str                    # Cron expression
    prompt: str                      # What to execute
    state: CronJobState              # enabled | disabled | paused
    timezone: str                    # IANA timezone
    run_history: list[CronRun]       # Last 20 runs
    created_at: str
    last_run_at: str | None
    run_count: int

@dataclass
class CronRun:
    started_at: str
    finished_at: str
    duration_ms: int
    status: str                      # "success" | "failure" | "timeout"
    result_summary: str              # Truncated output
```

History enables: "Show me the last 5 runs of my portfolio check" and debugging failed scheduled tasks.

#### GAP-25: Auto-Compact for Idle Sessions (nanobot)

Sessions that haven't been used for a configurable TTL get auto-compacted:

```yaml
session:
  ttl_minutes: 120  # Auto-compact after 2 hours idle (0 = disabled)
```

Keeps recent 8 messages, archives the rest to history.jsonl. Prevents unbounded memory growth from abandoned sessions.

---

### 26.8 Streaming & Communication

#### GAP-26: Message Throttling & Aggregation (ClawTeam)

Prevent noisy sub-agents from flooding the master:

```python
class MessageThrottler:
    """Per-source/target pair throttling with priority support."""
    default_window: float = 30.0  # seconds
    
    priorities = {"urgent": 0, "high": 5, "medium": 15, "low": 30}  # min interval per priority
    
    async def should_deliver(self, source: str, target: str, priority: str) -> bool:
        key = f"{source}→{target}"
        min_interval = self.priorities.get(priority, self.default_window)
        elapsed = time.time() - self._last_delivery.get(key, 0)
        if elapsed >= min_interval:
            self._last_delivery[key] = time.time()
            return True
        # Buffer the message for batch delivery later
        self._pending[key].append(message)
        return False
```

Urgent messages bypass throttling. Low-priority messages are batched and delivered periodically.

#### GAP-27: Thinking/Reasoning Content Storage (nanobot)

Store structured thinking content from models that support it:

```python
@dataclass
class AgentResponse:
    content: str                                # Final text response
    thinking_blocks: list[dict] | None = None   # Anthropic extended thinking
    reasoning_content: str | None = None        # DeepSeek/Kimi/MiMo reasoning
    tool_calls: list[ToolCall] = field(default_factory=list)
```

Thinking content is:
- Stored in checkpoints for debugging
- Optionally rendered to user (controlled by `streaming.show_thinking` config)
- Excluded from context for next turn (unless model expects it back)

#### GAP-28: Unified Session Mode (nanobot)

One conversation shared across all channels for single-user power users:

```yaml
session:
  unified: false  # When true, all channels share one session
```

When enabled, thread_id is always `unified:default` regardless of channel. User types in Telegram, continues on CLI, checks status via API — all in the same conversation.

---

### 26.9 Plugin & Hook System

#### GAP-29: Hook Execution Backends (OpenHarness)

Hooks should support multiple execution backends, not just Python decorators:

| Backend | Format | Use Case |
|---------|--------|----------|
| **Python** | `@hook("pre_tool_use")` decorator | In-process plugins |
| **Shell** | Shell command with env vars (`HOOK_EVENT`, `HOOK_PAYLOAD`) | External scripts |
| **HTTP** | POST to webhook URL with JSON payload | External services (Slack, PagerDuty) |
| **LLM** | LLM-driven hook that reasons about the event | Adaptive behavior |

Shell hooks receive event data via `LANGAGENT_HOOK_EVENT` and `LANGAGENT_HOOK_PAYLOAD` environment variables. Return code 0 = allow, 1 = deny.

#### GAP-30: Hook Error Isolation (nanobot)

Composite hook execution with error isolation:

```python
class CompositeHook:
    hooks: list[AgentHook]
    
    async def before_iteration(self, state):
        for hook in self.hooks:
            try:
                await hook.before_iteration(state)
            except Exception as e:
                logger.error(f"Hook {hook.__class__.__name__} failed: {e}")
                # Continue — don't let one broken hook crash the agent
    
    async def finalize_content(self, content: str) -> str:
        # Sequential, NO error isolation — bugs in finalizers should surface
        for hook in self.hooks:
            content = await hook.finalize_content(content)
        return content
```

Error isolation for side-effect hooks (before/after). No isolation for content-transforming hooks (finalize).

#### GAP-31: Plugin Manifest Schema (OpenHarness)

Define the concrete plugin manifest format:

```json
{
  "name": "my-plugin",
  "version": "1.0.0",
  "description": "What this plugin does",
  "enabled_by_default": true,
  "skills_dir": "./skills",
  "hooks_file": "./hooks.py",
  "commands": {
    "mycommand": {
      "description": "Does something",
      "handler": "commands.my_handler",
      "remote_invocable": false
    }
  },
  "agents": {
    "security-reviewer": {
      "role": "evaluator",
      "tier": "advanced",
      "tools": ["read_file", "grep", "glob"],
      "system_prompt_addon": "Focus on security..."
    }
  },
  "mcp_servers": {}
}
```

Discovery paths: `workspace/plugins/*/plugin.json` and `~/.langagent/plugins/*/plugin.json`.

---

### 26.10 Git & Code Quality

#### GAP-32: Stale-Branch Detection (claw-code)

Before running tests in the verify phase, check branch freshness:

```python
async def check_branch_freshness(worktree_path: str, base_branch: str = "main") -> BranchFreshness:
    """Detect if branch is behind main."""
    behind_count = git_rev_list_count(f"{base_branch}..HEAD", cwd=worktree_path)
    ahead_count = git_rev_list_count(f"HEAD..{base_branch}", cwd=worktree_path)
    
    if behind_count > 0:
        return BranchFreshness(
            stale=True,
            behind=behind_count,
            action="rebase"  # or "merge-forward" or "skip"
        )
    return BranchFreshness(stale=False)
```

Prevents false-positive test failures caused by testing against a stale branch.

---

### 26.11 Testing & Observability

#### GAP-33: Deterministic Mock Service (claw-code)

Built-in mock LLM service for E2E testing without API keys:

```python
class MockLLMService:
    """Anthropic-compatible mock for testing."""
    scenarios: dict[str, list[MockResponse]]
    
    async def handle_request(self, request):
        scenario = self.match_scenario(request)
        return scenario.next_response()
```

Enables:
- CI/CD without API keys
- Deterministic test scenarios (same input → same output)
- Edge case testing (token limits, error responses, tool call failures)
- Coverage of all streaming event types

#### GAP-34: Agent Color Assignment (OpenHarness)

Visual differentiation for swarm dashboard and logs:

```python
AGENT_COLORS = [
    "#FF6B6B",  # Red
    "#4ECDC4",  # Teal
    "#45B7D1",  # Blue
    "#96CEB4",  # Green
    "#FFEAA7",  # Yellow
    "#DDA0DD",  # Plum
    "#98D8C8",  # Mint
    "#F7DC6F",  # Gold
    "#BB8FCE",  # Purple
    "#85C1E9",  # Sky
]

def assign_color(agent_index: int) -> str:
    return AGENT_COLORS[agent_index % len(AGENT_COLORS)]
```

Colors assigned at spawn time, stored in agent metadata, used in:
- Web UI agent cards
- Terminal logs (ANSI colors)
- Git commit messages (optional)

---

### 26.12 Deployment & Infrastructure

#### GAP-35: Docker Sandbox for Tool Execution (OpenHarness)

Separate from deployment Docker — run dangerous tools in isolated containers:

```python
class DockerSandboxSession:
    """Run tool execution in a sandboxed Docker container."""
    
    async def execute(self, command: str, workspace: str) -> str:
        container = await docker.run(
            image=self.sandbox_image,
            command=command,
            volumes={workspace: {"bind": "/workspace", "mode": "rw"}},
            network_mode="none",          # No network access
            mem_limit="512m",             # Memory limit
            cpu_quota=100000,             # 1 CPU
            read_only=True,               # Read-only root filesystem
            tmpfs={"/tmp": "size=100m"},  # Writable temp
        )
        return container.output
```

Phase: P3. For untrusted code execution (user-uploaded scripts, npm install, etc.).

---

### 26.13 Summary — All 35 Gaps by Priority

| Priority | Gap # | Feature | Source |
|----------|-------|---------|--------|
| CRITICAL | 1 | Context recovery for re-spawns | ClawTeam |
| CRITICAL | 2 | Worker state machine | claw-code |
| CRITICAL | 5 | Phase gates | ClawTeam |
| CRITICAL | 8 | Dream Phase 1/2 separation | nanobot |
| CRITICAL | 13 | Runner-level error recovery | nanobot |
| CRITICAL | 14 | Reactive compaction | OpenHarness |
| CRITICAL | 6 | Git conflict detection | ClawTeam |
| HIGH | 9 | Task focus state tracking | OpenHarness |
| HIGH | 10 | Fact extraction engine | OpenHarness |
| HIGH | 16 | Recovery recipes | claw-code |
| HIGH | 17 | Bash validation submodules | claw-code |
| HIGH | 15 | File state tracking | nanobot |
| HIGH | 22 | Heartbeat service | nanobot |
| HIGH | 23 | Notification evaluator | nanobot |
| HIGH | 3 | Graceful shutdown protocol | ClawTeam |
| HIGH | 26 | Message throttling | ClawTeam |
| HIGH | 24 | Full-team snapshots | ClawTeam |
| HIGH | 11 | Provider-aware token counting | nanobot |
| HIGH | 12 | Prompt cache optimization | nanobot |
| MEDIUM | 29 | Hook execution backends | OpenHarness |
| MEDIUM | 31 | Plugin manifest schema | OpenHarness |
| MEDIUM | 35 | Docker sandbox for tools | OpenHarness |
| MEDIUM | 4 | Dead agent + task rebalancing | ClawTeam |
| MEDIUM | 19 | Degraded-mode MCP | claw-code |
| MEDIUM | 32 | Stale-branch detection | claw-code |
| MEDIUM | 7 | Green-level contracts | claw-code |
| MEDIUM | 33 | Deterministic mock service | claw-code |
| MEDIUM | 28 | Unified session mode | nanobot |
| MEDIUM | 34 | Agent color assignment | OpenHarness |
| MEDIUM | 21 | LSP integration | OpenHarness |
| MEDIUM | 25 | Auto-compact idle sessions | nanobot |
| MEDIUM | 24 | Cron job history + state machine | nanobot |
| MEDIUM | 20 | MCP schema normalization | nanobot |
| MEDIUM | 27 | Thinking/reasoning storage | nanobot |
| MEDIUM | 30 | Hook error isolation | nanobot |
| LOW | 18 | Workspace-root binding | claw-code |

---

## 27. Non-Functional Requirements

### 27.1 Performance

| Metric | Target |
|--------|--------|
| Message-to-first-token latency | < 2s (standard tier) |
| Tool execution overhead | < 100ms per tool call |
| Concurrent sessions | 100+ per instance |
| Concurrent sub-agents | 20+ per session |
| Memory footprint | < 512MB idle, < 1GB active |
| Startup time | < 5s (Docker container ready) |

### 27.2 Reliability

| Requirement | Implementation |
|-------------|----------------|
| Crash recovery | SQLite checkpoints, auto-resume |
| API retry | Exponential backoff with jitter (3 retries) |
| Provider failover | Automatic tier downgrade |
| Sub-agent failure | 3-layer detection + priority chain recovery |
| Task persistence | JSON + asyncio.Lock, survives restarts |
| Memory durability | Git-versioned Dream with restore |

### 27.3 Security

| Requirement | Implementation |
|-------------|----------------|
| No shell injection | `subprocess.run(shell=False)` always |
| Filesystem isolation | Docker + workspace confinement |
| Gateway auth | HMAC token + per-bridge ACL |
| Credential protection | Deny sensitive paths |
| Channel access control | Per-channel user allowlists |
| Input validation | Pydantic v2 + JSON repair |
| Docker non-root | uid 1000, no privileged mode |
| Budget limits | Per-agent and per-session cost caps |

### 27.4 Extensibility

| Extension Point | Mechanism |
|-----------------|-----------|
| New LLM provider | langchain integration or OpenAI-compatible |
| New channel | Implement `AbstractChannel` |
| New tool | `@tool` decorator, register in tool registry |
| New skill | Drop .md folder in `workspace/skills/` |
| New MCP server | Add to `mcp_servers` config |
| New bridge | Add to `gateway.bridges` config |
| New team template | Add TOML to `templates/` |
| New plugin | Python package in `workspace/plugins/` |
| New hook | `@hook("event_name")` decorator |
| New agent archetype | `@agent_archetype("name")` decorator |

### 27.5 Testing

| Level | Coverage | Tools |
|-------|----------|-------|
| Unit | 80%+ core modules | pytest + pytest-asyncio |
| Integration | All tools, all providers | Real API calls with mocking fallback |
| E2E | Agent loop, channels, scheduling, swarm | Docker-based test environment |
| Security | Sandbox escapes, injection | Custom security suite |
| Load | Concurrent sessions, sub-agent scaling | locust / k6 |

---

*End of Design Specification*
