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
20. [Observability & Cost Tracking](#20-observability--cost-tracking)
21. [Configuration](#21-configuration)
22. [Docker Deployment](#22-docker-deployment)
23. [Project Structure](#23-project-structure)
24. [Phased Roadmap](#24-phased-roadmap)
25. [Non-Functional Requirements](#25-non-functional-requirements)

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

## 20. Observability & Cost Tracking

### 20.1 Tracing

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

### 20.2 Cost Tracking

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

### 20.3 Metrics

- Token usage per request
- Tool execution duration and success rate
- Sub-agent lifecycle events
- Channel message delivery latency
- Context compression frequency
- Dream process duration and changes

### 20.4 Session Logging

Every message logged to `workspace/sessions/{thread_id}.jsonl`:
```json
{"role": "user", "content": "...", "timestamp": "...", "channel": "telegram", "user_id": "123"}
{"role": "assistant", "content": "...", "timestamp": "...", "tier": "standard", "cost_cents": 0.5}
{"role": "tool", "name": "web_search", "result": "...", "timestamp": "...", "duration_ms": 450}
```

---

## 21. Configuration

### 21.1 Single YAML File

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

### 21.2 Local Overrides

`config.local.yaml` (gitignored) overrides any key in `config.yaml`. Environment variables expand via `${VAR}` syntax. Pydantic v2 validates all config at startup.

---

## 22. Docker Deployment

### 22.1 Services

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
```

### 22.2 Dockerfile

- Base: `python:3.13-slim`
- System deps: curl, jq, ffmpeg, poppler-utils
- Non-root user (uid 1000)
- Health check: SQLite connectivity
- Multi-stage build for minimal image size

### 22.3 One-Command Install

```bash
curl -sSL https://raw.githubusercontent.com/.../install.sh | bash
```

The installer: checks prerequisites, clones repo, prompts for API keys, writes .env, builds Docker image, optionally starts gateway server.

---

## 23. Project Structure

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
├── config.yaml
├── config.local.yaml
├── docker-compose.yml
├── Dockerfile
├── install.sh
├── pyproject.toml
└── tests/
```

---

## 24. Phased Roadmap

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

**Exit criteria:** Agent can spawn sub-agents, manage them via tools, dream to consolidate memory, enforce permissions with user approval, track costs per user.

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

**Exit criteria:** Launch a 5-agent software dev team from template, complete a coding task autonomously. Three new channels working.

### Phase 3 — Polish & Scale (Weeks 8+)

| Deliverable | Notes |
|-------------|-------|
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

## 25. Non-Functional Requirements

### 25.1 Performance

| Metric | Target |
|--------|--------|
| Message-to-first-token latency | < 2s (standard tier) |
| Tool execution overhead | < 100ms per tool call |
| Concurrent sessions | 100+ per instance |
| Concurrent sub-agents | 20+ per session |
| Memory footprint | < 512MB idle, < 1GB active |
| Startup time | < 5s (Docker container ready) |

### 25.2 Reliability

| Requirement | Implementation |
|-------------|----------------|
| Crash recovery | SQLite checkpoints, auto-resume |
| API retry | Exponential backoff with jitter (3 retries) |
| Provider failover | Automatic tier downgrade |
| Sub-agent failure | 3-layer detection + priority chain recovery |
| Task persistence | JSON + asyncio.Lock, survives restarts |
| Memory durability | Git-versioned Dream with restore |

### 25.3 Security

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

### 25.4 Extensibility

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

### 25.5 Testing

| Level | Coverage | Tools |
|-------|----------|-------|
| Unit | 80%+ core modules | pytest + pytest-asyncio |
| Integration | All tools, all providers | Real API calls with mocking fallback |
| E2E | Agent loop, channels, scheduling, swarm | Docker-based test environment |
| Security | Sandbox escapes, injection | Custom security suite |
| Load | Concurrent sessions, sub-agent scaling | locust / k6 |

---

*End of Design Specification*
