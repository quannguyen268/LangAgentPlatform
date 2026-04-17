"""LangAgent Platform entry point - wires channels, agent, and scheduler."""

import asyncio
import logging
import signal

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
    agent, checkpointer, mcp_client = await create_agent(config)
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
        agent, config, checkpointer=checkpointer,
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
        from .observability.cost import CostTracker

        event_hub = EventHub()
        cost_tracker = CostTracker()

        api_config = config.channels.api
        api = APIChannel(
            host=api_config.host,
            port=api_config.port,
            workspace=config.agent.workspace,
            cost_tracker=cost_tracker,
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
        scheduler = Scheduler(agent, config, channels=channels_map)
        await scheduler.start()

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
    if scheduler:
        await scheduler.stop()
    for ch in channels:
        await ch.stop()
    if mcp_client:
        try:
            await mcp_client.close()
        except (OSError, RuntimeError):
            logger.debug("MCP client close failed (already closed or loop shutdown)")
    if checkpointer:
        try:
            await checkpointer.conn.close()
        except Exception:
            logger.debug("Checkpointer close failed (already closed)")

    logger.info("LangAgent Platform stopped.")


if __name__ == "__main__":
    asyncio.run(main())
