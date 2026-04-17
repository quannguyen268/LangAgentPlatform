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
        # GitStore tracks knowledge files inside workspace (not memory_dir)
        # so the repo root is workspace and files are bare filenames.
        self.gitstore = GitStore(
            str(self.workspace),
            tracked_files=["SOUL.md", "USER.md", "MEMORY.md"],
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
