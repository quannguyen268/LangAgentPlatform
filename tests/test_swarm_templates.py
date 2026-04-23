"""Test TOML team template loader."""
import pytest
from pathlib import Path
from src.swarm.templates import TeamTemplate, load_template


def _write(path: Path, body: str) -> Path:
    path.write_text(body.strip() + "\n")
    return path


def test_parses_valid_template(tmp_path):
    t = _write(tmp_path / "t.toml", """
name = "example"
goal = "Build an API"
phases = ["plan", "execute", "verify"]

[[agents]]
name = "architect"
role = "planner"
tier = "advanced"
tools = ["read_file", "write_file"]
skills = ["plan"]
task_prompt = "Design the API schema."

[[agents]]
name = "backend"
role = "executor"
tier = "standard"
tools = ["read_file", "write_file", "exec"]
skills = []
task_prompt = "Implement endpoints."
""")
    tmpl = load_template(str(t))
    assert isinstance(tmpl, TeamTemplate)
    assert tmpl.name == "example"
    assert tmpl.goal == "Build an API"
    assert tmpl.phases == ["plan", "execute", "verify"]
    assert len(tmpl.agents) == 2
    assert tmpl.agents[0].role == "planner"
    assert tmpl.agents[1].tier == "standard"


def test_rejects_invalid_tier(tmp_path):
    t = _write(tmp_path / "bad.toml", """
name = "bad"
goal = "x"
phases = ["plan"]

[[agents]]
name = "x"
role = "executor"
tier = "megamind"
tools = []
skills = []
task_prompt = "x"
""")
    with pytest.raises(ValueError):
        load_template(str(t))


def test_shipped_templates_parse():
    """Both shipped templates must load without error."""
    for tmpl_file in ["software-dev.toml", "research.toml"]:
        tmpl = load_template(f"templates/{tmpl_file}")
        assert tmpl.name
        assert len(tmpl.agents) > 0
