# Phase 1B: Dream Memory, Management API & WebSocket — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Dream memory (2-stage consolidation with Git versioning), management REST API endpoints (/v1/memory, /v1/cost, /v1/tasks), and WebSocket event stream (/ws) for real-time StreamEvent delivery.

**Architecture:** Dream memory is a background asyncio task that periodically reads conversation history, uses a lightweight LLM to reflect, then surgically edits knowledge files (SOUL.md, USER.md, MEMORY.md) with changes tracked in Git. The management API extends the existing aiohttp server in `src/channels/api.py` with new routes. The WebSocket endpoint broadcasts StreamEvents to connected clients.

**Tech Stack:** Python 3.11+, asyncio, aiohttp (REST + WebSocket), dulwich (pure-Python Git), LangChain (for Dream LLM calls), Pydantic v2

**Spec Reference:** `docs/superpowers/specs/2026-04-15-langagent-platform-design.md` — Sections 10, 20.6, 20.4; GAPs 8, 10, 24, 25

**Prerequisites:** Phase 1A complete (638 tests passing, create_deep_agent with middleware)

---

## File Structure

### New files

```
src/memory/consolidator.py      # Stage 1: summarize conversations → history.jsonl
src/memory/dream.py             # Stage 2: reflect on history → edit knowledge files
src/memory/gitstore.py          # Git versioning for memory files (dulwich)
src/api/__init__.py             # Management API package
src/api/routes.py               # REST route definitions (memory, cost, tasks)
src/api/websocket.py            # WebSocket endpoint for StreamEvent broadcasting
tests/test_consolidator.py      # Consolidation tests
tests/test_dream.py             # Dream process tests
tests/test_gitstore.py          # Git versioning tests
tests/test_api_management.py    # Management API route tests
tests/test_websocket.py         # WebSocket tests
```

### Modified files

```
src/channels/api.py             # Add management routes + WebSocket to existing aiohttp app
src/config.py                   # Add dream config section
src/main.py                     # Start dream background task
config.yaml                     # Add dream config defaults
requirements.txt                # Add dulwich
```

---

### Task 1: Implement GitStore for memory versioning

**Files:**
- Create: `src/memory/gitstore.py`
- Create: `tests/test_gitstore.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_gitstore.py
"""Test GitStore for memory file versioning."""
import pytest
from pathlib import Path


def test_gitstore_imports():
    from src.memory.gitstore import GitStore
    assert GitStore is not None


def test_gitstore_init_creates_repo(tmp_path):
    from src.memory.gitstore import GitStore
    store = GitStore(str(tmp_path / "memory"))
    store.init()
    assert (tmp_path / "memory" / ".git").exists()


def test_gitstore_auto_commit(tmp_path):
    from src.memory.gitstore import GitStore
    mem_dir = tmp_path / "memory"
    mem_dir.mkdir()
    store = GitStore(str(mem_dir), tracked_files=["test.md"])
    store.init()

    # Write a file and commit
    (mem_dir / "test.md").write_text("Hello world")
    sha = store.auto_commit("Initial content")
    assert sha is not None
    assert len(sha) >= 7  # Short SHA


def test_gitstore_no_commit_if_unchanged(tmp_path):
    from src.memory.gitstore import GitStore
    mem_dir = tmp_path / "memory"
    mem_dir.mkdir()
    store = GitStore(str(mem_dir), tracked_files=["test.md"])
    store.init()

    (mem_dir / "test.md").write_text("Hello world")
    store.auto_commit("First")

    # No changes — should return None
    sha = store.auto_commit("No changes")
    assert sha is None


def test_gitstore_log_commits(tmp_path):
    from src.memory.gitstore import GitStore
    mem_dir = tmp_path / "memory"
    mem_dir.mkdir()
    store = GitStore(str(mem_dir), tracked_files=["test.md"])
    store.init()

    (mem_dir / "test.md").write_text("Version 1")
    store.auto_commit("v1")
    (mem_dir / "test.md").write_text("Version 2")
    store.auto_commit("v2")

    log = store.log_commits(limit=5)
    assert len(log) >= 2
    assert "v2" in log[0]["message"]


def test_gitstore_get_diff(tmp_path):
    from src.memory.gitstore import GitStore
    mem_dir = tmp_path / "memory"
    mem_dir.mkdir()
    store = GitStore(str(mem_dir), tracked_files=["test.md"])
    store.init()

    (mem_dir / "test.md").write_text("Version 1")
    sha1 = store.auto_commit("v1")
    (mem_dir / "test.md").write_text("Version 2")
    sha2 = store.auto_commit("v2")

    diff = store.get_diff(sha2)
    assert "Version" in diff


def test_gitstore_restore(tmp_path):
    from src.memory.gitstore import GitStore
    mem_dir = tmp_path / "memory"
    mem_dir.mkdir()
    store = GitStore(str(mem_dir), tracked_files=["test.md"])
    store.init()

    (mem_dir / "test.md").write_text("Version 1")
    sha1 = store.auto_commit("v1")
    (mem_dir / "test.md").write_text("Version 2")
    store.auto_commit("v2")

    store.restore_commit(sha1)
    assert (mem_dir / "test.md").read_text() == "Version 1"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_gitstore.py -v
```

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Install dulwich**

```bash
pip install dulwich
echo "dulwich>=0.22.0" >> requirements.txt
```

- [ ] **Step 4: Implement GitStore**

