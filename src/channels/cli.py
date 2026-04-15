"""Interactive CLI channel using Rich for markdown rendering and prompt_toolkit for input."""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.markdown import Markdown

from .base import AbstractChannel, IncomingMessage, SendResult


class CLIChannel(AbstractChannel):
    """CLI channel — runs an interactive REPL in the terminal."""

    name: str = "cli"

    def __init__(self, user_id: str = "cli-user") -> None:
        self._user_id = user_id
        self._console = Console()
        self._running = False
        self._callback = None

    # ------------------------------------------------------------------
    # AbstractChannel implementation
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """No background tasks to start for the CLI channel."""
        self._running = True

    async def stop(self) -> None:
        """Stop the CLI channel."""
        self._running = False

    async def send(
        self,
        chat_id: str,
        text: str,
        *,
        reply_to_message_id: Optional[str] = None,
        disable_notification: bool = False,
    ) -> Optional[SendResult]:
        """Render markdown text to the terminal via Rich."""
        if not text:
            return None
        self._console.print(Markdown(text))
        return SendResult(message_id=str(uuid.uuid4()))

    async def send_file(self, chat_id: str, path: str, caption: str = "") -> None:
        """Print file path and size information to the terminal."""
        p = Path(path)
        if p.exists():
            size = p.stat().st_size
            self._console.print(
                f"[bold]File:[/bold] {p.resolve()}  "
                f"[bold]Size:[/bold] {size:,} bytes"
            )
            if caption:
                self._console.print(f"[italic]{caption}[/italic]")
        else:
            self._console.print(f"[red]File not found:[/red] {path}")

    # ------------------------------------------------------------------
    # Interactive REPL
    # ------------------------------------------------------------------

    async def run_interactive(self) -> None:
        """Async REPL loop — reads input with prompt_toolkit and dispatches messages."""
        from prompt_toolkit import PromptSession
        from prompt_toolkit.history import FileHistory

        history_dir = Path.home() / ".langagent"
        history_dir.mkdir(parents=True, exist_ok=True)
        history_file = history_dir / "cli_history"

        session: PromptSession = PromptSession(
            history=FileHistory(str(history_file)),
        )

        self._console.print(
            "[bold green]LangAgent CLI[/bold green]  "
            "(Ctrl+D or Ctrl+C to quit)\n"
        )

        while True:
            try:
                raw = await session.prompt_async("You: ")
            except EOFError:
                # Ctrl+D — graceful exit
                self._console.print("\n[dim]Goodbye.[/dim]")
                break
            except KeyboardInterrupt:
                # Ctrl+C — graceful exit
                self._console.print("\n[dim]Interrupted.[/dim]")
                break

            text = raw.strip()
            if not text:
                continue

            if self._callback is None:
                self._console.print("[yellow]No message handler registered.[/yellow]")
                continue

            msg = IncomingMessage(
                channel="cli",
                chat_id="local",
                user_id=self._user_id,
                user_name="CLI User",
                text=text,
                is_private=True,
            )

            try:
                response = await self._callback(msg)
                if response is not None:
                    reply_text = getattr(response, "text", str(response))
                    if reply_text:
                        await self.send("local", reply_text)
            except Exception as exc:  # noqa: BLE001
                self._console.print(f"[red]Error:[/red] {exc}")
