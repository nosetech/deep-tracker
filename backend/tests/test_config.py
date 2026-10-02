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
    assert s.frontend.host == "127.0.0.1"
    assert s.backend.port == 8700
    assert not s.lan_exposed
    assert s.slack.enabled is False


def test_example_is_valid_and_matches_defaults():
    s = load_settings(EXAMPLE)
    assert s.retention.days == 365
    assert s.summary.interval == "weekly"
    assert s.frontend.host == "127.0.0.1"


def test_override(tmp_path):
    p = write(
        tmp_path,
        "retention: {days: 30}\nsummary: {interval: daily}\n"
        "frontend: {host: 0.0.0.0, port: 3710}\ndb: {path: /abs/x.db}\n"
        "slack: {enabled: true, webhook_url: 'https://hooks.slack.com/services/a/b/c'}\n",
    )
    s = load_settings(p)
    assert s.retention.days == 30
    assert s.summary.interval == "daily"
    assert s.lan_exposed and s.frontend.port == 3710
    assert s.db.path == "/abs/x.db"
    assert s.slack.enabled


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