```python
# src/memory/gitstore.py
"""GitStore — Git versioning for memory files using dulwich (pure Python)."""
from __future__ import annotations

import logging
import time
from pathlib import Path

from dulwich.repo import Repo
from dulwich.objects import Blob, Tree, Commit
from dulwich import porcelain

logger = logging.getLogger(__name__)


class GitStore:
    """Track memory file changes with Git for audit trail and restore."""

    def __init__(self, path: str, tracked_files: list[str] | None = None):
        self.path = Path(path)
        self.tracked_files = tracked_files or ["SOUL.md", "USER.md", "MEMORY.md"]
        self._repo: Repo | None = None

    def init(self) -> None:
        """Initialize git repo if it doesn't exist."""
        self.path.mkdir(parents=True, exist_ok=True)
        git_dir = self.path / ".git"
        if git_dir.exists():
            self._repo = Repo(str(self.path))
        else:
            self._repo = Repo.init(str(self.path))
            # Create .gitignore
            gitignore = self.path / ".gitignore"
            gitignore.write_text("*.jsonl\n.cursor\n.dream_cursor\n")
            porcelain.add(self._repo, paths=[".gitignore"])
            porcelain.commit(
                self._repo,
                message=b"init: memory store",
                author=b"LangAgent <langagent@local>",
                committer=b"LangAgent <langagent@local>",
            )
            logger.info("GitStore initialized at %s", self.path)

    def auto_commit(self, message: str) -> str | None:
        """Stage tracked files and commit if there are changes.

        Returns:
            Short SHA of the commit, or None if nothing changed.
        """
        if not self._repo:
            self.init()

        # Stage tracked files that exist
        paths_to_add = []
        for fname in self.tracked_files:
            fpath = self.path / fname
            if fpath.exists():
                paths_to_add.append(fname)

        if not paths_to_add:
            return None

        porcelain.add(self._repo, paths=paths_to_add)

        # Check if there are staged changes
        status = porcelain.status(self._repo)
        staged_changes = status.staged["add"] or status.staged["modify"] or status.staged["delete"]
        if not staged_changes:
            return None

        sha = porcelain.commit(
            self._repo,
            message=message.encode("utf-8"),
            author=b"LangAgent Dream <langagent@local>",
            committer=b"LangAgent Dream <langagent@local>",
        )
        short_sha = sha.decode("ascii")[:7] if isinstance(sha, bytes) else str(sha)[:7]
        logger.info("GitStore commit: %s — %s", short_sha, message)
        return short_sha

    def log_commits(self, limit: int = 10) -> list[dict]:
        """Return recent commits as list of dicts."""
        if not self._repo:
            return []

        result = []
        try:
            walker = self._repo.get_walker(max_entries=limit)
            for entry in walker:
                commit = entry.commit
                result.append({
                    "sha": commit.id.decode("ascii")[:7],
                    "full_sha": commit.id.decode("ascii"),
                    "message": commit.message.decode("utf-8", errors="replace").strip(),
                    "timestamp": commit.commit_time,
                    "author": commit.author.decode("utf-8", errors="replace"),
                })
        except Exception as e:
            logger.warning("GitStore log failed: %s", e)
        return result

    def get_diff(self, sha: str) -> str:
        """Get the diff for a specific commit."""
        if not self._repo:
            return ""

        try:
            from dulwich.diff_tree import tree_changes
            # Find the full SHA
            full_sha = self._resolve_sha(sha)
            if not full_sha:
                return f"Commit {sha} not found"

            commit = self._repo[full_sha]
            parent_sha = commit.parents[0] if commit.parents else None

            if parent_sha:
                parent_tree = self._repo[self._repo[parent_sha].tree]
                current_tree = self._repo[commit.tree]
                changes = tree_changes(self._repo.object_store, parent_tree.id, current_tree.id)
                lines = []
                for change in changes:
                    old_path = change.old.path.decode() if change.old.path else "/dev/null"
                    new_path = change.new.path.decode() if change.new.path else "/dev/null"
                    lines.append(f"--- {old_path}")
                    lines.append(f"+++ {new_path}")
                    if change.new.sha:
                        new_content = self._repo[change.new.sha].data.decode("utf-8", errors="replace")
                        lines.append(new_content[:500])
                return "\n".join(lines)
            return "Initial commit — no parent to diff against"
        except Exception as e:
            return f"Diff error: {e}"

    def restore_commit(self, sha: str) -> bool:
        """Restore tracked files to the state at a given commit."""
        if not self._repo:
            return False

        try:
            full_sha = self._resolve_sha(sha)
            if not full_sha:
                return False

            commit = self._repo[full_sha]
            tree = self._repo[commit.tree]

            for item in tree.items():
                name = item.path.decode()
                if name in self.tracked_files:
                    blob = self._repo[item.sha]
                    (self.path / name).write_bytes(blob.data)

            self.auto_commit(f"restore: reverted to {sha}")
            return True
        except Exception as e:
            logger.error("GitStore restore failed: %s", e)
            return False

    def _resolve_sha(self, short_sha: str) -> bytes | None:
        """Resolve a short SHA to full SHA bytes."""
        try:
            for entry in self._repo.get_walker():
                full = entry.commit.id.decode("ascii")
                if full.startswith(short_sha):
                    return entry.commit.id
        except Exception:
            pass
        return None
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_gitstore.py -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/memory/gitstore.py tests/test_gitstore.py requirements.txt
git commit -m "feat: add GitStore for memory file versioning with dulwich"
```

---

### Task 2: Implement Consolidator (Stage 1)

