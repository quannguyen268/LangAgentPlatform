# PRD: LangAgent Platform
### The Most Modern Agentic Architecture System
**Version:** 0.1.0-draft  
**Date:** 2026-04-15  
**Author:** Solution Architecture Team  

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Reference Analysis — Feature Comparison Matrix](#2-reference-analysis)
3. [Vision & Goals](#3-vision--goals)
4. [Master Agent — The Orchestration Layer](#4-master-agent)
5. [Architecture Overview](#5-architecture-overview)
6. [Feature Specification](#6-feature-specification)
7. [Technical Design](#7-technical-design)
8. [Phased Roadmap](#8-phased-roadmap)
9. [Non-Functional Requirements](#9-non-functional-requirements)

---

## 1. Executive Summary

**LangAgent Platform** is a next-generation, production-grade AI agent platform built on **LangChain/LangGraph + DeepAgents**. It synthesizes the best architectural patterns from four leading open-source agent systems (ClawTeam, OpenHarness, ciana-parrot, nanobot) into a unified, modular, and extensible platform.

**Core thesis:** No single existing project covers all dimensions well. By combining:
- **ciana-parrot's** multi-tier LLM routing + host gateway bridge + DeepAgents foundation
- **OpenHarness's** 43+ tool ecosystem + permission system + plugin architecture + Claude Code compatibility
- **nanobot's** Dream memory system + 15+ channel integrations + progressive skill loading + lightweight design
- **ClawTeam's** multi-agent swarm coordination + git worktree isolation + harness phases + cost tracking

...we can build a platform that is simultaneously **powerful**, **extensible**, **cost-efficient**, and **production-hardened**.

---

## 2. Reference Analysis

### 2.1 Repository Profiles

| Dimension | ClawTeam | OpenHarness | ciana-parrot | nanobot |
|-----------|----------|-------------|--------------|---------|
| **Focus** | Multi-agent swarm coordination | Agent harness infrastructure | Personal AI assistant | Lightweight personal agent |
| **Framework** | Framework-agnostic (CLI spawning) | Custom Python harness | DeepAgents + LangGraph | Custom Python (no litellm) |
| **LLM Providers** | Any (via CLI agents) | 15+ (Anthropic, OpenAI, Gemini, DeepSeek, Groq, etc.) | 7 (Anthropic, OpenAI, Gemini, Groq, Ollama, OpenRouter, vLLM) | 30+ (native SDKs) |
| **Model Routing** | N/A (per-agent model) | Provider profiles | Multi-tier RoutingChatModel (lite→expert) | Per-provider auto-detection |
| **Channels** | N/A (CLI only) | Telegram, Slack, Discord, Feishu, +8 more | Telegram (extensible) | 15+ (Telegram, Discord, WeChat, Feishu, Slack, Matrix, Email, QQ, WhatsApp, etc.) |
| **Tools** | Inbox, Task, Board, Workspace (CLI) | 43+ (File, Shell, Search, Web, MCP, Agent, Notebook) | web_search, web_fetch, schedule, host_execute, switch_model | read, write, edit, glob, grep, exec, web_search, web_fetch, cron, notebook, spawn |
| **Skills** | N/A | 7 built-in (.md format, Claude-compatible) | 27 built-in (.md with requires_env/requires_bridge filtering) | 8 built-in (.md with progressive loading) |
| **MCP** | FastMCP server (exposes ClawTeam as MCP) | Stdio + HTTP client with auto-reconnect | MultiServerMCPClient (stdio) | Stdio + HTTP + SSE client |
| **Memory** | N/A (stateless coordination) | MEMORY.md + CLAUDE.md + auto-compaction | IDENTITY.md + AGENT.md + MEMORY.md | SOUL.md + USER.md + MEMORY.md + Dream (2-stage consolidation with Git) |
| **Multi-Agent** | Full swarm (spawn, teams, mailbox, harness phases) | Subagent spawning + team registry | Single agent | Subagent spawning |
| **Permissions** | N/A | Multi-level (Default/Auto/Plan) + path rules + hooks | Gateway allowlists + filesystem sandbox | bubblewrap sandbox + workspace restriction |
| **Scheduling** | N/A | CronCreate/Delete/Toggle | Cron + interval + one-shot (in-chat) | Natural language + cron + one-shot |
| **Observability** | Cost tracking + Gource visualization | LangSmith/langfuse tracing (optional) | LangSmith tracing (optional) | Langfuse tracing (optional) |
| **Deployment** | Local (tmux/subprocess) + distributed (SSHFS/P2P) | CLI + Gateway + Docker (planned) | Docker-only (one command) | Docker + CLI + systemd + API server |
| **UI** | Terminal (Rich) + Web board (SSE) | React/Ink TUI | Telegram inline keyboards + Avatar emotion | Rich + prompt_toolkit CLI |
| **Unique Strength** | Swarm intelligence, framework-agnostic coordination | Most complete tool/permission/plugin ecosystem | Host gateway bridge, multi-tier routing, avatar | Dream memory, channel breadth, code minimalism |

### 2.2 Feature Gap Analysis — What Each Repo Lacks

| Feature | ClawTeam | OpenHarness | ciana-parrot | nanobot |
|---------|----------|-------------|--------------|---------|
| LangGraph/DeepAgents foundation | Missing | Missing | **Has it** | Missing |
| Multi-tier model routing | Missing | Missing | **Has it** | Missing |
| Host gateway bridge (macOS CLI) | Missing | Missing | **Has it** | Missing |
| Multi-agent swarm | **Has it** | Partial | Missing | Missing |
| Git worktree isolation per agent | **Has it** | Partial | Missing | Missing |
| Harness phases (plan→execute→verify) | **Has it** | Plan mode only | Missing | Missing |
| 43+ integrated tools | Missing | **Has it** | 6 tools | 12 tools |
| Permission system (multi-level) | Missing | **Has it** | Gateway-only | Sandbox-only |
| Claude Code plugin compatibility | Missing | **Has it** | Missing | Missing |
| Pre/PostToolUse hooks | Missing | **Has it** | Missing | Lifecycle hooks |
| 15+ communication channels | Missing | 12 channels | 1 channel | **15+ channels** |
| Dream memory (2-stage + Git) | Missing | Missing | Missing | **Has it** |
| Progressive skill loading | Missing | Missing | Missing | **Has it** |
| Voice transcription | Missing | Missing | **Has it** | **Has it** |
| Scheduled tasks (agent-created) | Missing | Cron only | **Full (cron+interval+once)** | **Full** |
| Avatar/emotion system | Missing | Missing | **Has it** | Missing |
| Cost tracking | **Has it** | **Has it** | Missing | Token tracking |
| Docker-first deployment | Missing | Planned | **Has it** | **Has it** |
| OpenAI-compatible API server | Missing | Missing | Missing | **Has it** |
| Web dashboard | SSE board | Missing | Avatar SSE | Missing |

### 2.3 Architectural Decision: Why LangGraph + DeepAgents

Among the four repos, only **ciana-parrot** uses LangGraph/DeepAgents. This is the correct foundation because:

1. **LangGraph provides** — State machines, checkpointing, streaming, human-in-the-loop, time-travel debugging, and first-class tool calling
2. **DeepAgents provides** — Skills auto-discovery, markdown-based knowledge, filesystem backends, and agent creation patterns
3. **Ecosystem** — LangChain's vast integrations (LLM providers, vector stores, retrievers, document loaders)
4. **Observability** — Native LangSmith/langfuse integration for production monitoring
5. **Community** — Largest agent framework community, fastest-moving ecosystem

The other repos use custom Python agent loops that would need to replicate what LangGraph gives for free.

---

## 3. Vision & Goals

### 3.1 Product Vision

> Build a **single platform** that can operate as a personal AI assistant, a multi-agent swarm coordinator, and a developer tool harness — all configurable from the same codebase, deployed via Docker, and extensible through skills, plugins, hooks, and MCP.

### 3.2 Design Principles

| Principle | Description |
|-----------|-------------|
| **LangGraph-native** | All agent logic runs as LangGraph state graphs — checkpointed, streamable, debuggable |
| **Modular by default** | Every subsystem is a pluggable module. Swap LLM, channel, memory, tools without touching core |
| **Cost-aware** | Multi-tier routing is first-class. Every token counted. Agent can self-optimize cost |
| **Secure by design** | Sandbox-first execution. Permission system. Gateway allowlists. No shell=True |
| **Swarm-capable** | Single agent mode is default, but scales to coordinated multi-agent teams |
| **Channel-agnostic** | Same agent, any channel. Telegram, Discord, Slack, API, CLI, WebSocket |
| **Memory-first** | Persistent identity, user knowledge, and project facts survive across sessions |
| **Docker-only deploy** | One `docker compose up` to run. No system dependencies beyond Docker |
| **Skill-driven** | Drop a folder → get a capability. No code changes, no restarts |
| **Observable** | Every tool call, LLM invocation, and cost event traceable via LangSmith/langfuse |

### 3.3 Target Users

1. **Power users** — Personal AI assistant with Telegram/Discord, scheduled tasks, host tool access
2. **Developers** — Code harness with tools, permissions, plugins (Claude Code-compatible)
3. **Teams** — Multi-agent swarm for complex tasks (research, development, analysis)
4. **Researchers** — Extensible platform for agent behavior experiments

---

## 4. Master Agent — The Orchestration Layer

### 4.1 Core Concept

The **Master Agent** is the platform's central intelligence — a persistent, always-on LangGraph agent that acts as the **operating system** for the entire agent swarm. It is not just a router; it is an autonomous orchestrator that can:

1. **Understand user intent** and decompose complex goals into agent teams
2. **Spawn specialized agents** with the right tools, skills, and model tiers
3. **Subscribe tools/skills to agents** dynamically based on task requirements
4. **Monitor and intervene** — reassign tasks, swap models, kill stuck agents
5. **Learn from outcomes** — remember which configurations worked, improve over time

Both the **user** and the **Master Agent itself** can perform orchestration actions. The user can directly manage agents if they prefer, but the Master Agent makes the platform self-organizing by default.

### 4.2 Master Agent Capabilities

```
┌───────────────────────────────────────────────────────────────────┐
│                      MASTER AGENT                                 │
│  "I am the conductor. You tell me the goal, I build the team."   │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │ ORCHESTRATION TOOLS (exclusive to Master Agent)             │  │
│  │                                                             │  │
│  │  spawn_agent(name, role, tools, skills, tier, prompt)       │  │
│  │  customize_agent(agent_id, add_tools, remove_tools, tier)   │  │
│  │  subscribe_tool(agent_id, tool_name)                        │  │
│  │  unsubscribe_tool(agent_id, tool_name)                      │  │
│  │  subscribe_skill(agent_id, skill_name)                      │  │
│  │  assign_task(agent_id, task_description, priority)          │  │
│  │  monitor_agents() → status of all agents                    │  │
│  │  recall_agent(agent_id) → terminate and merge work          │  │
│  │  switch_agent_model(agent_id, tier)                         │  │
│  │  create_team(template, goal) → spawn full team from TOML    │  │
│  │  dissolve_team(team_id) → merge all work, cleanup           │  │
│  │  escalate(agent_id, reason) → re-route task to higher tier  │  │
│  │  review_cost() → cost breakdown by agent, tier, team        │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │ STANDARD TOOLS (shared with spawned agents)                 │  │
│  │  web_search, web_fetch, read_file, write_file, exec, ...   │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │ MEMORY & KNOWLEDGE                                          │  │
│  │  SOUL.md (identity) │ USER.md (preferences)                 │  │
│  │  MEMORY.md (facts)  │ AGENT_REGISTRY.md (known agent types) │  │
│  │  TEAM_PLAYBOOK.md (past team configs that worked well)      │  │
│  └─────────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────────┘
```

### 4.3 How It Works — Example Flows

**Flow 1: User asks "Build me a REST API for a todo app"**

```
User → Master Agent: "Build me a REST API for a todo app"
                      │
Master Agent (thinks): This is a software dev task.
                       I'll use the software-dev template.
                       │
                       ├─ spawn_agent("architect", role="planner",
                       │    tier="advanced", tools=[read, write, edit, grep, glob, exec],
                       │    skills=["plan", "review"])
                       │
                       ├─ spawn_agent("backend-dev", role="executor",
                       │    tier="standard", tools=[read, write, edit, exec, web_search],
                       │    skills=["commit", "debug"])
                       │
                       ├─ spawn_agent("tester", role="evaluator",
                       │    tier="standard", tools=[read, exec, grep],
                       │    skills=["test"])
                       │
                       ├─ assign_task("architect", "Design REST API schema and project structure")
                       │
                       └─ Master monitors via mailbox, advances harness phases,
                          escalates to "expert" tier if architect gets stuck
```

**Flow 2: User asks "Check my Spotify and add today's top track to my Bear note"**

```
User → Master Agent: "Check my Spotify and add today's top track to my Bear note"
                      │
Master Agent (thinks): Simple task, no team needed. I'll handle it myself.
                       Need spotify and bear-notes bridges.
                       │
                       ├─ host_execute(bridge="spotify", command="current")
                       │   → "Now Playing: 'Bohemian Rhapsody' by Queen"
                       │
                       ├─ host_execute(bridge="bear-notes", command="create",
                       │    args=["--title", "Today's Top Track", "--body", "Bohemian Rhapsody - Queen"])
                       │
                       └─ "Done! Added 'Bohemian Rhapsody' to your Bear notes."
```

**Flow 3: User manually customizes an agent**

```
User: "Give the backend-dev agent access to the github skill and switch it to expert tier"
                      │
Master Agent:
  ├─ subscribe_skill("backend-dev", "github")
  ├─ switch_agent_model("backend-dev", "expert")
  └─ "Done. backend-dev now has the github skill and is running on expert tier (Claude Opus)."
```

### 4.4 Agent Registry & Playbook

The Master Agent maintains two knowledge files that improve over time:

**AGENT_REGISTRY.md** — Known agent archetypes:
```markdown
## Backend Developer
- **Default tier:** standard
- **Core tools:** read_file, write_file, edit_file, exec, grep, glob
- **Core skills:** commit, debug
- **Typical role:** executor
- **Works well with:** architect, tester

## Research Analyst  
- **Default tier:** advanced
- **Core tools:** web_search, web_fetch, read_file, write_file
- **Core skills:** summarize
- **Typical role:** executor
- **Works well with:** lead researcher, editor
```

**TEAM_PLAYBOOK.md** — Learned team configurations:
```markdown
## REST API Development (success rate: 92%)
- architect (advanced) → 1 agent
- backend-dev (standard) → 2 agents  
- tester (standard) → 1 agent
- Harness: plan → execute → verify → ship
- Notes: Adding a second backend-dev reduced completion time by 40%

## Content Research (success rate: 85%)
- researcher (advanced) → 3 agents
- editor (expert) → 1 agent
- Notes: Expert tier for editor significantly improved output quality
```

The Master Agent updates these files through the Dream memory process, learning from outcomes.

### 4.5 User vs. Master Agent Orchestration

| Action | User Can Do | Master Agent Can Do |
|--------|-------------|---------------------|
| Spawn an agent | Yes, via `/spawn` command | Yes, autonomously based on goal |
| Subscribe tools to agent | Yes, via `/subscribe-tool` | Yes, based on task analysis |
| Switch agent model tier | Yes, via `/switch-model` | Yes, based on cost/complexity |
| Create a team | Yes, via `/launch` template | Yes, by decomposing a complex goal |
| Monitor agents | Yes, via `/status` | Yes, continuously with auto-intervention |
| Kill an agent | Yes, via `/recall` | Yes, if stuck or redundant |
| Assign tasks | Yes, via `/assign` | Yes, as part of harness flow |
| Review costs | Yes, via `/cost` | Yes, triggers tier downgrades when budget reached |

The platform is **user-first** — the user always has override authority. The Master Agent proposes, the user disposes. But for hands-off operation, the Master Agent can run the entire swarm autonomously.

### 4.6 Master Agent LangGraph Design

```python
# The Master Agent is itself a LangGraph state graph
# with specialized orchestration nodes

class MasterAgentState(MessagesState):
    active_agents: dict[str, AgentInfo]    # Running agents
    active_teams: dict[str, TeamInfo]       # Running teams
    pending_tasks: list[TaskInfo]           # Unassigned tasks
    cost_budget: float                      # Remaining budget
    current_phase: str                      # Harness phase
    
master_graph = StateGraph(MasterAgentState)
master_graph.add_node("reason", master_reasoning_node)      # Understand user intent
master_graph.add_node("plan", master_planning_node)          # Decompose into agents/tasks
master_graph.add_node("orchestrate", orchestration_node)     # Spawn/customize/assign
master_graph.add_node("monitor", monitoring_node)            # Watch agent health + progress
master_graph.add_node("tools", tool_executor_node)           # Execute tools (including orchestration tools)
master_graph.add_node("respond", response_node)              # Report to user

# The Master Agent can also handle simple tasks directly
# without spawning any sub-agents (single-agent mode)
```

---

## 5. Architecture Overview

### 5.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        CHANNELS LAYER                           │
│  Telegram │ Discord │ Slack │ Feishu │ Matrix │ CLI │ API │ WS  │
└─────────────────────────┬───────────────────────────────────────┘
                          │ IncomingMessage / SendResult
┌─────────────────────────▼───────────────────────────────────────┐
│                      MESSAGE BUS                                │
│  Async queue │ Channel routing │ Thread mapping │ Rate limiting  │
└─────────────────────────┬───────────────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────────────┐
│                   SESSION MANAGER                               │
│  Per-thread state │ SQLite checkpoints │ Session reset │ TTL    │
└─────────────────────────┬───────────────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────────────┐
│                 LANGGRAPH AGENT CORE                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │ State Graph   │  │ Checkpointer │  │ Streaming Engine     │  │
│  │ (ReAct loop)  │  │ (SQLite/     │  │ (token deltas,       │  │
│  │               │  │  Postgres)   │  │  tool events)        │  │
│  └──────┬───────┘  └──────────────┘  └──────────────────────┘  │
│         │                                                       │
│  ┌──────▼────────────────────────────────────────────────────┐  │
│  │              ROUTING CHAT MODEL                           │  │
│  │  lite ──→ standard ──→ advanced ──→ expert                │  │
│  │  (gpt-4o-mini) (sonnet)  (opus)    (opus+thinking)       │  │
│  │  Per-task tier via ContextVar │ Cost tracking per tier    │  │
│  └───────────────────────────────────────────────────────────┘  │
│         │                                                       │
│  ┌──────▼────────────────────────────────────────────────────┐  │
│  │                    TOOL REGISTRY                          │  │
│  │  Built-in │ Skills │ MCP │ Host Gateway │ Dynamic         │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                          │
          ┌───────────────┼───────────────┐
          ▼               ▼               ▼
┌─────────────┐  ┌──────────────┐  ┌──────────────┐
│  MEMORY     │  │  PERMISSIONS │  │  SCHEDULER   │
│  SOUL.md    │  │  Multi-level │  │  Cron        │
│  USER.md    │  │  Path rules  │  │  Interval    │
│  MEMORY.md  │  │  Hooks       │  │  One-shot    │
│  Dream      │  │  Sandbox     │  │  Model tier  │
│  Consolidate│  │  Gateway ACL │  │  override    │
└─────────────┘  └──────────────┘  └──────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────────┐
│                    SWARM COORDINATOR                            │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐          │
│  │ Agent A  │  │ Agent B  │  │ Agent C  │  │ Agent D  │  ...    │
│  │ (custom  │  │ (custom  │  │ (custom  │  │ (custom  │         │
│  │  tools)  │  │  tools)  │  │  tools)  │  │  tools)  │         │
│  └─────────┘  └─────────┘  └─────────┘  └─────────┘          │
│  Mailbox │ Task board │ Harness phases │ Git worktree          │
│  Cost rollup │ Templates │ Transport (File/P2P)                │
└─────────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────────┐
│                    HOST GATEWAY                                 │
│  HTTP bridge │ HMAC auth │ Per-bridge allowlists │ CWD safety   │
│  Bridges: Spotify, Reminders, iMessage, Things, Bear, 1P, ...  │
└─────────────────────────────────────────────────────────────────┘
```

**Key insight: The Master Agent sits between the Session Manager and the LangGraph Core.** It receives user messages, decides whether to handle them solo or spawn a team, and either way delegates to the LangGraph agent core for execution. Spawned sub-agents each get their own LangGraph instance with a custom tool set curated by the Master.

### 5.2 Project Structure

```
lang-agent-platform/
├── src/
│   ├── core/                    # LangGraph agent core
│   │   ├── graph.py             # State graph definition (ReAct loop)
│   │   ├── state.py             # AgentState schema
│   │   ├── router.py            # RoutingChatModel (multi-tier)
│   │   ├── checkpointer.py      # SQLite/Postgres checkpointer
│   │   ├── streaming.py         # Stream event protocol
│   │   └── compaction.py        # Context auto-compaction
│   │
│   ├── providers/               # LLM provider implementations
│   │   ├── base.py              # Abstract provider interface
│   │   ├── anthropic.py         # Claude (native SDK)
│   │   ├── openai.py            # GPT (native SDK)
│   │   ├── google.py            # Gemini (langchain-google-genai)
│   │   ├── groq.py              # Groq
│   │   ├── ollama.py            # Ollama (local)
│   │   ├── openrouter.py        # OpenRouter
│   │   ├── vllm.py              # vLLM (local)
│   │   └── registry.py          # Provider auto-detection & registry
│   │
│   ├── tools/                   # Built-in tool implementations
│   │   ├── filesystem.py        # read, write, edit, glob, grep
│   │   ├── shell.py             # Sandboxed exec (bwrap support)
│   │   ├── web.py               # web_search (multi-provider), web_fetch
│   │   ├── scheduling.py        # schedule_task, list_tasks, cancel_task
│   │   ├── gateway.py           # host_execute (bridge system)
│   │   ├── model.py             # switch_model (tier switching)
│   │   ├── notebook.py          # Jupyter notebook editing
│   │   ├── agent.py             # spawn_subagent, send_message
│   │   └── registry.py          # Dynamic tool registration + MCP wrapping
│   │
│   ├── skills/                  # Skills system
│   │   ├── loader.py            # Auto-discovery + progressive loading
│   │   ├── filter.py            # requires_env / requires_bridge filtering
│   │   ├── builtin/             # Built-in skills (.md)
│   │   │   ├── memory/SKILL.md
│   │   │   ├── github/SKILL.md
│   │   │   ├── commit/SKILL.md
│   │   │   ├── debug/SKILL.md
│   │   │   ├── review/SKILL.md
│   │   │   ├── plan/SKILL.md
│   │   │   ├── cron/SKILL.md
│   │   │   └── ...
│   │   └── hub.py               # Remote skill marketplace (ClawHub)
│   │
│   ├── memory/                  # Persistent memory system
│   │   ├── files.py             # SOUL.md, USER.md, MEMORY.md management
│   │   ├── consolidator.py      # Stage 1: conversation → history.jsonl
│   │   ├── dream.py             # Stage 2: history → knowledge file edits
│   │   ├── search.py            # Memory search (multilingual)
│   │   └── context.py           # CLAUDE.md discovery + injection
│   │
│   ├── channels/                # Communication channels
│   │   ├── base.py              # AbstractChannel protocol
│   │   ├── manager.py           # Channel lifecycle + message bus
│   │   ├── telegram.py          # Telegram (full: voice, photos, keyboards)
│   │   ├── discord.py           # Discord
│   │   ├── slack.py             # Slack
│   │   ├── feishu.py            # Feishu/Lark
│   │   ├── matrix.py            # Matrix/Element
│   │   ├── wechat.py            # WeChat
│   │   ├── email.py             # Email (IMAP/SMTP)
│   │   ├── whatsapp.py          # WhatsApp
│   │   ├── websocket.py         # WebSocket (real-time)
│   │   ├── api.py               # OpenAI-compatible REST API
│   │   └── cli.py               # Interactive CLI
│   │
│   ├── permissions/             # Security & permissions
│   │   ├── manager.py           # Permission mode (default/auto/plan)
│   │   ├── rules.py             # Path-level + command rules
│   │   ├── hooks.py             # PreToolUse / PostToolUse hooks
│   │   ├── sandbox.py           # bwrap + Docker sandbox
│   │   └── sensitive.py         # Credential path protection
│   │
│   ├── scheduler/               # Task scheduling
│   │   ├── engine.py            # Scheduler loop (poll + execute)
│   │   ├── store.py             # Task persistence (JSON + SQLite)
│   │   ├── cron.py              # Cron expression evaluation
│   │   └── natural.py           # Natural language → cron parsing
│   │
│   ├── gateway/                 # Host gateway bridge
│   │   ├── server.py            # HTTP server (runs on host)
│   │   ├── client.py            # Async httpx client (runs in Docker)
│   │   ├── bridges.py           # Bridge configuration + validation
│   │   └── avatar.py            # Avatar emotion SSE relay
│   │
│   ├── swarm/                   # Multi-agent coordination
│   │   ├── coordinator.py       # Team registry + lifecycle
│   │   ├── mailbox.py           # Inter-agent messaging
│   │   ├── task_board.py        # Task creation + dependencies
│   │   ├── harness.py           # Phase state machine (plan→execute→verify)
│   │   ├── spawn.py             # Agent spawning (tmux/subprocess)
│   │   ├── workspace.py         # Git worktree isolation
│   │   ├── transport.py         # File + P2P (ZMQ) transport
│   │   ├── templates.py         # Team templates (TOML)
│   │   └── cost.py              # Per-agent cost tracking
│   │
│   ├── mcp/                     # Model Context Protocol
│   │   ├── client.py            # Stdio + HTTP + SSE client
│   │   ├── server.py            # FastMCP server (expose platform as MCP)
│   │   ├── wrapper.py           # MCP tool → LangGraph tool adapter
│   │   └── auth.py              # MCP authentication
│   │
│   ├── plugins/                 # Plugin ecosystem
│   │   ├── loader.py            # Plugin discovery + loading
│   │   ├── schema.py            # Command, Hook, Agent definitions
│   │   └── compatibility.py     # Claude Code plugin compatibility
│   │
│   ├── observability/           # Tracing & metrics
│   │   ├── tracer.py            # LangSmith / langfuse integration
│   │   ├── cost.py              # Token counting + cost calculation
│   │   └── metrics.py           # Prometheus-style metrics
│   │
│   ├── config/                  # Configuration
│   │   ├── schema.py            # Pydantic v2 config models
│   │   ├── loader.py            # YAML + env var expansion
│   │   └── profiles.py          # Provider/agent profiles
│   │
│   ├── session/                 # Session management
│   │   ├── manager.py           # Per-thread session isolation
│   │   ├── history.py           # JSONL session logging
│   │   └── resume.py            # Session resume + time-travel
│   │
│   ├── commands/                # Slash commands
│   │   ├── router.py            # Command registry + dispatch
│   │   └── builtin.py           # /help, /new, /status, /dream, /stop, etc.
│   │
│   └── main.py                  # Entry point + wiring
│
├── gateway/                     # Host-side gateway (standalone)
│   ├── server.py                # Gateway HTTP server
│   └── bridges/                 # Bridge definitions
│
├── workspace/                   # Agent workspace (mounted volume)
│   ├── SOUL.md                  # Agent identity & personality
│   ├── USER.md                  # User preferences & knowledge
│   ├── MEMORY.md                # Learned facts & decisions
│   ├── AGENT.md                 # Behavior instructions
│   ├── memory/                  # Consolidation data
│   │   ├── history.jsonl
│   │   └── .git/
│   ├── skills/                  # User-added skills
│   ├── sessions/                # JSONL session logs
│   └── templates/               # Custom response templates
│
├── skills/                      # Built-in skills library
│   ├── memory/SKILL.md
│   ├── github/SKILL.md
│   ├── weather/SKILL.md
│   ├── spotify/SKILL.md
│   ├── apple-reminders/SKILL.md
│   ├── 1password/SKILL.md
│   └── ...
│
├── templates/                   # Team launch templates
│   ├── software-dev.toml
│   ├── code-review.toml
│   ├── research.toml
│   └── hedge-fund.toml
│
├── config.yaml                  # Main configuration
├── config.local.yaml            # Local overrides (gitignored)
├── docker-compose.yml           # Docker deployment
├── Dockerfile                   # Multi-stage build
├── install.sh                   # One-command installer
├── pyproject.toml               # Python project config
└── tests/                       # Test suite
```

---

## 6. Feature Specification

### 6.1 Multi-Provider LLM Engine

**Source inspiration:** ciana-parrot (routing), nanobot (30+ providers), OpenHarness (provider workflows)

| Feature | Priority | Description |
|---------|----------|-------------|
| Anthropic (Claude) | P0 | Native SDK with extended thinking, prompt caching |
| OpenAI (GPT) | P0 | Native SDK with reasoning model support (o1/o3) |
| Google Gemini | P0 | langchain-google-genai integration |
| Groq | P1 | Fast inference for voice transcription + chat |
| Ollama | P1 | Local model deployment |
| OpenRouter | P1 | Gateway for 200+ models |
| vLLM | P1 | Self-hosted open-source inference |
| DeepSeek | P2 | Chain-of-thought reasoning models |
| Moonshot/Kimi | P2 | Chinese market support |
| Qwen (DashScope) | P2 | Alibaba models |
| GitHub Copilot | P2 | OAuth device flow, no API key |
| Bedrock (AWS) | P2 | Enterprise deployment |

**Implementation:** Each provider implements a `BaseLLMProvider` interface. Auto-detection by model name keyword. Provider registry with retry policies.

### 6.2 Multi-Tier Model Routing

**Source inspiration:** ciana-parrot (RoutingChatModel)

```yaml
model_router:
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
  default_tier: "standard"
```

**Capabilities:**
- Agent calls `switch_model(tier="expert")` mid-conversation for complex reasoning
- Scheduled tasks specify `model_tier` to optimize cost
- ContextVar-based per-task tier tracking (async-safe)
- System message injection with current tier label
- Cost tracking per tier with automatic rollup
- Automatic fallback on provider errors (tier downgrade)

### 6.3 Communication Channels

**Source inspiration:** nanobot (15+ channels), ciana-parrot (Telegram depth)

| Channel | Phase | Features |
|---------|-------|----------|
| Telegram | P0 | Long-polling, voice, photos, inline keyboards, typing, Markdown→HTML |
| CLI | P0 | Interactive streaming, Rich TUI |
| OpenAI-compatible API | P0 | REST + SSE streaming for web UI integration |
| Discord | P1 | Bot websocket, embeds, file attachments |
| Slack | P1 | Bot token, threads, file upload |
| WebSocket | P1 | Real-time bidirectional streaming |
| Feishu/Lark | P2 | CardKit streaming, media cards |
| Matrix/Element | P2 | E2EE, media rich |
| WeChat | P2 | QR scan, voice memo |
| Email | P2 | IMAP/SMTP, attachment support |
| WhatsApp | P3 | Node.js bridge, QR scan |

**Architecture:**
```python
class AbstractChannel(ABC):
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def send(self, thread_id: str, content: str, **kwargs) -> SendResult: ...
    async def send_file(self, thread_id: str, file: bytes, **kwargs) -> SendResult: ...
    def on_message(self, callback: Callable[[IncomingMessage], Awaitable[None]]): ...
```

**Per-channel features:**
- Allow lists (user IDs)
- Group policy (mention / open / allowlist)
- Unified session option (one conversation across all channels)
- Auto-retry on send failure
- Platform-specific rendering (Feishu cards, Discord embeds)
- Voice transcription (Whisper via Groq/OpenAI)

### 6.4 Host Gateway Bridge

**Source inspiration:** ciana-parrot (gateway system)

**Architecture:** Standalone HTTP server on host ↔ async client inside Docker container

**Security layers:**
1. HMAC token authentication
2. Per-bridge command allowlists
3. CWD path traversal prevention (realpath validation)
4. No shell execution (`subprocess.run(shell=False)`)
5. Configurable timeouts per bridge

**Default bridges:**
```yaml
gateway:
  host: "host.docker.internal"
  port: 9842
  token: "${GATEWAY_TOKEN}"
  bridges:
    spotify: { command: "spogo", allowed_commands: ["play", "pause", "next", ...] }
    apple-reminders: { command: "remindctl", allowed_commands: ["add", "list", ...] }
    things: { command: "things", allowed_commands: ["add", "list", ...] }
    imessage: { command: "imsg", allowed_commands: ["send", "read", ...] }
    bear-notes: { command: "grizzly", allowed_commands: ["create", "search", ...] }
    obsidian: { command: "obsidian-cli", allowed_commands: ["search", "create", ...] }
    1password: { command: "op", allowed_commands: ["item get", ...] }
    homekit: { command: "openhue", allowed_commands: ["get", "set", ...] }
    sonos: { command: "sonos", allowed_commands: ["play", "pause", ...] }
    camsnap: { command: "camsnap", allowed_commands: ["snap", ...] }
```

**Avatar emotion system** (optional):
- After agent response → lite-tier LLM analyzes emotion
- POST to gateway `/avatar/emotion` endpoint
- SSE relay to connected browser client (3D avatar)

### 6.5 Tool Ecosystem

**Source inspiration:** OpenHarness (43+ tools), ciana-parrot (web/scheduling), nanobot (sandbox)

#### Core Tools (P0)

| Tool | Description |
|------|-------------|
| `read_file` | Read files with line range support, PDF/image capable |
| `write_file` | Create/overwrite files atomically |
| `edit_file` | Line-range edit, insert, delete with validation |
| `glob` | Fast file pattern matching |
| `grep` | Ripgrep-based content search with regex |
| `exec` | Sandboxed shell execution (bwrap support) |
| `web_search` | Multi-provider: Brave, DuckDuckGo, Tavily, SearXNG, Kagi |
| `web_fetch` | HTML→Markdown with readability extraction |
| `schedule_task` | Create cron/interval/one-shot scheduled tasks |
| `list_tasks` / `cancel_task` | Manage scheduled tasks |
| `host_execute` | Execute host CLI tools via gateway bridge |
| `switch_model` | Switch LLM tier mid-conversation |

#### Extended Tools (P1)

| Tool | Description |
|------|-------------|
| `notebook_edit` | Jupyter cell manipulation with kernel execution |
| `spawn_subagent` | Launch background agent tasks |
| `send_message` | Inter-agent communication |
| `mcp_tool` | Call any MCP server tool |

#### Swarm Tools (P2)

| Tool | Description |
|------|-------------|
| `team_create` / `team_delete` | Manage agent teams |
| `task_create` / `task_update` | Swarm task board |
| `inbox_send` / `inbox_receive` | Agent mailbox |
| `harness_advance` | Phase progression |

### 6.6 Skills System

**Source inspiration:** ciana-parrot (requires_env/requires_bridge), nanobot (progressive loading), OpenHarness (Claude-compatible)

**Format:**
```markdown
---
name: spotify
description: "Control Spotify playback and manage playlists"
requires_bridge: "spotify"
requires_env: []
homepage: "https://github.com/..."
---

# Spotify Control
Instructions for the agent on how to use the spotify bridge...
```

**Features:**
- Auto-discovery from `workspace/skills/` and `skills/builtin/`
- Progressive loading (summary first, full content on demand)
- Conditional activation via `requires_env` and `requires_bridge`
- Compatible with Claude Code / anthropics skills format
- Remote skill marketplace (ClawHub integration)
- Hot-reload (no restart needed when adding skills)

### 6.7 Memory System

**Source inspiration:** nanobot (Dream + 2-stage), ciana-parrot (IDENTITY/AGENT/MEMORY), OpenHarness (CLAUDE.md)

**Architecture: 3 files + 2-stage processing**

| File | Purpose | Updated by |
|------|---------|------------|
| `SOUL.md` | Agent identity, personality, voice, values | Dream process |
| `USER.md` | User preferences, habits, knowledge | Dream process |
| `MEMORY.md` | Project facts, decisions, context | Agent (real-time) + Dream |
| `AGENT.md` | Behavior instructions, tool guidelines | User (manual) |

**Stage 1 — Consolidation:**
- When context window pressure increases, summarize old messages
- Append to `memory/history.jsonl` (cursor-based, incremental)
- Triggered automatically or via `/consolidate` command

**Stage 2 — Dream:**
- Periodically (default: every 2 hours) studies new history
- Surgically edits SOUL.md, USER.md, MEMORY.md with minimal changes
- Full audit trail via Git versioning in `memory/.git/`
- Commands: `/dream`, `/dream-log`, `/dream-restore {sha}`

**Context injection:**
- All memory files loaded into every conversation context
- CLAUDE.md discovery from project directories
- Skills summary injected (progressive loading)

### 6.8 Permission & Security System

**Source inspiration:** OpenHarness (multi-level), ciana-parrot (gateway ACL), nanobot (bwrap)

**Permission modes:**
- **Default** — Ask before write/execute operations
- **Auto** — Allow everything (for sandboxed/trusted environments)
- **Plan** — Block all writes, review-first workflow

**Security layers:**

| Layer | Mechanism |
|-------|-----------|
| LLM tier | Model routing prevents expensive models for trivial tasks |
| Tool permissions | PreToolUse/PostToolUse hooks with approval dialogs |
| Path rules | Glob-based path allow/deny lists |
| Command rules | Deny lists for dangerous shell commands |
| Filesystem sandbox | bwrap / Docker isolation + workspace confinement |
| Gateway ACL | Per-bridge command allowlists + CWD restriction |
| Channel ACL | Per-channel user allowlists + group policies |
| Credential protection | Hardcoded deny for SSH, AWS, GCP, Docker credential paths |
| Input validation | Pydantic v2 for all tool inputs + JSON repair |

### 6.9 Scheduled Tasks

**Source inspiration:** ciana-parrot (cron+interval+once), nanobot (natural language scheduling)

**Task types:**
- **Cron** — Standard 5-field cron expressions with IANA timezone
- **Interval** — Repeat every N seconds
- **Once** — ISO timestamp for one-shot execution
- **Natural language** — "Every weekday at 9am", "Tomorrow at 3pm"

**Features:**
- Agent creates tasks via `schedule_task` tool in conversation
- Model tier override per task (use lite for routine checks)
- Results delivered back to originating channel
- Job history tracking (success/failure/duration)
- Persistent across container restarts (JSON file + asyncio.Lock)

### 6.10 Multi-Agent Swarm

**Source inspiration:** ClawTeam (full swarm system)

**Coordination model:**

```
┌─ Leader Agent ─────────────────────────────┐
│  Spawns workers, designs tasks, monitors   │
│  Uses: oh spawn, oh task create, oh inbox  │
└────┬──────────┬──────────┬─────────────────┘
     │          │          │
┌────▼───┐ ┌───▼────┐ ┌───▼────┐
│Worker 1│ │Worker 2│ │Worker 3│  (git worktree each)
│Backend │ │Frontend│ │Tester  │
└────────┘ └────────┘ └────────┘
```

**Features:**
- Agent spawning with CLI adapters (Claude, Codex, Gemini, Kimi, etc.)
- Git worktree isolation per agent (merge-ready branches)
- Inter-agent messaging (mailbox: send, broadcast, receive, peek)
- Task board with dependencies (blocks/blocked_by)
- Harness phases: discuss → plan → execute → verify → ship
- Phase gates (artifact required, all tasks complete, human approval)
- Team templates (TOML) for domain-specific setups
- Cost tracking per agent with team rollup
- Transport: file-based (default) + P2P (ZMQ) for distributed
- Dashboard: terminal (Rich) + web (SSE)
- Gource visualization for swarm activity

### 6.11 MCP Support

**Source inspiration:** nanobot (multi-transport), OpenHarness (HTTP + auto-reconnect)

**Client features:**
- Stdio, HTTP, and SSE transport
- Auto-configuration from Claude Desktop/Cursor config
- Tool wrapping: MCP tools → LangGraph tools automatically
- Resource and prompt exposure
- Multiple concurrent server connections
- Per-server tool filtering and timeout control

**Server features:**
- FastMCP server exposing platform as MCP tools
- Enables external agents to use this platform's capabilities
- Tools: memory, scheduling, gateway, swarm coordination

### 6.12 Observability

**Source inspiration:** OpenHarness (cost tracking), nanobot (langfuse), ciana-parrot (LangSmith)

| Feature | Implementation |
|---------|---------------|
| LangSmith tracing | Native LangGraph integration |
| langfuse tracing | Alternative backend support |
| Token counting | Per-call, per-tier, per-agent |
| Cost tracking | Model-specific pricing, team rollup |
| Tool execution metrics | Duration, success/failure, arguments |
| Session logging | JSONL per thread for audit trail |
| Web dashboard | Real-time SSE board for swarm monitoring |
| Gource visualization | Animated commit graph of swarm activity |

### 6.13 Docker Deployment

**Source inspiration:** ciana-parrot (one-command), nanobot (multi-service compose)

**docker-compose.yml services:**
```yaml
services:
  agent-gateway:     # Main agent + all channels
    build: .
    ports: ["18790:18790"]
    volumes:
      - ./workspace:/app/workspace
      - ./config.yaml:/app/config.yaml:ro
      - ./data:/app/data
    env_file: .env

  agent-api:         # OpenAI-compatible API server
    build: .
    command: ["serve"]
    ports: ["8900:8900"]

  agent-cli:         # Interactive CLI session
    build: .
    command: ["cli"]
    stdin_open: true
    tty: true
```

**One-command installer:**
```bash
curl -sSL https://raw.githubusercontent.com/.../install.sh | bash
```

### 6.14 Plugin Ecosystem

**Source inspiration:** OpenHarness (Claude Code compatibility), ClawTeam (hooks + plugins)

**Plugin types:**
- **Command plugins** — Add slash commands
- **Hook plugins** — PreToolUse/PostToolUse lifecycle hooks
- **Agent plugins** — Define agent archetypes for swarm
- **MCP plugins** — Expose MCP servers

**Compatibility:**
- Compatible with Claude Code / anthropics plugins format
- Compatible with ClawTeam event hooks (17+ event types)

### 6.15 Configuration

**Source inspiration:** ciana-parrot (YAML + Pydantic), nanobot (comprehensive config)

```yaml
# config.yaml — single file, all settings
agent:
  workspace: "./workspace"
  max_tool_iterations: 30
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
    lite: { provider: "groq", model: "llama-3.3-70b" }
    standard: { provider: "anthropic", model: "claude-sonnet-4-6" }
    advanced: { provider: "anthropic", model: "claude-opus-4-6" }
    expert: { provider: "anthropic", model: "claude-opus-4-6", extended_thinking: true }

channels:
  telegram: { enabled: true, token: "${TELEGRAM_BOT_TOKEN}", trigger: "@Agent", allowed_users: [123456] }
  discord: { enabled: false, token: "${DISCORD_BOT_TOKEN}" }
  api: { enabled: true, host: "0.0.0.0", port: 8900 }

scheduler:
  poll_interval: 60
  
gateway:
  host: "host.docker.internal"
  port: 9842
  token: "${GATEWAY_TOKEN}"
  bridges: { ... }

memory:
  dream: { interval_hours: 2 }

mcp_servers:
  filesystem: { transport: "stdio", command: "npx", args: ["-y", "@modelcontextprotocol/server-filesystem", "/data"] }

skills:
  enabled: true
  directories: ["./skills/builtin", "./workspace/skills"]

permissions:
  mode: "default"

logging:
  level: "INFO"

observability:
  langsmith: { enabled: false, api_key: "${LANGSMITH_API_KEY}", project: "lang-agent" }
  langfuse: { enabled: false }

swarm:
  enabled: false
  backend: "tmux"
  transport: "file"
```

---

## 7. Technical Design

### 7.1 LangGraph State Graph

```python
from langgraph.graph import StateGraph, MessagesState
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

class AgentState(MessagesState):
    """Extended state with platform-specific fields."""
    active_tier: str = "standard"
    session_id: str = ""
    channel: str = ""
    memory_context: str = ""  # Injected SOUL + USER + MEMORY
    tool_permissions: dict = {}

# Build the graph
graph = StateGraph(AgentState)
graph.add_node("agent", agent_node)           # LLM reasoning
graph.add_node("tools", tool_executor_node)   # Tool execution
graph.add_node("permission", permission_node) # Permission check
graph.add_conditional_edges("agent", should_use_tools)
graph.add_edge("permission", "tools")
graph.add_edge("tools", "agent")

# Compile with checkpointer
checkpointer = AsyncSqliteSaver.from_conn_string("data/checkpoints.db")
app = graph.compile(checkpointer=checkpointer)
```

### 7.2 Routing Chat Model

```python
from contextvars import ContextVar
from langchain_core.language_models import BaseChatModel

_active_tier: ContextVar[str] = ContextVar("active_tier", default="standard")

class RoutingChatModel(BaseChatModel):
    tiers: dict[str, BaseChatModel]
    
    async def _agenerate(self, messages, **kwargs):
        tier = _active_tier.get()
        model = self.tiers[tier]
        return await model._agenerate(messages, **kwargs)
    
    def bind_tools(self, tools, **kwargs):
        # Pre-bind all tiers
        bound_tiers = {k: v.bind_tools(tools, **kwargs) for k, v in self.tiers.items()}
        return RoutingChatModel(tiers=bound_tiers)
```

### 7.3 Retry with Exponential Backoff

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

### 7.4 Technology Stack

| Component | Technology | Rationale |
|-----------|-----------|-----------|
| Agent framework | LangGraph + DeepAgents | Checkpointing, streaming, state machines |
| LLM SDKs | anthropic, openai, langchain-* | Native for performance, langchain for breadth |
| Async runtime | asyncio | Python standard, LangGraph native |
| Config | Pydantic v2 + YAML | Type-safe validation, human-readable config |
| CLI | Typer + Rich | Modern Python CLI with beautiful TUI |
| HTTP client | httpx | Async-first, HTTP/2 support |
| Web framework | aiohttp | Lightweight async server for API + SSE |
| WebSocket | websockets + socketio | Real-time bidirectional channels |
| MCP | mcp SDK | Official Model Context Protocol support |
| Persistence | SQLite (aiosqlite) | Zero-config, LangGraph-native checkpointer |
| Sandbox | bubblewrap (bwrap) | Linux namespace isolation |
| Process mgmt | tmux + subprocess | Visual (tmux) + headless (subprocess) agent backends |
| Container | Docker + docker-compose | One-command deployment |
| Testing | pytest + pytest-asyncio | Async test support |
| Linting | ruff | Fast, comprehensive Python linting |
| Tracing | LangSmith / langfuse | Production observability |

---

## 8. Phased Roadmap

### Phase 0 — Foundation (Weeks 1-3)

**Goal:** Minimal working agent on LangGraph with single provider and Telegram

| Deliverable | Details |
|-------------|---------|
| LangGraph agent core | State graph, ReAct loop, SQLite checkpointer |
| Anthropic provider | Claude with streaming + extended thinking |
| Core tools | read, write, edit, glob, grep, exec, web_search, web_fetch |
| Telegram channel | Long-polling, markdown rendering, voice, photos |
| CLI channel | Interactive streaming with Rich |
| Memory files | SOUL.md, USER.md, MEMORY.md loading |
| Config system | YAML + Pydantic + env var expansion |
| Docker deployment | Dockerfile + docker-compose + install.sh |
| Session management | Per-thread SQLite checkpoints |
| Basic permissions | Filesystem sandbox + command allowlist |

**Exit criteria:** Agent converses on Telegram, uses tools, persists sessions, deploys via Docker.

### Phase 1 — Power Features (Weeks 4-6)

**Goal:** Multi-provider, model routing, scheduling, gateway, skills

| Deliverable | Details |
|-------------|---------|
| Multi-provider LLM | OpenAI, Gemini, Groq, Ollama, OpenRouter |
| Multi-tier routing | RoutingChatModel with switch_model tool |
| Host gateway | HTTP bridge server + client + 10 default bridges |
| Skills system | Auto-discovery, progressive loading, dependency filtering |
| Scheduled tasks | Cron + interval + one-shot with model tier override |
| MCP client | Stdio + HTTP transport, tool wrapping |
| Dream memory | 2-stage consolidation with Git versioning |
| Context compaction | Auto-compact when approaching context limit |
| OpenAI-compatible API | REST + SSE for web UI integration |
| Voice transcription | Whisper via Groq/OpenAI |

**Exit criteria:** Agent switches models for cost optimization, runs scheduled tasks, controls host apps, loads skills dynamically.

### Phase 2 — Ecosystem (Weeks 7-9)

**Goal:** Channels, plugins, permissions, observability

| Deliverable | Details |
|-------------|---------|
| Discord channel | Full integration with embeds |
| Slack channel | Bot token, threads, file upload |
| WebSocket channel | Real-time bidirectional streaming |
| Plugin system | Commands, hooks, agents (Claude Code compatible) |
| Permission system | Multi-level modes + path rules + approval dialogs |
| PreToolUse/PostToolUse | Hook lifecycle system |
| Cost tracking | Per-tier, per-session, per-agent token + cost |
| LangSmith/langfuse | Full tracing integration |
| Slash commands | /help, /new, /status, /dream, /stop, /model, etc. |
| Avatar emotion | SSE relay for 3D avatar display |

**Exit criteria:** Multi-channel deployment, plugin extensibility, production observability.

### Phase 3 — Swarm Intelligence (Weeks 10-14)

**Goal:** Multi-agent coordination, team management, harness phases

| Deliverable | Details |
|-------------|---------|
| Agent spawning | tmux + subprocess backends with CLI adapters |
| Team management | Create, discover, lifecycle, snapshots |
| Mailbox system | Send, broadcast, receive, peek, watch |
| Task board | Create, assign, dependencies, status tracking |
| Harness phases | discuss → plan → execute → verify → ship |
| Phase gates | Artifact, all-tasks-complete, human approval |
| Git worktree isolation | Per-agent branch + automatic merge |
| Team templates | TOML-based domain templates |
| Transport | File (default) + P2P (ZMQ) |
| Web dashboard | SSE real-time board + Gource visualization |
| Cost rollup | Per-agent + team aggregate |
| MCP server | Expose platform as MCP for external agents |

**Exit criteria:** Launch a 5-agent software development team from a template, complete a task autonomously.

### Phase 4 — Polish & Scale (Weeks 15+)

| Deliverable | Details |
|-------------|---------|
| WeChat, Feishu, Matrix channels | Additional channel integrations |
| Email channel | IMAP/SMTP with attachment support |
| WhatsApp bridge | Node.js bridge integration |
| Skill marketplace | ClawHub remote skill discovery + install |
| Postgres checkpointer | For production multi-instance deployment |
| Redis transport | For distributed swarm teams |
| Claude Code bridge | Full Claude Code sessions from Telegram |
| Natural language scheduling | "Every weekday at 9am" → cron |
| Advanced sandbox | Docker-in-Docker for untrusted code |
| Performance optimization | Connection pooling, response caching |

---

## 9. Non-Functional Requirements

### 9.1 Performance

| Metric | Target |
|--------|--------|
| Message-to-first-token latency | < 2s (standard tier) |
| Tool execution overhead | < 100ms per tool call |
| Concurrent sessions | 100+ per instance |
| Memory footprint | < 512MB idle, < 1GB active |
| Startup time | < 5s (Docker container ready) |

### 9.2 Reliability

| Requirement | Implementation |
|-------------|----------------|
| Crash recovery | SQLite checkpoints, session resume |
| API retry | Exponential backoff with jitter (3 retries) |
| Provider failover | Automatic tier downgrade on provider error |
| Task persistence | Survive container restarts |
| Memory durability | Git-versioned with Dream restore capability |

### 9.3 Security

| Requirement | Implementation |
|-------------|----------------|
| No shell injection | `subprocess.run(shell=False)` everywhere |
| Filesystem isolation | bwrap sandbox + workspace confinement |
| Gateway authentication | HMAC token + per-bridge ACL |
| Credential protection | Hardcoded deny for sensitive paths |
| Channel access control | Per-channel user allowlists |
| Input validation | Pydantic v2 for all external inputs |
| Docker non-root | Run as uid 1000, no privileged mode |

### 9.4 Extensibility

| Extension point | Mechanism |
|-----------------|-----------|
| New LLM provider | Implement `BaseLLMProvider` |
| New channel | Implement `AbstractChannel` |
| New tool | `@tool` decorator + register |
| New skill | Drop folder in `workspace/skills/` |
| New MCP server | Add to `mcp_servers` config |
| New bridge | Add to `gateway.bridges` config |
| New swarm template | Add TOML file to `templates/` |
| New plugin | Command/Hook/Agent plugin format |
| Custom hooks | 17+ event types with veto capability |

### 9.5 Testing Strategy

| Level | Coverage target | Tools |
|-------|----------------|-------|
| Unit tests | 80%+ core modules | pytest + pytest-asyncio |
| Integration tests | All tools, all providers | Real API calls (with mocking fallback) |
| E2E tests | Agent loop, channels, scheduling | Docker-based test environment |
| Security tests | Sandbox escapes, injection attacks | Custom security test suite |
| Load tests | Concurrent sessions, swarm scaling | locust / k6 |

---

## Appendix A: Feature Provenance

Every major feature maps back to a proven reference implementation:

| Feature | Primary Source | Secondary Source |
|---------|---------------|------------------|
| LangGraph agent core | ciana-parrot | — |
| Multi-tier routing | ciana-parrot | — |
| Host gateway bridge | ciana-parrot | — |
| Avatar emotion | ciana-parrot | — |
| Tool ecosystem (43+) | OpenHarness | nanobot |
| Permission system | OpenHarness | — |
| Plugin compatibility | OpenHarness | ClawTeam |
| CLAUDE.md discovery | OpenHarness | — |
| PreToolUse/PostToolUse hooks | OpenHarness | ClawTeam |
| Dream memory | nanobot | — |
| Progressive skill loading | nanobot | — |
| 15+ channels | nanobot | OpenHarness |
| Voice transcription | nanobot | ciana-parrot |
| OpenAI-compatible API | nanobot | — |
| Heartbeat system | nanobot | — |
| Multi-agent swarm | ClawTeam | — |
| Git worktree isolation | ClawTeam | — |
| Harness phases | ClawTeam | — |
| Team templates | ClawTeam | — |
| Inter-agent mailbox | ClawTeam | — |
| Cost tracking | ClawTeam | OpenHarness |
| Gource visualization | ClawTeam | — |
| Transport backends | ClawTeam | — |

---

## Appendix B: Why Not Fork?

| Option | Pros | Cons |
|--------|------|------|
| Fork ciana-parrot | Already on LangGraph/DeepAgents | Missing swarm, limited channels, small tool set |
| Fork OpenHarness | Most complete tool/permission system | Custom harness (not LangGraph), would need rewrite |
| Fork nanobot | Most channels, Dream memory, lightweight | Custom loop (not LangGraph), no swarm |
| Fork ClawTeam | Best swarm coordination | No LLM integration (CLI-only), no channels |
| **Build new (recommended)** | Best of all four, clean LangGraph foundation | More initial work |

**Recommendation:** Build from scratch on LangGraph/DeepAgents, pulling proven patterns (not code) from each reference. This avoids inheriting technical debt while capturing battle-tested designs.

---

*End of PRD*
