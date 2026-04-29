"""Agent setup — creates LangAgent agent using DeepAgents + LangChain middleware.

Architecture decision AD-14: Use create_deep_agent() with composable middleware
instead of a hand-built StateGraph. DeepAgents provides the graph, tools (filesystem,
todo, subagents), skills, memory, and backend. We add custom tools (web, cron,
gateway, model router) and middleware (retry, limits, summarization, context editing).
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from langchain.chat_models import init_chat_model
import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.store.memory import InMemoryStore

from . import middleware as _middleware  # noqa: F401 — patches skill YAML parser
from .config import AppConfig
from .observability.cost import CostTracker
from .tools.web import web_search, web_fetch, init_web_tools
from .tools.cron import schedule_task, list_tasks, cancel_task, init_cron_tools
from .tools.host import host_execute, init_host_tools
from .tools.model_router import switch_model, init_model_router_tools, RoutingChatModel
from .transcription import init_transcription

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PlatformBundle:
    """Aggregate return value of create_agent().

    Replaces the historical N-tuple to keep call sites stable as new
    subsystems get wired in (Swarm in 2B-I, future broadcaster channels, etc.).
    """
    agent: Any
    checkpointer: Any
    cost_tracker: Any
    mcp_client: Any | None = None
    subagent_registry: Any | None = None
    recovery_executor: Any | None = None
    broadcaster: Any | None = None
    swarm: Any | None = None


def _build_interrupt_on(config: AppConfig) -> dict | None:
    """Build the interrupt_on dict based on permission mode.

    - "default": write tools require approval, read tools don't
    - "auto": no interrupts (None)
    - "plan": write tools excluded from tool list entirely (handled elsewhere)
    """
    mode = getattr(config, "permissions", None)
    mode = mode.mode if mode else "default"

    if mode == "auto":
        return None  # No interrupts

    if mode == "plan":
        return None  # Plan mode handled by excluding write tools

    # Default mode: ask for write tools, allow read tools
    return {
        "exec": True,
        "host_execute": True,
        "write_file": {"allowed_decisions": ["approve", "edit", "reject"]},
        "edit_file": {"allowed_decisions": ["approve", "edit", "reject"]},
        "schedule_task": True,
        "cancel_task": True,
        "read_file": False,
        "glob": False,
        "grep": False,
        "web_search": False,
        "web_fetch": False,
        "switch_model": False,
        "list_tasks": False,
    }


def _build_middleware(config: AppConfig) -> list:
    """Build the middleware stack from config."""
    middleware = []

    try:
        from langchain.agents.middleware import ModelRetryMiddleware
        middleware.append(ModelRetryMiddleware(
            max_retries=3,
            retry_on=(TimeoutError, ConnectionError),
        ))
    except ImportError:
        logger.debug("ModelRetryMiddleware not available, skipping")

    try:
        from langchain.agents.middleware import ToolRetryMiddleware
        middleware.append(ToolRetryMiddleware(
            max_retries=2,
            backoff_factor=2.0,
            initial_delay=1.0,
        ))
    except ImportError:
        logger.debug("ToolRetryMiddleware not available, skipping")

    try:
        from langchain.agents.middleware import ModelCallLimitMiddleware
        middleware.append(ModelCallLimitMiddleware(thread_limit=50, run_limit=20))
    except ImportError:
        logger.debug("ModelCallLimitMiddleware not available, skipping")

    try:
        from langchain.agents.middleware import ToolCallLimitMiddleware
        middleware.append(ToolCallLimitMiddleware(thread_limit=100, run_limit=30))
    except ImportError:
        logger.debug("ToolCallLimitMiddleware not available, skipping")

    # Context management (summarization + tool output clearing)
    ctx_config = getattr(config, "context", None)
    if ctx_config:
        try:
            from langchain.agents.middleware import SummarizationMiddleware
            middleware.append(SummarizationMiddleware(
                model="gpt-4o-mini",
                trigger=("tokens", ctx_config.summarization_trigger_tokens
                         if hasattr(ctx_config, "summarization_trigger_tokens") else 100000),
                keep=("messages", ctx_config.keep_recent_messages
                      if hasattr(ctx_config, "keep_recent_messages") else 20),
            ))
        except ImportError:
            logger.debug("SummarizationMiddleware not available, skipping")

        try:
            from langchain.agents.middleware import ContextEditingMiddleware, ClearToolUsesEdit
            middleware.append(ContextEditingMiddleware(edits=[
                ClearToolUsesEdit(
                    trigger=ctx_config.clear_tool_outputs_trigger
                    if hasattr(ctx_config, "clear_tool_outputs_trigger") else 80000,
                    keep=ctx_config.clear_tool_outputs_keep
                    if hasattr(ctx_config, "clear_tool_outputs_keep") else 5,
                    placeholder="[cleared]",
                ),
            ]))
        except ImportError:
            logger.debug("ContextEditingMiddleware not available, skipping")

    if middleware:
        logger.info("Middleware stack: %s", [type(m).__name__ for m in middleware])

    return middleware


async def create_agent(config: AppConfig) -> "PlatformBundle":
    """Create and return the main LangAgent agent.

    Uses create_deep_agent() with middleware (AD-14).

    Returns:
        PlatformBundle: a frozen dataclass aggregating the agent and all
        wired subsystems (checkpointer, cost_tracker, mcp_client,
        subagent_registry, recovery_executor, broadcaster, swarm).

        ``broadcaster`` is included so ``main.py`` can attach the real
        ``EventHub`` via ``broadcaster.set_hub(event_hub)`` once it's been
        constructed. It is ``None`` when sub-agents are disabled. The
        ``swarm`` slot is populated by Phase 2B-I Task 2 when
        ``config.swarm.enabled``; otherwise it is ``None``.
    """
    # Initialize tool configs
    init_web_tools(config.web)
    init_cron_tools(config.scheduler)
    if config.gateway.enabled:
        init_host_tools(config.gateway)

    # Initialize transcription if enabled
    if config.transcription.enabled:
        init_transcription(config.transcription)

    # LLM provider
    provider_name = config.provider.name
    model_name = config.provider.model

    model_kwargs = {}
    if config.provider.temperature is not None:
        model_kwargs["temperature"] = config.provider.temperature
    if config.provider.max_tokens is not None:
        model_kwargs["max_tokens"] = config.provider.max_tokens
    if config.provider.base_url:
        model_kwargs["base_url"] = config.provider.base_url
    if config.provider.api_key:
        model_kwargs["api_key"] = config.provider.api_key

    base_model = init_chat_model(
        f"{provider_name}:{model_name}",
        **model_kwargs,
    )
    model = base_model
    logger.info("LLM provider: %s:%s", provider_name, model_name)

    # Workspace
    workspace = config.agent.workspace
    Path(workspace).mkdir(parents=True, exist_ok=True)

    # Memory files
    memory_files = []
    for fname in ["IDENTITY.md", "AGENT.md", "MEMORY.md"]:
        fpath = Path(workspace, fname)
        if fpath.exists():
            memory_files.append(fname)
            logger.info("Memory file loaded: %s", fpath)

    # Skills directory
    skills_dirs = []
    if config.skills.enabled:
        skills_path = Path(workspace, "skills")
        skills_path.mkdir(parents=True, exist_ok=True)
        skills_dirs.append("skills")
        logger.info("Skills directory: %s", skills_path)

    # Custom tools (beyond DeepAgents built-ins)
    custom_tools = [web_search, web_fetch, schedule_task, list_tasks, cancel_task]
    if config.gateway.enabled:
        custom_tools.append(host_execute)

    # Model router tiers
    tier_models: dict = {}

    if config.model_router.enabled and config.model_router.tiers:
        default_tier = config.model_router.default_tier
        for tier_name, tier_cfg in config.model_router.tiers.items():
            try:
                tier_kwargs = {}
                if tier_cfg.temperature is not None:
                    tier_kwargs["temperature"] = tier_cfg.temperature
                if tier_cfg.max_tokens is not None:
                    tier_kwargs["max_tokens"] = tier_cfg.max_tokens
                if tier_cfg.base_url:
                    tier_kwargs["base_url"] = tier_cfg.base_url
                if tier_cfg.api_key:
                    tier_kwargs["api_key"] = tier_cfg.api_key
                tier_models[tier_name] = init_chat_model(
                    f"{tier_cfg.name}:{tier_cfg.model}", **tier_kwargs
                )
                logger.info("Model tier initialized: %s (%s:%s)", tier_name, tier_cfg.name, tier_cfg.model)
            except Exception as e:
                logger.warning("Failed to init tier '%s': %s", tier_name, e)

        if tier_models:
            init_model_router_tools(tier_models, default_tier=default_tier)
            custom_tools.append(switch_model)
            tier_labels = {
                name: f"{cfg.name}:{cfg.model}"
                for name, cfg in config.model_router.tiers.items()
                if name in tier_models
            }
            model = RoutingChatModel(
                tier_models=tier_models,
                tier_labels=tier_labels,
                default_tier=default_tier,
            )
            logger.info("RoutingChatModel active (default_tier=%s, tiers=%s)",
                        default_tier, sorted(tier_models.keys()))

    # Cost tracker (shared between orchestration tools and API channel)
    cost_tracker = CostTracker()

    # Sub-agent system (orchestration tools + registry)
    subagent_registry = None
    recovery_executor = None
    broadcaster = None
    if config.subagent.enabled:
        from .subagent.registry import SubAgentRegistry
        from .subagent.tools import (
            init_orchestration_tools,
            spawn_agent, recall_agent, monitor_agents,
            assign_task, switch_agent_model, review_cost,
        )
        subagent_store = InMemoryStore()
        subagent_registry = SubAgentRegistry(subagent_store)

        # Phase 2A: real DeepAgents spawner + recovery executor
        from .subagent.broadcaster import EventBroadcaster
        from .subagent.spawner import DeepAgentsSpawner
        from .subagent.recovery_executor import RecoveryExecutor
        from .subagent.recovery import RecoveryChain

        # event_hub doesn't exist yet at this point; main.py attaches it via
        # broadcaster.set_hub(event_hub) once the API channel is built.
        broadcaster = EventBroadcaster(None)
        tools_by_name = {t.name: t for t in custom_tools}
        spawner = DeepAgentsSpawner(
            registry=subagent_registry,
            broadcaster=broadcaster,
            base_model=model,
            tools_by_name=tools_by_name,
        )
        recovery_executor = RecoveryExecutor(
            registry=subagent_registry,
            chain=RecoveryChain(max_retries=config.subagent.max_retries),
            spawner=spawner,
            broadcaster=broadcaster,
        )

        init_orchestration_tools(
            registry=subagent_registry,
            spawner=spawner.spawn,
            cost_tracker=cost_tracker,
        )
        custom_tools.extend([
            spawn_agent, recall_agent, monitor_agents,
            assign_task, switch_agent_model, review_cost,
        ])
        logger.info("Orchestration tools enabled (6 tools)")

    # MCP tools
    mcp_client = None
    mcp_tools = []
    if config.mcp_servers:
        try:
            from langchain_mcp_adapters.client import MultiServerMCPClient
            mcp_client = MultiServerMCPClient(config.mcp_servers)
            mcp_tools = await mcp_client.get_tools()
            logger.info("MCP tools loaded: %d", len(mcp_tools))
        except Exception as e:
            logger.warning("Failed to load MCP tools: %s", e)

    # Checkpointer
    data_dir = config.agent.data_dir
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    db_path = str(Path(data_dir, "checkpoints.db"))
    conn = await aiosqlite.connect(db_path)
    checkpointer = AsyncSqliteSaver(conn)
    await checkpointer.setup()

    # Build middleware stack
    middleware = _build_middleware(config)

    # Build interrupt_on for permissions
    interrupt_on = _build_interrupt_on(config)

    # Create agent via DeepAgents with middleware (AD-14)
    all_tools = custom_tools + mcp_tools

    agent = create_deep_agent(
        model=model,
        tools=all_tools,
        memory=memory_files if memory_files else None,
        skills=skills_dirs if skills_dirs else None,
        backend=FilesystemBackend(root_dir=workspace, virtual_mode=True),
        interrupt_on=interrupt_on,
        middleware=middleware,
        checkpointer=checkpointer,
    )

    logger.info(
        "LangAgent created (DeepAgents + middleware): %d custom tools, %d MCP tools, "
        "%d memory files, %d skill dirs, %d middleware",
        len(custom_tools), len(mcp_tools), len(memory_files),
        len(skills_dirs), len(middleware),
    )

    return PlatformBundle(
        agent=agent,
        checkpointer=checkpointer,
        mcp_client=mcp_client,
        subagent_registry=subagent_registry,
        cost_tracker=cost_tracker,
        recovery_executor=recovery_executor,
        broadcaster=broadcaster,
        swarm=None,  # Task 2 wires Swarm here when config.swarm.enabled
    )