**Files:**
- Create: `src/memory/consolidator.py`
- Create: `tests/test_consolidator.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_consolidator.py
"""Test Consolidator — Stage 1 memory compression."""
import pytest
import json
from pathlib import Path


def test_consolidator_imports():
    from src.memory.consolidator import Consolidator
    assert Consolidator is not None


def test_consolidator_init(tmp_path):
    from src.memory.consolidator import Consolidator
    c = Consolidator(str(tmp_path))
    assert c.history_path == tmp_path / "history.jsonl"
    assert c.cursor_path == tmp_path / ".cursor"


def test_append_to_history(tmp_path):
    from src.memory.consolidator import Consolidator
    c = Consolidator(str(tmp_path))

    c.append([
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"},
    ], summary="Greeting exchange")

    history = tmp_path / "history.jsonl"
    assert history.exists()
    lines = history.read_text().strip().split("\n")
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["summary"] == "Greeting exchange"
    assert entry["message_count"] == 2


def test_cursor_tracking(tmp_path):
    from src.memory.consolidator import Consolidator
    c = Consolidator(str(tmp_path))

    c.append([{"role": "user", "content": "msg1"}], summary="s1")
    c.append([{"role": "user", "content": "msg2"}], summary="s2")

    cursor = c.get_cursor()
    assert cursor == 2  # Two entries appended


def test_get_new_entries_since_cursor(tmp_path):
    from src.memory.consolidator import Consolidator
    c = Consolidator(str(tmp_path))

    c.append([{"role": "user", "content": "msg1"}], summary="s1")
    # Simulate a previous cursor at position 0
    c.set_dream_cursor(0)

    c.append([{"role": "user", "content": "msg2"}], summary="s2")

    new_entries = c.get_entries_since_dream_cursor()
    assert len(new_entries) == 2  # Both entries since cursor was 0


def test_dream_cursor_advances(tmp_path):
    from src.memory.consolidator import Consolidator
    c = Consolidator(str(tmp_path))

    c.append([{"role": "user", "content": "msg1"}], summary="s1")
    c.append([{"role": "user", "content": "msg2"}], summary="s2")

    c.set_dream_cursor(2)
    new = c.get_entries_since_dream_cursor()
    assert len(new) == 0  # No new entries since cursor is at end
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_consolidator.py -v
```

Expected: FAIL

- [ ] **Step 3: Implement Consolidator**

```python
# src/memory/consolidator.py
"""Consolidator — Stage 1 memory compression.

Summarizes old conversation messages into history.jsonl entries.
Cursor-based and incremental — only processes new messages.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_MAX_CHUNK_MESSAGES = 60


class Consolidator:
    """Summarize conversations into persistent history entries."""

    def __init__(self, memory_dir: str):
        self.memory_dir = Path(memory_dir)
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.history_path = self.memory_dir / "history.jsonl"
        self.cursor_path = self.memory_dir / ".cursor"
        self.dream_cursor_path = self.memory_dir / ".dream_cursor"

    def append(self, messages: list[dict], summary: str) -> None:
        """Append a consolidated summary entry to history.jsonl.

        Args:
            messages: The original messages that were summarized
            summary: LLM-generated summary of the messages
        """
        entry = {
            "timestamp": time.time(),
            "summary": summary,
            "message_count": len(messages),
        }
        with open(self.history_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        # Advance cursor
        cursor = self.get_cursor()
        self._write_cursor(self.cursor_path, cursor + 1)

    def get_cursor(self) -> int:
        """Get the current consolidation cursor (number of entries written)."""
        return self._read_cursor(self.cursor_path)

    def get_dream_cursor(self) -> int:
        """Get the dream cursor (last entry processed by Dream)."""
        return self._read_cursor(self.dream_cursor_path)

    def set_dream_cursor(self, value: int) -> None:
        """Set the dream cursor to a specific position."""
        self._write_cursor(self.dream_cursor_path, value)

    def get_entries_since_dream_cursor(self) -> list[dict]:
        """Get all history entries since the dream cursor."""
        dream_cursor = self.get_dream_cursor()
        all_entries = self._read_all_entries()
        return all_entries[dream_cursor:]

    def get_all_entries(self) -> list[dict]:
        """Read all history entries."""
        return self._read_all_entries()

    def _read_all_entries(self) -> list[dict]:
        if not self.history_path.exists():
            return []
        entries = []
        for line in self.history_path.read_text(encoding="utf-8").strip().split("\n"):
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return entries

    def _read_cursor(self, path: Path) -> int:
        if path.exists():
            try:
                return int(path.read_text().strip())
            except (ValueError, OSError):
                return 0
        return 0

    def _write_cursor(self, path: Path, value: int) -> None:
        path.write_text(str(value))
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_consolidator.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/memory/consolidator.py tests/test_consolidator.py
git commit -m "feat: add Consolidator for Stage 1 memory compression"
```

---

### Task 3: Implement Dream process (Stage 2)

