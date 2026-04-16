# Phase 0: Fork & Foundation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fork ciana-parrot, rebrand to LangAgent Platform, verify all inherited features work, add CLI and OpenAI-compatible API channels.

**Architecture:** Clone ciana-parrot into the repo root as `src/`, rename all references, verify each subsystem (LLM, Telegram, gateway, skills, MCP, scheduling, memory, Docker), then add two new channel implementations.

**Tech Stack:** Python 3.13, LangGraph, DeepAgents, LangChain, Pydantic v2, aiohttp (API), Rich + prompt_toolkit (CLI), Docker

**Spec Reference:** `docs/superpowers/specs/2026-04-15-langagent-platform-design.md` — Sections 5, 11, 22, 23, 25 (Phase 0)

**Prerequisites:** ciana-parrot repo cloned at `../ciana-parrot/` (reference)

---

## File Structure

### Files to copy from ciana-parrot (then rename)

```
ciana-parrot/src/           → src/          (main source)
ciana-parrot/workspace/     → workspace/    (agent workspace)
ciana-parrot/config.yaml    → config.yaml   (default config)
ciana-parrot/Dockerfile     → Dockerfile
ciana-parrot/docker-compose.yml → docker-compose.yml
ciana-parrot/pyproject.toml → pyproject.toml
ciana-parrot/install.sh     → install.sh
ciana-parrot/skills/        → skills/       (built-in skills, if exists)
```

### New files to create

```
src/channels/cli.py         — CLI channel (Rich TUI)
src/channels/api.py         — OpenAI-compatible API channel
tests/                      — Test directory
tests/conftest.py           — Shared fixtures
tests/test_config.py        — Config loading tests
tests/test_channels_cli.py  — CLI channel tests
tests/test_channels_api.py  — API channel tests
```

---

### Task 1: Fork ciana-parrot into repo

**Files:**
- Copy: entire `ciana-parrot/` source tree into repo root
- Modify: `pyproject.toml` (rename project)
- Modify: `src/__init__.py` (rename module)

- [ ] **Step 1: Copy source files from ciana-parrot**

```bash
# From the repo root (lang-agent-platform/)
cp -r ciana-parrot/src/* src/ 2>/dev/null || mkdir -p src && cp -r ciana-parrot/src/* src/
cp -r ciana-parrot/workspace . 2>/dev/null || true
cp ciana-parrot/config.yaml . 2>/dev/null || true
cp ciana-parrot/config.local.yaml.example . 2>/dev/null || true
cp ciana-parrot/Dockerfile . 2>/dev/null || true
cp ciana-parrot/docker-compose.yml . 2>/dev/null || true
cp ciana-parrot/pyproject.toml . 2>/dev/null || true
cp ciana-parrot/install.sh . 2>/dev/null || true
cp -r ciana-parrot/skills . 2>/dev/null || true
```

- [ ] **Step 2: Rename project in pyproject.toml**

