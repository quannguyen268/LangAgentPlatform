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