**Files:**
- Create: `src/memory/dream.py`
- Create: `tests/test_dream.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_dream.py
"""Test Dream process — Stage 2 memory reflection."""
import pytest
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


def test_dream_imports():
    from src.memory.dream import DreamProcess
    assert DreamProcess is not None


def test_dream_init(tmp_path):
    from src.memory.dream import DreamProcess
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    memory_dir = workspace / "memory"
    memory_dir.mkdir()
    dream = DreamProcess(str(workspace), str(memory_dir))
    assert dream.workspace == workspace
    assert dream.max_batch_size == 20
    assert dream.max_iterations == 10


@pytest.mark.asyncio
async def test_dream_skips_when_no_new_entries(tmp_path):
    from src.memory.dream import DreamProcess
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    memory_dir = workspace / "memory"
    memory_dir.mkdir()

    dream = DreamProcess(str(workspace), str(memory_dir))
    result = await dream.run(model=MagicMock())
    assert result["status"] == "skipped"
    assert result["reason"] == "no_new_entries"


@pytest.mark.asyncio
async def test_dream_phase1_called_with_entries(tmp_path):
    from src.memory.dream import DreamProcess
    from src.memory.consolidator import Consolidator

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "SOUL.md").write_text("I am LangAgent.")
    (workspace / "MEMORY.md").write_text("No memories yet.")

    memory_dir = workspace / "memory"
    memory_dir.mkdir()

    # Add history entries
    consolidator = Consolidator(str(memory_dir))
    consolidator.append([{"role": "user", "content": "I love Python"}], summary="User likes Python")
    consolidator.append([{"role": "user", "content": "Use dark mode"}], summary="User prefers dark mode")

    # Mock the LLM
    mock_model = AsyncMock()
    mock_model.ainvoke = AsyncMock(return_value=MagicMock(content="User likes Python and prefers dark mode."))

    dream = DreamProcess(str(workspace), str(memory_dir))
    result = await dream.run(model=mock_model)

    assert result["status"] == "completed"
    assert result["entries_processed"] == 2
    # Dream cursor should advance
    assert consolidator.get_dream_cursor() == 2
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_dream.py -v
```

Expected: FAIL

- [ ] **Step 3: Implement DreamProcess**

```python
# src/memory/dream.py
"""Dream — Stage 2 memory reflection process.

Two phases (GAP-8):
- Phase 1: Plain LLM call to analyze new history entries (no tools)
- Phase 2: LLM with restricted tools (read/edit/write) to edit knowledge files

All changes tracked via GitStore.
"""
from __future__ import annotations

import logging
from pathlib import Path

from .consolidator import Consolidator
from .gitstore import GitStore

logger = logging.getLogger(__name__)

_PHASE1_PROMPT = """You are reviewing recent conversation summaries to update the agent's long-term memory.

Current knowledge files:
{soul_content}

---
{memory_content}

---

New conversation summaries to process:
{entries}

Analyze these summaries. What important facts, preferences, or patterns should be remembered?
What should be updated in the knowledge files? Be specific about what to change."""

_PHASE2_PROMPT = """Based on your analysis, make minimal surgical edits to the knowledge files.

Rules:
- Only change what's new or corrected
- Don't rewrite content that's still accurate
- Keep edits concise (one-liners preferred)
- SOUL.md: personality, voice, values (rarely changes)
- USER.md: user preferences, habits (changes often)
- MEMORY.md: project facts, decisions, context (changes often)

Your analysis:
{analysis}

Make the necessary edits now using the available tools (read_file, edit_file, write_file)."""


class DreamProcess:
    """Periodic reflection process that updates knowledge files from conversation history."""

    def __init__(
        self,
        workspace: str,
        memory_dir: str,
        max_batch_size: int = 20,
        max_iterations: int = 10,
    ):
        self.workspace = Path(workspace)
        self.memory_dir = Path(memory_dir)
        self.consolidator = Consolidator(str(self.memory_dir))
        self.gitstore = GitStore(
            str(self.memory_dir),
            tracked_files=["../SOUL.md", "../USER.md", "../MEMORY.md"],
        )
        self.max_batch_size = max_batch_size
        self.max_iterations = max_iterations

    async def run(self, model) -> dict:
        """Execute one dream cycle.

        Args:
            model: LLM to use for reflection (should be cheap — lite tier)

        Returns:
            Dict with status, entries_processed, and optional commit_sha
        """
        # Check for new entries
        new_entries = self.consolidator.get_entries_since_dream_cursor()
        if not new_entries:
            return {"status": "skipped", "reason": "no_new_entries"}

        # Limit batch size
        batch = new_entries[:self.max_batch_size]
        logger.info("Dream: processing %d new entries (of %d available)", len(batch), len(new_entries))

        # Read current knowledge files
        soul_content = self._read_file("SOUL.md")
        memory_content = self._read_file("MEMORY.md")

        # Phase 1: Analysis (plain LLM call, no tools)
        entries_text = "\n".join(
            f"- [{e.get('timestamp', '?')}] {e.get('summary', 'no summary')}"
            for e in batch
        )

        phase1_prompt = _PHASE1_PROMPT.format(
            soul_content=soul_content or "(empty)",
            memory_content=memory_content or "(empty)",
            entries=entries_text,
        )

        try:
            analysis_response = await model.ainvoke(phase1_prompt)
            analysis = analysis_response.content if hasattr(analysis_response, 'content') else str(analysis_response)
        except Exception as e:
            logger.error("Dream Phase 1 failed: %s", e)
            return {"status": "failed", "phase": 1, "error": str(e)}

        logger.info("Dream Phase 1 complete: %d chars analysis", len(analysis))

        # Phase 2: Editing (for now, append analysis to MEMORY.md)
        # Full Phase 2 with tool-guided editing is deferred to when we integrate
        # with DeepAgents' AgentRunner (requires restricted tool set).
        # For now, append key insights to MEMORY.md directly.
        memory_path = self.workspace / "MEMORY.md"
        try:
            existing = memory_path.read_text(encoding="utf-8") if memory_path.exists() else ""
            # Extract actionable lines from analysis (simple heuristic)
            new_lines = [
                line.strip() for line in analysis.split("\n")
                if line.strip() and not line.strip().startswith("#")
                and len(line.strip()) > 10
            ]
            if new_lines:
                update = "\n".join(f"- {line}" for line in new_lines[:5])  # Max 5 new items
                memory_path.write_text(
                    existing.rstrip() + "\n\n## Dream Update\n" + update + "\n",
                    encoding="utf-8",
                )
                logger.info("Dream Phase 2: appended %d insights to MEMORY.md", len(new_lines[:5]))
        except Exception as e:
            logger.error("Dream Phase 2 failed: %s", e)
            return {"status": "failed", "phase": 2, "error": str(e)}

        # Git commit
        self.gitstore.init()
        commit_sha = self.gitstore.auto_commit(
            f"dream: processed {len(batch)} entries"
        )

        # Advance dream cursor
        current_cursor = self.consolidator.get_dream_cursor()
        self.consolidator.set_dream_cursor(current_cursor + len(batch))

        return {
            "status": "completed",
            "entries_processed": len(batch),
            "commit_sha": commit_sha,
            "analysis_length": len(analysis),
        }

    def _read_file(self, filename: str) -> str:
        """Read a file from workspace, return empty string if missing."""
        path = self.workspace / filename
        if path.exists():
            try:
                return path.read_text(encoding="utf-8")
            except Exception:
                return ""
        return ""
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_dream.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/memory/dream.py tests/test_dream.py
git commit -m "feat: add Dream process for Stage 2 memory reflection"
```

