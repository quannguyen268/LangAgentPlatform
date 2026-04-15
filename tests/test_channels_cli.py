"""Tests for CLIChannel — imports, inheritance, name, send, send_file."""

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.channels.base import AbstractChannel, IncomingMessage
from src.channels.cli import CLIChannel


# ---------------------------------------------------------------------------
# test_cli_channel_imports
# ---------------------------------------------------------------------------

def test_cli_channel_imports():
    """CLIChannel module loads and the class is accessible."""
    from src.channels import cli  # noqa: F401 — just verify it imports cleanly
    assert hasattr(cli, "CLIChannel")


# ---------------------------------------------------------------------------
# test_cli_channel_is_abstract_channel
# ---------------------------------------------------------------------------

def test_cli_channel_is_abstract_channel():
    """CLIChannel inherits from AbstractChannel."""
    assert issubclass(CLIChannel, AbstractChannel)


# ---------------------------------------------------------------------------
# test_cli_channel_name
# ---------------------------------------------------------------------------

def test_cli_channel_name():
    """CLIChannel.name equals 'cli'."""
    assert CLIChannel.name == "cli"
    # Also verify on an instance
    ch = CLIChannel()
    assert ch.name == "cli"


# ---------------------------------------------------------------------------
# test_cli_channel_send
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cli_channel_send():
    """send() renders markdown via Console without crashing and returns SendResult."""
    from src.channels.base import SendResult

    ch = CLIChannel()
    mock_console = MagicMock()
    ch._console = mock_console

    result = await ch.send("local", "**Hello**, world!")

    mock_console.print.assert_called_once()
    assert result is not None
    assert isinstance(result, SendResult)
    assert result.message_id is not None


@pytest.mark.asyncio
async def test_cli_channel_send_empty_returns_none():
    """send() with empty text returns None and does not call console."""
    ch = CLIChannel()
    mock_console = MagicMock()
    ch._console = mock_console

    result = await ch.send("local", "")

    mock_console.print.assert_not_called()
    assert result is None


# ---------------------------------------------------------------------------
# test_cli_channel_send_file
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cli_channel_send_file(tmp_path):
    """send_file() prints path and size for an existing file."""
    ch = CLIChannel()
    mock_console = MagicMock()
    ch._console = mock_console

    test_file = tmp_path / "hello.txt"
    test_file.write_text("hello world")

    await ch.send_file("local", str(test_file), caption="A test file")

    assert mock_console.print.call_count >= 1
    # Verify that the filename appears in one of the printed strings
    all_printed = " ".join(str(c) for c in mock_console.print.call_args_list)
    assert "hello.txt" in all_printed


@pytest.mark.asyncio
async def test_cli_channel_send_file_not_found():
    """send_file() with a non-existent path prints an error message."""
    ch = CLIChannel()
    mock_console = MagicMock()
    ch._console = mock_console

    await ch.send_file("local", "/nonexistent/path/file.txt")

    mock_console.print.assert_called_once()
    printed = str(mock_console.print.call_args_list[0])
    assert "not found" in printed.lower() or "File not found" in printed
