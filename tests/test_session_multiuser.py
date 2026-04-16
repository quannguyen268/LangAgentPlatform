"""Test multi-user session isolation via thread_id."""
import pytest
from unittest.mock import MagicMock
from pathlib import Path


def _make_router(tmp_path):
    from src.router import MessageRouter
    from src.config import (
        AppConfig, AgentConfig, ProviderConfig, SchedulerConfig,
        GatewayConfig, SkillsConfig, TranscriptionConfig,
        ChannelsConfig, TelegramChannelConfig, CLIConfig, APIConfig,
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    config = AppConfig(
        agent=AgentConfig(workspace=str(workspace), data_dir=str(data_dir)),
        provider=ProviderConfig(name="anthropic", model="test", api_key="test"),
        scheduler=SchedulerConfig(poll_interval=60),
        gateway=GatewayConfig(enabled=False),
        skills=SkillsConfig(enabled=False),
        transcription=TranscriptionConfig(enabled=False),
        channels=ChannelsConfig(
            telegram=TelegramChannelConfig(enabled=False),
            cli=CLIConfig(enabled=False),
            api=APIConfig(enabled=False),
        ),
    )
    return MessageRouter(agent=MagicMock(), config=config)


def test_thread_id_includes_user_id(tmp_path):
    router = _make_router(tmp_path)
    tid_alice = router.get_thread_id("telegram", "chat123", "alice")
    tid_bob = router.get_thread_id("telegram", "chat123", "bob")
    assert tid_alice != tid_bob
    assert "alice" in tid_alice
    assert "bob" in tid_bob


def test_thread_id_same_user_same_thread(tmp_path):
    router = _make_router(tmp_path)
    tid1 = router.get_thread_id("telegram", "chat123", "alice")
    tid2 = router.get_thread_id("telegram", "chat123", "alice")
    assert tid1 == tid2


def test_thread_id_format(tmp_path):
    router = _make_router(tmp_path)
    tid = router.get_thread_id("telegram", "chat123", "alice")
    assert tid.startswith("telegram_chat123_alice")


def test_thread_id_without_user_id_backwards_compat(tmp_path):
    router = _make_router(tmp_path)
    tid = router.get_thread_id("telegram", "chat123")
    assert tid.startswith("telegram_chat123")
    assert "None" not in tid