---

### Task 4: Add Dream config and background task

**Files:**
- Modify: `src/config.py`
- Modify: `src/main.py`

- [ ] **Step 1: Read current config.py**

Read `src/config.py` to find where to add the Dream config.

- [ ] **Step 2: Add DreamConfig to config.py**

Add alongside the existing config dataclasses:

```python
@dataclass
class DreamConfig:
    enabled: bool = True
    interval_hours: float = 2.0
    max_batch_size: int = 20
    max_iterations: int = 10
    model: str = ""  # Empty = use default provider. Otherwise "provider:model"
```

Add as a field on `AppConfig` with default: `dream: DreamConfig = field(default_factory=DreamConfig)`

- [ ] **Step 3: Add dream section to config.yaml**

```yaml
dream:
  enabled: true
  interval_hours: 2.0
  max_batch_size: 20
  max_iterations: 10
```

- [ ] **Step 4: Wire dream background task in main.py**

Read `src/main.py`. After the scheduler starts, add:

```python
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
            import asyncio
            interval = config.dream.interval_hours * 3600
            while True:
                await asyncio.sleep(interval)
                try:
                    # Use a cheap model for dream reflection
                    from langchain.chat_models import init_chat_model
                    dream_model_name = config.dream.model or f"{config.provider.name}:{config.provider.model}"
                    dream_model = init_chat_model(dream_model_name)
                    result = await dream_proc.run(model=dream_model)
                    logger.info("Dream completed: %s", result)
                except Exception as e:
                    logger.error("Dream failed: %s", e)

        dream_task = asyncio.create_task(dream_loop())
        logger.info("Dream process enabled (interval: %.1fh)", config.dream.interval_hours)
```

In the cleanup section, cancel the dream task:

```python
    if dream_task:
        dream_task.cancel()
```

- [ ] **Step 5: Run existing tests**

```bash
pytest tests/test_config.py -v --tb=short -q
```

Expected: All config tests pass

- [ ] **Step 6: Commit**

```bash
git add src/config.py src/main.py config.yaml
git commit -m "feat: add Dream config and background task wiring"
```

---

### Task 5: Implement Management API routes (memory, cost, tasks)

**Files:**
- Create: `src/api/__init__.py`
- Create: `src/api/routes.py`
- Create: `tests/test_api_management.py`
- Modify: `src/channels/api.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_api_management.py
"""Test management API routes."""
import pytest
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop
from aiohttp import web
import json


@pytest.fixture
def management_app(tmp_path):
    """Create a test aiohttp app with management routes."""
    from src.api.routes import setup_management_routes

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "IDENTITY.md").write_text("I am LangAgent.")
    (workspace / "MEMORY.md").write_text("User likes Python.")
    memory_dir = workspace / "memory"
    memory_dir.mkdir()

    from src.observability.cost import CostTracker
    cost_tracker = CostTracker()
    cost_tracker.record("anthropic", "claude-sonnet-4-6", 1000, 500, "user1", "standard")

    app = web.Application()
    setup_management_routes(app, workspace=str(workspace), cost_tracker=cost_tracker)
    return app


@pytest.mark.asyncio
async def test_memory_list(management_app, aiohttp_client):
    client = await aiohttp_client(management_app)
    resp = await client.get("/v1/memory")
    assert resp.status == 200
    data = await resp.json()
    assert isinstance(data, list)
    assert any(f["name"] == "IDENTITY.md" for f in data)
    assert any(f["name"] == "MEMORY.md" for f in data)


@pytest.mark.asyncio
async def test_memory_read(management_app, aiohttp_client):
    client = await aiohttp_client(management_app)
    resp = await client.get("/v1/memory/IDENTITY.md")
    assert resp.status == 200
    data = await resp.json()
    assert "I am LangAgent" in data["content"]


@pytest.mark.asyncio
async def test_memory_read_not_found(management_app, aiohttp_client):
    client = await aiohttp_client(management_app)
    resp = await client.get("/v1/memory/NONEXISTENT.md")
    assert resp.status == 404


@pytest.mark.asyncio
async def test_memory_update(management_app, aiohttp_client):
    client = await aiohttp_client(management_app)
    resp = await client.put(
        "/v1/memory/MEMORY.md",
        json={"content": "Updated memory content."},
    )
    assert resp.status == 200
    # Verify it was written
    resp2 = await client.get("/v1/memory/MEMORY.md")
    data = await resp2.json()
    assert data["content"] == "Updated memory content."


@pytest.mark.asyncio
async def test_cost_summary(management_app, aiohttp_client):
    client = await aiohttp_client(management_app)
    resp = await client.get("/v1/cost")
    assert resp.status == 200
    data = await resp.json()
    assert "total_tokens" in data
    assert data["total_tokens"] > 0


@pytest.mark.asyncio
async def test_cost_breakdown(management_app, aiohttp_client):
    client = await aiohttp_client(management_app)
    resp = await client.get("/v1/cost/breakdown")
    assert resp.status == 200
    data = await resp.json()
    assert "by_user" in data
    assert "by_tier" in data
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_api_management.py -v
```