Change the `[project]` name from `ciana-parrot` (or whatever it's called) to `langagent-platform`:

```toml
[project]
name = "langagent-platform"
version = "0.1.0"
description = "LangAgent Platform — Production-grade AI agent platform on LangGraph"
requires-python = ">=3.13"
```

Also update the `[project.scripts]` entry point:

```toml
[project.scripts]
langagent = "src.main:main"
```

- [ ] **Step 3: Update src/__init__.py**

```python
"""LangAgent Platform — Production-grade AI agent platform on LangGraph."""
```

- [ ] **Step 4: Create tests directory with conftest.py**

```bash
mkdir -p tests
```

Create `tests/__init__.py`:
```python
```

Create `tests/conftest.py`:
```python
"""Shared test fixtures for LangAgent Platform."""
import asyncio
import pytest


@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for the test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
```

- [ ] **Step 5: Commit the fork**

```bash
git add src/ workspace/ config.yaml pyproject.toml Dockerfile docker-compose.yml tests/ install.sh skills/
git commit -m "feat: fork ciana-parrot as LangAgent Platform foundation"
```

---

### Task 2: Verify config loading

**Files:**
- Read: `src/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write config loading test**

```python
# tests/test_config.py
"""Test configuration loading and validation."""
import pytest
from pathlib import Path


def test_config_loads_from_yaml(tmp_path):
    """Verify config.yaml can be parsed and validated."""
    config_content = """
agent:
  workspace: "./workspace"
  data_dir: "./data"

provider:
  name: "anthropic"
  model: "claude-sonnet-4-6"
  api_key: "test-key"
  temperature: 0
  max_tokens: 8192

channels:
  telegram:
    enabled: false

scheduler:
  poll_interval: 60

gateway:
  enabled: false

skills:
  enabled: true

transcription:
  enabled: false
"""
    config_file = tmp_path / "config.yaml"
    config_file.write_text(config_content)

    from src.config import load_config
    config = load_config(str(config_file))
    assert config.provider.name == "anthropic"
    assert config.provider.model == "claude-sonnet-4-6"
    assert config.agent.workspace == "./workspace"


def test_config_env_var_expansion(tmp_path, monkeypatch):
    """Verify ${ENV_VAR} syntax is expanded."""
    monkeypatch.setenv("TEST_API_KEY", "sk-test-123")
    config_content = """
agent:
  workspace: "./workspace"
  data_dir: "./data"

provider:
  name: "anthropic"
  model: "claude-sonnet-4-6"
  api_key: "${TEST_API_KEY}"

channels:
  telegram:
    enabled: false

scheduler:
  poll_interval: 60

gateway:
  enabled: false

skills:
  enabled: true

transcription:
  enabled: false
"""
    config_file = tmp_path / "config.yaml"
    config_file.write_text(config_content)

    from src.config import load_config
    config = load_config(str(config_file))
    assert config.provider.api_key == "sk-test-123"
```

- [ ] **Step 2: Run test to verify it works**

```bash
pip install -e ".[dev]" 2>/dev/null || pip install -e .
pytest tests/test_config.py -v
```

Expected: PASS (config loading should work from ciana-parrot)

- [ ] **Step 3: Commit**

```bash
git add tests/test_config.py
git commit -m "test: add config loading verification tests"
```

---

### Task 3: Verify LangGraph agent loop

**Files:**
- Read: `src/agent.py`
- Create: `tests/test_agent_creation.py`

- [ ] **Step 1: Write agent creation test**

```python
# tests/test_agent_creation.py
"""Test that the LangGraph agent can be created."""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from pathlib import Path


@pytest.mark.asyncio
async def test_agent_creates_successfully(tmp_path):
    """Verify create_cianaparrot_agent returns an agent, checkpointer, and mcp_client."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "IDENTITY.md").write_text("I am a test agent.")
    (workspace / "AGENT.md").write_text("Behave well.")
    (workspace / "MEMORY.md").write_text("No memories yet.")
    (workspace / "skills").mkdir()

    data_dir = tmp_path / "data"
    data_dir.mkdir()

    from src.config import AppConfig, ProviderConfig, AgentConfig, SchedulerConfig, GatewayConfig, SkillsConfig, TranscriptionConfig

    config = AppConfig(
        agent=AgentConfig(workspace=str(workspace), data_dir=str(data_dir)),
        provider=ProviderConfig(name="anthropic", model="claude-sonnet-4-6", api_key="test-key"),
        scheduler=SchedulerConfig(poll_interval=60),
        gateway=GatewayConfig(enabled=False),
        skills=SkillsConfig(enabled=True),
        transcription=TranscriptionConfig(enabled=False),
        channels={},
    )

    # Mock the LLM so we don't need a real API key
    with patch("src.agent.init_chat_model") as mock_init:
        mock_model = MagicMock()
        mock_model.bind_tools = MagicMock(return_value=mock_model)
        mock_init.return_value = mock_model

        from src.agent import create_cianaparrot_agent
        agent, checkpointer, mcp_client = await create_cianaparrot_agent(config)

        assert agent is not None
        assert checkpointer is not None
        assert mcp_client is None  # No MCP servers configured
```

- [ ] **Step 2: Run test**

```bash
pytest tests/test_agent_creation.py -v
```

Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_agent_creation.py
git commit -m "test: verify LangGraph agent creation works"
```

---

### Task 4: Verify Telegram channel

**Files:**
- Read: `src/channels/telegram/channel.py`
- Create: `tests/test_channel_telegram.py`

- [ ] **Step 1: Write Telegram channel import test**

```python
# tests/test_channel_telegram.py
"""Test Telegram channel can be imported and instantiated."""
import pytest


def test_telegram_channel_imports():
    """Verify Telegram channel module loads."""
    from src.channels.telegram.channel import TelegramChannel
    assert TelegramChannel is not None


def test_telegram_formatting_imports():
    """Verify Telegram formatting module loads."""
    from src.channels.telegram.formatting import markdown_to_telegram_html
    assert markdown_to_telegram_html is not None


def test_telegram_formatting_basic():
    """Verify basic markdown to Telegram HTML conversion."""
    from src.channels.telegram.formatting import markdown_to_telegram_html
    result = markdown_to_telegram_html("**bold** and *italic*")
    assert "<b>" in result or "<strong>" in result
```

- [ ] **Step 2: Run test**

```bash
pytest tests/test_channel_telegram.py -v
```

Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_channel_telegram.py
git commit -m "test: verify Telegram channel imports and formatting"
```

---

### Task 5: Verify gateway, skills, scheduler, and tools

**Files:**
- Create: `tests/test_subsystems.py`

- [ ] **Step 1: Write subsystem verification tests**

```python
# tests/test_subsystems.py
"""Verify all inherited subsystems import correctly."""
import pytest


def test_gateway_client_imports():
    from src.gateway.client import GatewayClient
    assert GatewayClient is not None


def test_gateway_server_imports():
    from src.gateway.server import GatewayServer
    assert GatewayServer is not None


def test_scheduler_imports():
    from src.scheduler import Scheduler
    assert Scheduler is not None


def test_web_tools_import():
    from src.tools.web import web_search, web_fetch
    assert web_search is not None
    assert web_fetch is not None


def test_cron_tools_import():
    from src.tools.cron import schedule_task, list_tasks, cancel_task
    assert schedule_task is not None


def test_host_tools_import():
    from src.tools.host import host_execute
    assert host_execute is not None


def test_model_router_imports():
    from src.tools.model_router import RoutingChatModel, switch_model
    assert RoutingChatModel is not None
    assert switch_model is not None


def test_middleware_imports():
    from src.middleware import patch_skill_parser
    # Just verify it doesn't crash on import


def test_events_imports():
    from src.events import StreamEvent
    assert StreamEvent is not None


def test_store_imports():
    from src.store import SessionStore
    assert SessionStore is not None


def test_backend_imports():
    from src.backend import WorkspaceShellBackend
    assert WorkspaceShellBackend is not None


def test_channel_base_imports():
    from src.channels.base import AbstractChannel
    assert AbstractChannel is not None
```

- [ ] **Step 2: Run all subsystem tests**

```bash
pytest tests/test_subsystems.py -v
```

Expected: PASS for all. If any fail, fix the import path (ciana-parrot may use different class names).

- [ ] **Step 3: Fix any import failures**

If tests fail, read the actual source files and fix the import names. The class names may differ from what's assumed above. For example, if `GatewayClient` is actually called `AsyncGatewayClient`, update the test.

- [ ] **Step 4: Commit**

```bash
git add tests/test_subsystems.py
git commit -m "test: verify all inherited subsystems import correctly"
```

---

### Task 6: Add CLI channel

**Files:**
- Create: `src/channels/cli.py`
- Create: `tests/test_channels_cli.py`

- [ ] **Step 1: Write failing test for CLI channel**

```python
# tests/test_channels_cli.py
"""Test CLI channel implementation."""
import pytest
from unittest.mock import AsyncMock


def test_cli_channel_imports():
    from src.channels.cli import CLIChannel
    assert CLIChannel is not None


def test_cli_channel_is_abstract_channel():
    from src.channels.cli import CLIChannel
    from src.channels.base import AbstractChannel
    assert issubclass(CLIChannel, AbstractChannel)


@pytest.mark.asyncio
async def test_cli_channel_send():
    from src.channels.cli import CLIChannel
    channel = CLIChannel()
    # send should not raise
    result = await channel.send("test_thread", "Hello, world!")
    assert result is not None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_channels_cli.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'src.channels.cli'`

- [ ] **Step 3: Implement CLI channel**

```python
# src/channels/cli.py
"""CLI channel — interactive Rich TUI for local use."""
import asyncio
import logging
from dataclasses import dataclass
from typing import Callable, Awaitable

from rich.console import Console
from rich.markdown import Markdown

from .base import AbstractChannel, IncomingMessage, SendResult

logger = logging.getLogger(__name__)
console = Console()


@dataclass
class CLIChannelConfig:
    enabled: bool = False
    user_id: str = "cli_user"


class CLIChannel(AbstractChannel):
    """Interactive CLI channel using Rich for rendering."""

    def __init__(self, config: CLIChannelConfig | None = None):
        self.config = config or CLIChannelConfig()
        self._callback: Callable[[IncomingMessage], Awaitable[None]] | None = None
        self._running = False

    async def start(self) -> None:
        self._running = True
        logger.info("CLI channel started")

    async def stop(self) -> None:
        self._running = False
        logger.info("CLI channel stopped")

    async def send(self, thread_id: str, content: str, **kwargs) -> SendResult:
        """Print response to terminal with Rich markdown rendering."""
        console.print()
        console.print(Markdown(content))
        console.print()
        return SendResult(success=True, message_id="cli")

    async def send_file(self, thread_id: str, file: bytes, filename: str, **kwargs) -> SendResult:
        """Print file info to terminal."""
        console.print(f"[dim]File: {filename} ({len(file)} bytes)[/dim]")
        return SendResult(success=True, message_id="cli")

    def on_message(self, callback: Callable[[IncomingMessage], Awaitable[None]]):
        self._callback = callback

    async def run_interactive(self):
        """Run interactive REPL loop. Call this from main."""
        from prompt_toolkit import PromptSession
        from prompt_toolkit.history import FileHistory
        from pathlib import Path

        history_path = Path.home() / ".langagent" / "cli_history"
        history_path.parent.mkdir(parents=True, exist_ok=True)

        session = PromptSession(history=FileHistory(str(history_path)))
        thread_id = f"cli_local_{self.config.user_id}_s0"

        console.print("[bold green]LangAgent Platform[/bold green] — Type your message (Ctrl+D to exit)")
        console.print()

        while self._running:
            try:
                user_input = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: session.prompt("You: ")
                )
                if not user_input.strip():
                    continue

                if self._callback:
                    msg = IncomingMessage(
                        channel="cli",
                        chat_id="local",
                        user_id=self.config.user_id,
                        text=user_input.strip(),
                        thread_id=thread_id,
                    )
                    await self._callback(msg)

            except (EOFError, KeyboardInterrupt):
                console.print("\n[dim]Goodbye![/dim]")
                break
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_channels_cli.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/channels/cli.py tests/test_channels_cli.py
git commit -m "feat: add CLI channel with Rich TUI rendering"
```

---

### Task 7: Add OpenAI-compatible API channel

**Files:**
- Create: `src/channels/api.py`
- Create: `tests/test_channels_api.py`

- [ ] **Step 1: Write failing test for API channel**

```python
# tests/test_channels_api.py
"""Test OpenAI-compatible API channel."""
import pytest
import json


def test_api_channel_imports():
    from src.channels.api import APIChannel
    assert APIChannel is not None


def test_api_channel_is_abstract_channel():
    from src.channels.api import APIChannel
    from src.channels.base import AbstractChannel
    assert issubclass(APIChannel, AbstractChannel)


@pytest.mark.asyncio
async def test_api_chat_completion_format():
    """Verify the API returns OpenAI-compatible format."""
    from src.channels.api import format_chat_completion
    result = format_chat_completion(
        content="Hello!",
        model="claude-sonnet-4-6",
        usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    )
    assert result["object"] == "chat.completion"
    assert result["choices"][0]["message"]["content"] == "Hello!"
    assert result["choices"][0]["message"]["role"] == "assistant"
    assert result["usage"]["total_tokens"] == 15


@pytest.mark.asyncio
async def test_api_sse_format():
    """Verify SSE streaming format."""
    from src.channels.api import format_sse_chunk
    chunk = format_sse_chunk(delta="Hello", model="claude-sonnet-4-6")
    assert chunk["object"] == "chat.completion.chunk"
    assert chunk["choices"][0]["delta"]["content"] == "Hello"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_channels_api.py -v
```

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement API channel**

```python
# src/channels/api.py
"""OpenAI-compatible API channel — REST + SSE streaming."""
import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Callable, Awaitable

from aiohttp import web

from .base import AbstractChannel, IncomingMessage, SendResult

logger = logging.getLogger(__name__)


@dataclass
class APIChannelConfig:
    enabled: bool = True
    host: str = "0.0.0.0"
    port: int = 8900
    auth_token: str = ""


def format_chat_completion(content: str, model: str, usage: dict | None = None) -> dict:
    """Format a non-streaming response in OpenAI chat completion format."""
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": usage or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def format_sse_chunk(delta: str, model: str, finish_reason: str | None = None) -> dict:
    """Format a single SSE streaming chunk."""
    choice = {"index": 0, "delta": {}, "finish_reason": finish_reason}
    if delta:
        choice["delta"]["content"] = delta
    if finish_reason is None and not delta:
        choice["delta"]["role"] = "assistant"
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [choice],
    }


class APIChannel(AbstractChannel):
    """OpenAI-compatible REST API with SSE streaming."""

    def __init__(self, config: APIChannelConfig | None = None):
        self.config = config or APIChannelConfig()
        self._callback: Callable[[IncomingMessage], Awaitable[None]] | None = None
        self._app = web.Application()
        self._runner: web.AppRunner | None = None
        self._pending_responses: dict[str, asyncio.Queue] = {}
        self._setup_routes()

    def _setup_routes(self):
        self._app.router.add_post("/v1/chat/completions", self._handle_chat)
        self._app.router.add_get("/v1/models", self._handle_models)
        self._app.router.add_get("/health", self._handle_health)

    async def start(self) -> None:
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.config.host, self.config.port)
        await site.start()
        logger.info("API channel listening on %s:%d", self.config.host, self.config.port)

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()
        logger.info("API channel stopped")

    async def send(self, thread_id: str, content: str, **kwargs) -> SendResult:
        """Push response to the pending queue for the requesting thread."""
        if thread_id in self._pending_responses:
            await self._pending_responses[thread_id].put(content)
        return SendResult(success=True, message_id="api")

    async def send_file(self, thread_id: str, file: bytes, filename: str, **kwargs) -> SendResult:
        return SendResult(success=True, message_id="api")

    def on_message(self, callback: Callable[[IncomingMessage], Awaitable[None]]):
        self._callback = callback

    async def _handle_health(self, request: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

    async def _handle_models(self, request: web.Request) -> web.Response:
        return web.json_response({
            "object": "list",
            "data": [{"id": "langagent", "object": "model", "owned_by": "langagent-platform"}],
        })

    async def _handle_chat(self, request: web.Request) -> web.Response:
        """Handle /v1/chat/completions requests."""
        body = await request.json()
        messages = body.get("messages", [])
        stream = body.get("stream", False)
        user_id = body.get("user", "api_user")

        if not messages:
            return web.json_response({"error": "messages required"}, status=400)

        last_message = messages[-1].get("content", "")
        thread_id = f"api_{user_id}_s0"

        # Create response queue
        response_queue: asyncio.Queue = asyncio.Queue()
        self._pending_responses[thread_id] = response_queue

        try:
            # Send message to agent
            if self._callback:
                msg = IncomingMessage(
                    channel="api",
                    chat_id=user_id,
                    user_id=user_id,
                    text=last_message,
                    thread_id=thread_id,
                )
                # Fire and don't await — response comes via send()
                asyncio.create_task(self._callback(msg))

            # Wait for response
            content = await asyncio.wait_for(response_queue.get(), timeout=300)

            if stream:
                response = web.StreamResponse(
                    headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache"}
                )
                await response.prepare(request)
                chunk = format_sse_chunk(delta=content, model="langagent")
                await response.write(f"data: {json.dumps(chunk)}\n\n".encode())
                done_chunk = format_sse_chunk(delta="", model="langagent", finish_reason="stop")
                await response.write(f"data: {json.dumps(done_chunk)}\n\n".encode())
                await response.write(b"data: [DONE]\n\n")
                return response
            else:
                result = format_chat_completion(content=content, model="langagent")
                return web.json_response(result)

        finally:
            self._pending_responses.pop(thread_id, None)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_channels_api.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/channels/api.py tests/test_channels_api.py
git commit -m "feat: add OpenAI-compatible API channel with SSE streaming"
```

---

### Task 8: Wire new channels into main.py and config

**Files:**
- Modify: `src/main.py`
- Modify: `src/config.py`

- [ ] **Step 1: Add CLI and API channel configs to config schema**

Read `src/config.py` first to understand the existing config structure. Then add:

```python
# Add to config.py — new channel config dataclasses

@dataclass
class CLIChannelConfig:
    enabled: bool = False
    user_id: str = "cli_user"

@dataclass
class APIChannelConfig:
    enabled: bool = True
    host: str = "0.0.0.0"
    port: int = 8900
    auth_token: str = ""
```

Add these to the main config class where Telegram config is defined.

- [ ] **Step 2: Update config.yaml with new channel defaults**

Add to `config.yaml`:

```yaml
channels:
  telegram:
    enabled: true
    token: "${TELEGRAM_BOT_TOKEN}"
    trigger: "@Agent"
    allowed_users: []
  cli:
    enabled: false
    user_id: "cli_user"
  api:
    enabled: true
    host: "0.0.0.0"
    port: 8900
```

- [ ] **Step 3: Wire channels into main.py**

Read `src/main.py` to understand the startup flow. Add CLI and API channel initialization alongside Telegram. The pattern should follow whatever ciana-parrot uses for Telegram startup.

- [ ] **Step 4: Test full startup (manual)**

```bash
# Test that the app starts without errors (will fail on LLM call without key, but should boot)
timeout 5 python -m src.main --help 2>&1 || echo "Startup test complete"
```

- [ ] **Step 5: Commit**

```bash
git add src/config.py src/main.py config.yaml
git commit -m "feat: wire CLI and API channels into main startup"
```

---

### Task 9: Update Docker deployment

**Files:**
- Modify: `Dockerfile`
- Modify: `docker-compose.yml`

- [ ] **Step 1: Update Dockerfile**

Read the existing Dockerfile, then ensure it:
- Uses `python:3.13-slim` base
- Installs system deps: `curl jq ffmpeg poppler-utils`
- Creates non-root user (uid 1000)
- Copies source and installs deps
- Exposes API port 8900
- Sets entry point to `python -m src.main`

- [ ] **Step 2: Update docker-compose.yml**

```yaml
services:
  agent-gateway:
    build: .
    ports:
      - "18790:18790"
    volumes:
      - ./workspace:/app/workspace
      - ./config.yaml:/app/config.yaml:ro
      - ./data:/app/data
      - ./skills:/app/skills:ro
    env_file: .env
    restart: unless-stopped

  agent-api:
    build: .
    command: ["python", "-m", "src.main", "--api-only"]
    ports:
      - "8900:8900"
    volumes:
      - ./workspace:/app/workspace
      - ./config.yaml:/app/config.yaml:ro
      - ./data:/app/data
    env_file: .env
    restart: unless-stopped
```

- [ ] **Step 3: Test Docker build**

```bash
docker build -t langagent-platform . 2>&1 | tail -5
```

Expected: Build succeeds

- [ ] **Step 4: Commit**

```bash
git add Dockerfile docker-compose.yml
git commit -m "feat: update Docker deployment for LangAgent Platform"
```

---

### Task 10: Final verification — all tests pass

**Files:**
- All test files

- [ ] **Step 1: Run full test suite**

```bash
pytest tests/ -v --tb=short
```

Expected: All tests PASS

- [ ] **Step 2: Verify Docker build**

```bash
docker build -t langagent-platform .
```

Expected: Build succeeds

- [ ] **Step 3: Final commit and tag**

```bash
git add -A
git commit -m "chore: Phase 0 complete — fork verified, CLI + API channels added"
git tag v0.0.1-phase0
```

---

## Exit Criteria

- [ ] All ciana-parrot source copied and renamed
- [ ] Config loads and validates from YAML
- [ ] LangGraph agent creates (with mocked LLM)
- [ ] Telegram channel imports correctly
- [ ] Gateway, scheduler, skills, tools all import correctly
- [ ] CLI channel implemented with Rich rendering
- [ ] OpenAI-compatible API channel implemented with SSE
- [ ] Docker builds successfully
- [ ] All tests pass
- [ ] Tagged as v0.0.1-phase0
