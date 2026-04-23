"""Test that SwarmConfig loads from config.yaml."""
def test_swarm_config_defaults():
    from src.config import SwarmConfig
    cfg = SwarmConfig()
    assert cfg.enabled is False
    assert cfg.templates_dir == "templates"
    assert cfg.workspace == "./workspace"


def test_swarm_config_override():
    from src.config import SwarmConfig
    cfg = SwarmConfig(enabled=True, templates_dir="custom/", workspace="/tmp")
    assert cfg.enabled is True
    assert cfg.templates_dir == "custom/"


def test_app_config_includes_swarm():
    """AppConfig must expose a swarm field with defaults applied."""
    from src.config import AppConfig
    app = AppConfig()
    assert app.swarm.enabled is False
    assert app.swarm.templates_dir == "templates"