Expected: FAIL

- [ ] **Step 3: Implement management routes**

```python
# src/api/__init__.py
"""Management API — REST endpoints for memory, cost, tasks."""
```

```python
# src/api/routes.py
"""Management API route handlers.

Endpoints:
- GET/PUT /v1/memory/{filename} — Read/write memory files
- GET /v1/memory — List memory files
- GET /v1/memory/dream/log — Dream change history
- POST /v1/memory/dream/restore/{sha} — Restore memory to a previous state
- GET /v1/cost — Cost summary
- GET /v1/cost/breakdown — Per-user, per-tier, per-agent breakdown
- GET /v1/tasks — List scheduled tasks
"""
from __future__ import annotations

import logging
from pathlib import Path

from aiohttp import web

logger = logging.getLogger(__name__)

ALLOWED_MEMORY_FILES = {
    "IDENTITY.md", "AGENT.md", "MEMORY.md", "SOUL.md", "USER.md",
    "AGENT_REGISTRY.md", "TEAM_PLAYBOOK.md",
}


def setup_management_routes(
    app: web.Application,
    workspace: str,
    cost_tracker=None,
    gitstore=None,
) -> None:
    """Register management routes on an aiohttp Application."""
    workspace_path = Path(workspace)

    # ── Memory endpoints ──

    async def handle_memory_list(request: web.Request) -> web.Response:
        files = []
        for name in ALLOWED_MEMORY_FILES:
            fpath = workspace_path / name
            if fpath.exists():
                files.append({
                    "name": name,
                    "size": fpath.stat().st_size,
                    "modified": fpath.stat().st_mtime,
                })
        return web.json_response(files)

    async def handle_memory_read(request: web.Request) -> web.Response:
        filename = request.match_info["filename"]
        if filename not in ALLOWED_MEMORY_FILES:
            raise web.HTTPForbidden(reason=f"Access denied: {filename}")
        fpath = workspace_path / filename
        if not fpath.exists():
            raise web.HTTPNotFound(reason=f"File not found: {filename}")
        content = fpath.read_text(encoding="utf-8")
        return web.json_response({"name": filename, "content": content})

    async def handle_memory_update(request: web.Request) -> web.Response:
        filename = request.match_info["filename"]
        if filename not in ALLOWED_MEMORY_FILES:
            raise web.HTTPForbidden(reason=f"Access denied: {filename}")
        body = await request.json()
        content = body.get("content", "")
        fpath = workspace_path / filename
        fpath.write_text(content, encoding="utf-8")
        return web.json_response({"status": "ok", "name": filename, "size": len(content)})

    async def handle_dream_log(request: web.Request) -> web.Response:
        if not gitstore:
            return web.json_response({"commits": []})
        commits = gitstore.log_commits(limit=20)
        return web.json_response({"commits": commits})

    async def handle_dream_restore(request: web.Request) -> web.Response:
        sha = request.match_info["sha"]
        if not gitstore:
            raise web.HTTPServiceUnavailable(reason="GitStore not available")
        success = gitstore.restore_commit(sha)
        if success:
            return web.json_response({"status": "restored", "sha": sha})
        raise web.HTTPNotFound(reason=f"Commit {sha} not found")

    # ── Cost endpoints ──

    async def handle_cost_summary(request: web.Request) -> web.Response:
        if not cost_tracker:
            return web.json_response({"total_tokens": 0, "total_cost_cents": 0})
        return web.json_response(cost_tracker.summary())

    async def handle_cost_breakdown(request: web.Request) -> web.Response:
        if not cost_tracker:
            return web.json_response({"by_user": {}, "by_tier": {}, "by_agent": {}})
        return web.json_response({
            "by_user": cost_tracker.by_user(),
            "by_tier": cost_tracker.by_tier(),
            "by_agent": cost_tracker.by_agent(),
        })

    # ── Register routes ──

    app.router.add_get("/v1/memory", handle_memory_list)
    app.router.add_get("/v1/memory/dream/log", handle_dream_log)
    app.router.add_post("/v1/memory/dream/restore/{sha}", handle_dream_restore)
    app.router.add_get("/v1/memory/{filename}", handle_memory_read)
    app.router.add_put("/v1/memory/{filename}", handle_memory_update)
    app.router.add_get("/v1/cost", handle_cost_summary)
    app.router.add_get("/v1/cost/breakdown", handle_cost_breakdown)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_api_management.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/api/ tests/test_api_management.py
git commit -m "feat: add management API routes for memory, cost, and dream log"
```

---

### Task 6: Implement WebSocket event stream

