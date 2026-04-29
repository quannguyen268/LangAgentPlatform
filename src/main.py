"""LangAgent Platform entry point - wires channels, agent, and scheduler."""

import asyncio
import logging
import signal
from pathlib import Path

from .avatar import AvatarBridge
from .gateway.bridges.claude_code import setup_bridge
from .config import load_config
from .agent import create_agent
from .middleware import init_middleware_bridges
from .router import MessageRouter
from .scheduler import Scheduler
from .channels.telegram import TelegramChannel
from .channels.cli import CLIChannel
from .channels.api import APIChannel

logger = logging.getLogger(__name__)


async def main() -> None:
    # Load config
    config = load_config()

    # Logging
    logging.basicConfig(
        level=getattr(logging, config.logging.level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logger.info("LangAgent Platform starting...")

    # Initialize bridge availability for skill filtering
    if config.gateway.enabled:
        init_middleware_bridges(config.gateway)

    # Create agent
    bundle = await create_agent(config)
    logger.info("Agent ready")

    # Avatar emotion system (relays via gateway SSE)
    pre_hook = None
    post_hook = None
    if config.avatar.enabled:
        avatar = AvatarBridge(config.avatar, config.gateway)
        avatar.init_llm()
        pre_hook = avatar.on_user_message
        post_hook = avatar.on_agent_response
        logger.info("Avatar emotion system enabled (tier: %s)", config.avatar.tier)

    # Router
    router = MessageRouter(
        bundle.agent, config, checkpointer=bundle.checkpointer,
        pre_hook=pre_hook, post_hook=post_hook,
    )

    # Channels
    channels = []

    if config.channels.telegram.enabled:
        tg_config = config.channels.telegram
        tg = TelegramChannel(tg_config)

        await setup_bridge(config, tg)

        async def tg_callback(msg):
            return await router.handle_message(msg, tg_config)

        tg.on_message(tg_callback)
        channels.append(tg)
        logger.info("Telegram channel configured")

    if config.channels.cli.enabled:
        cli_config = config.channels.cli
        cli = CLIChannel(user_id=cli_config.user_id)

        async def cli_callback(msg):
            return await router.handle_message(msg, cli_config)

        cli.on_message(cli_callback)
        channels.append(cli)
        logger.info("CLI channel configured")

    if config.channels.api.enabled:
        from .api.websocket import EventHub

        event_hub = EventHub()

        # Attach the real hub to the sub-agent broadcaster so lifecycle
        # events (spawn/progress/complete/failed) actually reach API clients.
        if bundle.broadcaster is not None:
            bundle.broadcaster.set_hub(event_hub)

        api_config = config.channels.api
        api = APIChannel(
            host=api_config.host,
            port=api_config.port,
            workspace=config.agent.workspace,
            cost_tracker=bundle.cost_tracker,
            event_hub=event_hub,
        )

        async def api_callback(msg):
            return await router.handle_message(msg, api_config)

        api.on_message(api_callback)
        channels.append(api)
        logger.info("API channel configured")

    # Start channels
    for ch in channels:
        await ch.start()
        logger.info("Channel started: %s", ch.name)

    # Scheduler (with channel references for sending results)
    scheduler = None
    if config.scheduler.enabled:
        channels_map = {ch.name: ch for ch in channels}
        scheduler = Scheduler(bundle.agent, config, channels=channels_map)
        await scheduler.start()

    # Health monitor (background task checking sub-agent heartbeats)
    health_task = None
    if config.subagent.enabled and bundle.subagent_registry is not None:
        from .subagent.health import HealthMonitor
        monitor = HealthMonitor(
            registry=bundle.subagent_registry,
            heartbeat_timeout=config.subagent.heartbeat_timeout,
            task_timeout=config.subagent.task_timeout,
            max_iterations=config.subagent.max_iterations,
        )

        async def health_loop():
            interval = config.subagent.health_check_interval
            while True:
                await asyncio.sleep(interval)
                try:
                    # Pull fresh heartbeat + iteration from BaseStore so the
                    # monitor sees what sub-agents have actually written.
                    await bundle.subagent_registry.sync_from_store()
                    unhealthy = monitor.check_all()
                    if unhealthy:
                        logger.warning("Unhealthy sub-agents: %s", unhealthy)
                        if bundle.recovery_executor is None:
                            logger.warning(
                                "No recovery_executor wired; %d unhealthy agent(s) ignored",
                                len(unhealthy),
                            )
                        else:
                            # Run recoveries concurrently so a slow one doesn't
                            # stall the rest of this tick or push the next tick.
                            items = list(unhealthy.items())
                            results = await asyncio.gather(
                                *(
                                    bundle.recovery_executor.handle_failure(
                                        aid, reason=reason.value,
                                    )
                                    for aid, reason in items
                                ),
                                return_exceptions=True,
                            )
                            for (aid, _), res in zip(items, results):
                                if isinstance(res, Exception):
                                    logger.error(
                                        "Recovery failed for %s: %s", aid, res,
                                    )
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error("Health monitor error: %s", e)

        health_task = asyncio.create_task(health_loop())
        logger.info("Health monitor started (interval: %.1fs)",
                    config.subagent.health_check_interval)

    # Dream process (periodic memory reflection)
    dream_task = None
    if config.dream.enabled:
        from .memory.dream import DreamProcess
        dream_proc = DreamProcess(
            workspace=config.agent.workspace,
            memory_dir=str(Path(config.agent.workspace, "memory")),
            max_batch_size=config.dream.max_batch_size,
            max_iterations=config.dream.max_iterations,
        )

        async def dream_loop():
            interval = config.dream.interval_hours * 3600
            while True:
                await asyncio.sleep(interval)
                try:
                    from langchain.chat_models import init_chat_model
                    dream_model_name = config.dream.model or f"{config.provider.name}:{config.provider.model}"
                    dream_model = init_chat_model(dream_model_name)
                    result = await dream_proc.run(model=dream_model)
                    logger.info("Dream completed: %s", result)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error("Dream failed: %s", e)

        dream_task = asyncio.create_task(dream_loop())
        logger.info("Dream process enabled (interval: %.1fh)", config.dream.interval_hours)

    logger.info("LangAgent Platform is running. Press Ctrl+C to stop.")

    # Graceful shutdown
    stop_event = asyncio.Event()

    def _signal_handler():
        logger.info("Shutdown signal received")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    # Wait for shutdown
    await stop_event.wait()

    # Cleanup
    logger.info("Shutting down...")
    if health_task:
        health_task.cancel()
        try:
            await health_task
        except asyncio.CancelledError:
            pass
    # Deregister all sub-agents so their tasks don't leak as orphan coroutines
    if bundle.subagent_registry is not None:
        await bundle.subagent_registry.shutdown_all()
    if dream_task:
        dream_task.cancel()
        try:
            await dream_task
        except asyncio.CancelledError:
            pass
    if scheduler:
        await scheduler.stop()
    for ch in channels:
        await ch.stop()
    if bundle.mcp_client:
        try:
            await bundle.mcp_client.close()
        except (OSError, RuntimeError):
            logger.debug("MCP client close failed (already closed or loop shutdown)")
    if bundle.checkpointer:
        try:
            await bundle.checkpointer.conn.close()
        except Exception:
            logger.debug("Checkpointer close failed (already closed)")

    logger.info("LangAgent Platform stopped.")


if __name__ == "__main__":
    asyncio.run(main())
