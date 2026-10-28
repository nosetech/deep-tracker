from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from deep_tracker.config import ConfigError, load_settings, loader
from deep_tracker.main import app

EXAMPLE = Path(__file__).resolve().parents[2] / "config" / "config.yaml.example"


def write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "config.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_defaults_when_default_file_missing(monkeypatch, tmp_path):
    monkeypatch.delenv(loader.CONFIG_ENV, raising=False)
    monkeypatch.setattr(loader, "DEFAULT_CONFIG_PATH", tmp_path / "none.yaml")
    s = load_settings()
    assert s.retention.days == 365
    assert s.summary.interval == "weekly"
    assert s.frontend.port == 3700
    assert s.backend.port == 8700
    assert s.slack.enabled is False


def test_example_is_valid_and_matches_defaults():
    s = load_settings(EXAMPLE)
    assert s.retention.days == 365
    assert s.summary.interval == "weekly"
    assert s.frontend.port == 3700


def test_override(tmp_path):
    p = write(
        tmp_path,
        "retention: {days: 30}\nsummary: {interval: daily}\n"
        "frontend: {port: 3710}\ndb: {path: /abs/x.db}\n"
        "slack: {enabled: true, webhook_url: 'https://hooks.slack.com/services/a/b/c'}\n",
    )
    s = load_settings(p)
    assert s.retention.days == 30
    assert s.summary.interval == "daily"
    assert s.frontend.port == 3710
    assert s.db.path == "/abs/x.db"
    assert s.slack.enabled


def test_ai_command(tmp_path):
    assert load_settings(write(tmp_path, "")).ai.command == "claude"
    s = load_settings(write(tmp_path, "ai: {command: /opt/bin/claude}\n"))
    assert s.ai.command == "/opt/bin/claude"


def test_relative_db_path_resolved_to_deploy_root(tmp_path):
    s = load_settings(write(tmp_path, "db: {path: data/a.db}\n"))
    assert s.db.path == str(loader.DEPLOY_ROOT / "data/a.db")


def test_empty_file_uses_defaults(tmp_path):
    assert load_settings(write(tmp_path, "")).retention.days == 365


@pytest.mark.parametrize(
    "text, key",
    [
        ("retention: {days: 0}", "retention.days"),
        ("summary: {interval: hourly}", "summary.interval"),
        ("backend: {port: 70000}", "backend.port"),
        ("backend: {prot: 1}", "backend.prot"),
        ("slack: {enabled: true}", "slack"),
        ("slack: {webhook_url: not-a-url}", "slack.webhook_url"),
        ("feed: {fetch_interval_minutes: abc}", "feed.fetch_interval_minutes"),
        ("ai: {command: ''}", "ai.command"),
        ("instance: 'a b'", "instance"),
    ],
)
def test_invalid_values(tmp_path, text, key):
    with pytest.raises(ConfigError) as e:
        load_settings(write(tmp_path, text))
    assert key in str(e.value)


def test_invalid_yaml_and_non_mapping(tmp_path):
    with pytest.raises(ConfigError):
        load_settings(write(tmp_path, "a: [unclosed"))
    with pytest.raises(ConfigError):
        load_settings(write(tmp_path, "- 1\n- 2\n"))


def test_explicit_missing_file_is_error(monkeypatch, tmp_path):
    monkeypatch.setenv(loader.CONFIG_ENV, str(tmp_path / "missing.yaml"))
    with pytest.raises(ConfigError):
        load_settings()


def test_env_overrides_path(monkeypatch, tmp_path):
    monkeypatch.setenv(loader.CONFIG_ENV, str(write(tmp_path, "retention: {days: 7}")))
    assert load_settings().retention.days == 7


def test_config_api_hides_secrets(monkeypatch, tmp_path):
    p = write(
        tmp_path,
        "slack: {enabled: true, webhook_url: 'https://hooks.slack.com/services/a/b/c'}",
    )
    monkeypatch.setenv(loader.CONFIG_ENV, str(p))
    loader.get_settings.cache_clear()
    try:
        body = TestClient(app).get("/api/config").json()
    finally:
        loader.get_settings.cache_clear()
    assert body["slack_enabled"] is True
    assert body["retention_days"] == 365
    assert "hooks.slack.com" not in str(body)


def test_config_api_returns_pyproject_version():
    import tomllib
    from pathlib import Path

    pyproject = Path(__file__).parents[1] / "pyproject.toml"
    expected = tomllib.loads(pyproject.read_text())["project"]["version"]
    assert TestClient(app).get("/api/config").json()["version"] == expected


def test_config_api_version_unknown_without_metadata(monkeypatch):
    from importlib.metadata import PackageNotFoundError

    from deep_tracker.api import config as config_api

    def missing(_name):
        raise PackageNotFoundError

    monkeypatch.setattr(config_api, "version", missing)
    assert TestClient(app).get("/api/config").json()["version"] == "unknown"


def test_frontend_host_is_rejected_with_migration_hint(tmp_path):
    with pytest.raises(ConfigError, match="LAN_IP"):
        load_settings(write(tmp_path, "frontend: {host: 0.0.0.0}\n"))


def test_launch_settings_output(monkeypatch, tmp_path, capsys):
    from deep_tracker.config import __main__ as launch

    path = write(tmp_path, "frontend:\n  port: 3710\nbackend:\n  port: 8710\n")
    monkeypatch.setenv(loader.CONFIG_ENV, str(path))
    monkeypatch.delenv("LAN_IP", raising=False)
    monkeypatch.delenv("TAILSCALE_IP", raising=False)
    loader.get_settings.cache_clear()
    try:
        assert launch.main() == 0
    finally:
        loader.get_settings.cache_clear()
    assert capsys.readouterr().out.splitlines() == [
        "INSTANCE=default",
        f"LOG_DIR={loader.LOG_DIR}",
        "FRONTEND_HOST=127.0.0.1",
        "FRONTEND_PUBLIC=",
        "FRONTEND_PORT=3710",
        "BACKEND_PORT=8710",
        "BASE_URL_HOST=''",
    ]


def test_launch_settings_uses_lan_ip(monkeypatch, tmp_path, capsys):
    from deep_tracker.config import __main__ as launch

    monkeypatch.setenv(loader.CONFIG_ENV, str(write(tmp_path, "")))
    monkeypatch.setenv("LAN_IP", "192.168.0.10")
    monkeypatch.delenv("TAILSCALE_IP", raising=False)
    loader.get_settings.cache_clear()
    try:
        assert launch.main() == 0
    finally:
        loader.get_settings.cache_clear()
    out = capsys.readouterr().out.splitlines()
    assert "FRONTEND_HOST=192.168.0.10" in out
    assert "FRONTEND_PUBLIC=1" in out


def test_launch_settings_fails_when_both_ips_given(monkeypatch, tmp_path, capsys):
    from deep_tracker.config import __main__ as launch

    monkeypatch.setenv(loader.CONFIG_ENV, str(write(tmp_path, "")))
    monkeypatch.setenv("LAN_IP", "192.168.0.10")
    monkeypatch.setenv("TAILSCALE_IP", "100.64.0.1")
    loader.get_settings.cache_clear()
    try:
        assert launch.main() == 1
    finally:
        loader.get_settings.cache_clear()
    assert "同時に指定できません" in capsys.readouterr().err