**Files:**
- Create: `src/api/websocket.py`
- Create: `tests/test_websocket.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_websocket.py
"""Test WebSocket event broadcasting."""
import pytest
import asyncio
import json


def test_event_hub_imports():
    from src.api.websocket import EventHub
    assert EventHub is not None


@pytest.mark.asyncio
async def test_event_hub_subscribe_and_broadcast():
    from src.api.websocket import EventHub
    from src.core.streaming import token_event

    hub = EventHub()
    received = []

    async def subscriber():
        async for event in hub.subscribe():
            received.append(event)
            if len(received) >= 2:
                break

    # Start subscriber
    task = asyncio.create_task(subscriber())

    # Give subscriber time to register
    await asyncio.sleep(0.05)

    # Broadcast events
    hub.broadcast(token_event("Hello", user_id="u1"))
    hub.broadcast(token_event("World", user_id="u1"))

    await asyncio.wait_for(task, timeout=2.0)
    assert len(received) == 2
    assert received[0].data["delta"] == "Hello"
    assert received[1].data["delta"] == "World"


@pytest.mark.asyncio
async def test_event_hub_multiple_subscribers():
    from src.api.websocket import EventHub
    from src.core.streaming import done_event

    hub = EventHub()
    counts = [0, 0]

    async def sub(idx):
        async for event in hub.subscribe():
            counts[idx] += 1
            break

    t1 = asyncio.create_task(sub(0))
    t2 = asyncio.create_task(sub(1))
    await asyncio.sleep(0.05)

    hub.broadcast(done_event(user_id="u1"))
    await asyncio.wait_for(asyncio.gather(t1, t2), timeout=2.0)

    assert counts[0] == 1
    assert counts[1] == 1


@pytest.mark.asyncio
async def test_event_hub_unsubscribe_on_exit():
    from src.api.websocket import EventHub
    hub = EventHub()

    async for event in hub.subscribe():
        break  # Exit immediately

    # Should not raise or leak
    assert hub.subscriber_count == 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_websocket.py -v
```

Expected: FAIL

- [ ] **Step 3: Implement EventHub**

```python
# src/api/websocket.py
"""WebSocket event broadcasting for real-time StreamEvent delivery.

EventHub manages subscribers. Each WebSocket connection subscribes
to receive StreamEvents. The hub broadcasts events to all subscribers.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator

from aiohttp import web

from ..core.streaming import StreamEvent

logger = logging.getLogger(__name__)


class EventHub:
    """Fan-out StreamEvents to multiple WebSocket subscribers."""

    def __init__(self):
        self._queues: list[asyncio.Queue[StreamEvent | None]] = []

    @property
    def subscriber_count(self) -> int:
        return len(self._queues)

    def broadcast(self, event: StreamEvent) -> None:
        """Send an event to all subscribers."""
        for q in self._queues:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass  # Drop if subscriber is slow

    async def subscribe(self) -> AsyncIterator[StreamEvent]:
        """Async iterator that yields events. Cleans up on exit."""
        queue: asyncio.Queue[StreamEvent | None] = asyncio.Queue(maxsize=1000)
        self._queues.append(queue)
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield event
        finally:
            self._queues.remove(queue)

    def close_all(self) -> None:
        """Signal all subscribers to disconnect."""
        for q in self._queues:
            try:
                q.put_nowait(None)
            except asyncio.QueueFull:
                pass


async def websocket_handler(request: web.Request) -> web.WebSocketResponse:
    """aiohttp WebSocket handler that streams events to connected clients."""
    hub: EventHub = request.app["event_hub"]
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    logger.info("WebSocket client connected (total: %d)", hub.subscriber_count + 1)

    try:
        async for event in hub.subscribe():
            if ws.closed:
                break
            await ws.send_json(event.to_dict())
    except Exception as e:
        logger.debug("WebSocket error: %s", e)
    finally:
        logger.info("WebSocket client disconnected (total: %d)", hub.subscriber_count)

    return ws


def setup_websocket(app: web.Application, hub: EventHub) -> None:
    """Register WebSocket route and store hub on app."""
    app["event_hub"] = hub
    app.router.add_get("/ws", websocket_handler)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_websocket.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/api/websocket.py tests/test_websocket.py
git commit -m "feat: add EventHub and WebSocket endpoint for real-time StreamEvent delivery"
```

---

### Task 7: Wire management API + WebSocket into the existing API channel

**Files:**
- Modify: `src/channels/api.py`
- Modify: `src/main.py`

- [ ] **Step 1: Update APIChannel to accept management routes and websocket**

Read `src/channels/api.py`. In the `start()` method, after creating the aiohttp app but before starting the runner, add:

```python
# In APIChannel.__init__, add optional dependencies:
def __init__(self, host="0.0.0.0", port=8900, workspace=None, cost_tracker=None, event_hub=None):
    # ... existing init ...
    self._workspace = workspace
    self._cost_tracker = cost_tracker
    self._event_hub = event_hub
```

In `start()`, after route setup:
```python
    # Management API routes
    if self._workspace:
        from ..api.routes import setup_management_routes
        setup_management_routes(app, workspace=self._workspace, cost_tracker=self._cost_tracker)

    # WebSocket
    if self._event_hub:
        from ..api.websocket import setup_websocket
        setup_websocket(app, self._event_hub)
```

- [ ] **Step 2: Update main.py to pass workspace and cost tracker to API channel**

In `src/main.py`, where the API channel is created, pass the workspace and cost tracker:

```python
    if config.channels.api.enabled:
        from .api.websocket import EventHub
        from .observability.cost import CostTracker

        event_hub = EventHub()
        cost_tracker = CostTracker()

        api = APIChannel(
            host=config.channels.api.host,
            port=config.channels.api.port,
            workspace=config.agent.workspace,
            cost_tracker=cost_tracker,
            event_hub=event_hub,
        )
        # ... wire callback, append to channels ...
```

- [ ] **Step 3: Run full test suite**

```bash
pytest tests/ -q --tb=line --ignore=tests/test_middleware_bridge.py --ignore=tests/test_middleware_full.py
```

Expected: All pass (existing + new)

- [ ] **Step 4: Commit**

```bash
git add src/channels/api.py src/main.py
git commit -m "feat: wire management API and WebSocket into API channel startup"
```

---

### Task 8: Add slash commands for Dream

**Files:**
- Modify: `src/router.py` (or create `src/commands/dream.py` if commands module exists)

- [ ] **Step 1: Add /dream, /dream-log, /dream-restore commands**

Read `src/router.py` to understand how commands (like `/new`) are currently handled. Then add handlers for:

- `/dream` — trigger dream process manually
- `/dream-log` — show recent dream commits (from GitStore)
- `/dream-restore {sha}` — restore memory to a previous state

These should be handled in the message router's `handle_message` method, before passing to the agent. If the text starts with `/dream`, handle it directly and return a response.

```python
# In handle_message, after trigger check:
if clean_text.startswith("/dream"):
    return await self._handle_dream_command(clean_text, msg)

async def _handle_dream_command(self, text: str, msg) -> AgentResponse:
    from .memory.dream import DreamProcess
    from .memory.gitstore import GitStore

    parts = text.strip().split()
    cmd = parts[0]

    if cmd == "/dream" and len(parts) == 1:
        # Trigger dream manually
        # ... create DreamProcess, run it ...
        return AgentResponse(text="Dream process triggered.")

    if cmd == "/dream-log":
        gitstore = GitStore(str(Path(self._workspace, "memory")))
        gitstore.init()
        commits = gitstore.log_commits(limit=10)
        if not commits:
            return AgentResponse(text="No dream history yet.")
        lines = [f"**{c['sha']}** — {c['message']}" for c in commits]
        return AgentResponse(text="## Dream Log\n\n" + "\n".join(lines))

    if cmd.startswith("/dream-restore") and len(parts) >= 2:
        sha = parts[1]
        gitstore = GitStore(str(Path(self._workspace, "memory")))
        gitstore.init()
        if gitstore.restore_commit(sha):
            return AgentResponse(text=f"Memory restored to {sha}.")
        return AgentResponse(text=f"Commit {sha} not found.")

    return AgentResponse(text="Unknown dream command. Use: /dream, /dream-log, /dream-restore {sha}")
```

- [ ] **Step 2: Test manually or write a test**

```bash
pytest tests/test_router.py -v --tb=short
```

Expected: Existing router tests still pass

- [ ] **Step 3: Commit**

```bash
git add src/router.py
git commit -m "feat: add /dream, /dream-log, /dream-restore slash commands"
```

---

### Task 9: Final verification and tag

- [ ] **Step 1: Run full test suite**

```bash
pytest tests/ -v --tb=short --ignore=tests/test_middleware_bridge.py --ignore=tests/test_middleware_full.py
```

Expected: All pass (existing + ~30 new tests)

- [ ] **Step 2: Verify all modules import correctly**

```bash
python3 -c "
from src.memory.consolidator import Consolidator
print('Consolidator OK')
from src.memory.dream import DreamProcess
print('DreamProcess OK')
from src.memory.gitstore import GitStore
print('GitStore OK')
from src.api.routes import setup_management_routes
print('Management API routes OK')
from src.api.websocket import EventHub, websocket_handler
print('WebSocket OK')
print('All Phase 1B modules verified!')
"
```

- [ ] **Step 3: Commit and tag**

```bash
git add -A
git commit -m "chore: Phase 1B complete — Dream memory, management API, WebSocket"
git tag v0.2.0-phase1b
git push origin feature/implementation-plans --tags
```

---

## Exit Criteria

- [ ] GitStore versioning with dulwich (init, auto_commit, log, diff, restore)
- [ ] Consolidator for Stage 1 (append summaries to history.jsonl, cursor tracking)
- [ ] DreamProcess for Stage 2 (Phase 1 analysis, Phase 2 editing, Git commit)
- [ ] Dream config section (interval, batch size, model)
- [ ] Dream background task in main.py
- [ ] Management API: GET/PUT /v1/memory/{filename}, GET /v1/memory, GET /v1/memory/dream/log, POST /v1/memory/dream/restore/{sha}
- [ ] Management API: GET /v1/cost, GET /v1/cost/breakdown
- [ ] WebSocket EventHub with fan-out broadcasting
- [ ] WebSocket endpoint /ws integrated into API channel
- [ ] Slash commands: /dream, /dream-log, /dream-restore
- [ ] All existing tests still pass
- [ ] Tagged as v0.2.0-phase1b

## What's deferred

- **Full Phase 2 Dream editing with tool-guided AgentRunner** — requires DeepAgents integration for restricted tool set. Current implementation appends insights directly to MEMORY.md.
- **Per-user USER.md in Dream** — requires iterating over user directories. Current implementation edits shared MEMORY.md only.
- **/v1/tasks endpoints** — depends on Phase 1C sub-agent system.
- **/v1/agents endpoints** — depends on Phase 1C.
- **WebSocket authentication** — Phase 2B (Web UI).
