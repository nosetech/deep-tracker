import socket

import httpx
import pytest

from deep_tracker.ai import AIError, ClaudeCodeCLIProvider, create_provider
from deep_tracker.config import load_settings
from deep_tracker.config.dev import (
    DEV_MODE_ENV,
    DevInstanceError,
    allocate_ports,
    build_dev_config,
    instance_name,
    validate_port,
)
from deep_tracker.config.models import AISettings
from deep_tracker.notify import SlackNotifier

URL = "https://hooks.slack.com/services/T000/B000/SECRETTOKEN"


def occupy():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    return s, s.getsockname()[1]


def test_allocate_ports_in_dev_range_and_distinct():
    backend, frontend = allocate_ports()
    assert 18000 <= backend < 19000
    assert 18000 <= frontend < 19000
    assert backend != frontend


@pytest.mark.parametrize("port", [8700, 3700])
def test_production_ports_rejected(port):
    with pytest.raises(DevInstanceError):
        validate_port(port, "backend")


def test_port_in_use_rejected():
    s, port = occupy()
    with s, pytest.raises(DevInstanceError):
        allocate_ports(backend=port)


def test_same_port_for_both_rejected():
    s, port = occupy()
    s.close()
    with pytest.raises(DevInstanceError):
        allocate_ports(backend=port, frontend=port)


def test_instance_name_is_valid_setting():
    assert instance_name("deep tracker/83") == "dev-deep-tracker-83"
    assert instance_name("///") == "dev-unknown"


def test_dev_config_is_isolated(tmp_path):
    config = build_dev_config(tmp_path, "wt", 18001, 18002)
    path = tmp_path / "config.yaml"
    import yaml

    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    settings = load_settings(path)
    assert settings.instance == "dev-wt"
    assert (settings.backend.port, settings.frontend.port) == (18001, 18002)
    assert settings.frontend.host == "127.0.0.1"
    assert settings.db.path == str(tmp_path / "deep-tracker.db")
    assert settings.slack.enabled is False


def test_dev_mode_blocks_slack(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"slack: {{enabled: true, webhook_url: {URL}}}\n", encoding="utf-8")
    sent = []

    def handler(request):
        sent.append(request)
        return httpx.Response(200)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setenv(DEV_MODE_ENV, "1")
    assert SlackNotifier(load_settings(cfg), client=client).notify("t") is False
    assert sent == []


def test_dev_mode_blocks_ai(monkeypatch):
    monkeypatch.setenv(DEV_MODE_ENV, "1")
    with pytest.raises(AIError):
        create_provider(AISettings()).generate("hi")


def test_normal_mode_uses_claude_code(monkeypatch):
    monkeypatch.delenv(DEV_MODE_ENV, raising=False)
    assert isinstance(create_provider(AISettings()), ClaudeCodeCLIProvider)
