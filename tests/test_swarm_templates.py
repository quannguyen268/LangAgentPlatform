"""Test TOML team template loader."""
import pytest
from pathlib import Path
from pydantic import ValidationError
from src.swarm.templates import AgentTemplate, TeamTemplate, load_builtin, load_template


def _write(path: Path, body: str) -> Path:
    path.write_text(body.lstrip("\n") + "\n")
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
    """Both shipped templates must load via the package resource API."""
    for name in ("software-dev", "research"):
        tmpl = load_builtin(name)
        assert tmpl.name
        assert len(tmpl.agents) > 0


def test_missing_file_raises_with_path(tmp_path):
    ghost = tmp_path / "does-not-exist.toml"
    with pytest.raises(FileNotFoundError, match="does-not-exist.toml"):
        load_template(str(ghost))


def test_malformed_toml_raises_with_path(tmp_path):
    t = _write(tmp_path / "broken.toml", "name = \ngoal = ")
    with pytest.raises(ValueError, match="Malformed TOML"):
        load_template(str(t))


def test_empty_agents_rejected(tmp_path):
    t = _write(tmp_path / "empty.toml", """
name = "x"
goal = "y"
phases = ["plan"]
agents = []
""")
    with pytest.raises(ValueError, match="at least one agent"):
        load_template(str(t))


def test_duplicate_agent_names_rejected(tmp_path):
    t = _write(tmp_path / "dup.toml", """
name = "x"
goal = "y"
phases = ["plan"]

[[agents]]
name = "worker"
role = "executor"
tier = "standard"
tools = []
skills = []
task_prompt = "task 1"

[[agents]]
name = "worker"
role = "executor"
tier = "standard"
tools = []
skills = []
task_prompt = "task 2"
""")
    with pytest.raises(ValueError, match="unique"):
        load_template(str(t))


def test_blank_strings_rejected(tmp_path):
    t = _write(tmp_path / "blank.toml", """
name = "x"
goal = "y"
phases = ["plan"]

[[agents]]
name = "   "
role = "executor"
tier = "standard"
tools = []
skills = []
task_prompt = "do thing"
""")
    with pytest.raises(ValueError):
        load_template(str(t))


def test_tools_and_skills_deduped(tmp_path):
    t = _write(tmp_path / "dupes.toml", """
name = "x"
goal = "y"
phases = ["plan"]

[[agents]]
name = "w"
role = "executor"
tier = "standard"
tools = ["read_file", "read_file", "exec", ""]
skills = ["a", "a", "b"]
task_prompt = "x"
""")
    tmpl = load_template(str(t))
    assert tmpl.agents[0].tools == ["read_file", "exec"]
    assert tmpl.agents[0].skills == ["a", "b"]


def test_known_tools_rejects_unknown(tmp_path):
    t = _write(tmp_path / "drift.toml", """
name = "x"
goal = "y"
phases = ["plan"]

[[agents]]
name = "w"
role = "executor"
tier = "standard"
tools = ["web_search", "nosuchtool"]
skills = []
task_prompt = "x"
""")
    with pytest.raises(ValueError, match="nosuchtool"):
        load_template(str(t), known_tools={"web_search", "web_fetch"})


def test_known_tools_passes_when_all_registered(tmp_path):
    t = _write(tmp_path / "ok.toml", """
name = "x"
goal = "y"
phases = ["plan"]

[[agents]]
name = "w"
role = "executor"
tier = "standard"
tools = ["web_search"]
skills = []
task_prompt = "x"
""")
    tmpl = load_template(str(t), known_tools={"web_search", "web_fetch"})
    assert tmpl.agents[0].tools == ["web_search"]


def test_load_builtin_raises_on_unknown_name():
    with pytest.raises(FileNotFoundError):
        load_builtin("does-not-exist")


# ---------------------------------------------------------------------------
# Phase field tests (WS4 Task 1)
# ---------------------------------------------------------------------------
def _agent(name, phase=None):
    return {"name": name, "role": "executor", "tier": "standard",
            "task_prompt": "do x", "tools": [], "skills": [],
            **({"phase": phase} if phase is not None else {})}


def test_agent_template_phase_defaults_none():
    a = AgentTemplate(**_agent("a"))
    assert a.phase is None


def test_agent_phase_blank_normalised_to_none():
    a = AgentTemplate(name="a", role="executor", tier="standard",
                      task_prompt="do x", phase="   ")
    assert a.phase is None


def test_team_is_phased_true_when_any_agent_has_phase():
    t = TeamTemplate(name="t", goal="g", phases=["plan", "execute"],
                     agents=[AgentTemplate(**_agent("a", "plan"))])
    assert t.is_phased is True


def test_team_is_phased_false_when_no_phases():
    t = TeamTemplate(name="t", goal="g", phases=["plan", "execute"],
                     agents=[AgentTemplate(**_agent("a"))])
    assert t.is_phased is False


def test_agents_for_phase_filters():
    t = TeamTemplate(name="t", goal="g", phases=["plan", "execute"],
                     agents=[AgentTemplate(**_agent("a", "plan")),
                             AgentTemplate(**_agent("b", "execute")),
                             AgentTemplate(**_agent("c", "plan"))])
    assert [a.name for a in t.agents_for_phase("plan")] == ["a", "c"]
    assert [a.name for a in t.agents_for_phase("execute")] == ["b"]


def test_unknown_agent_phase_rejected():
    with pytest.raises(ValidationError):
        TeamTemplate(name="t", goal="g", phases=["plan", "execute"],
                     agents=[AgentTemplate(**_agent("a", "bogus"))])
