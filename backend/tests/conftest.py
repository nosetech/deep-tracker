import pytest


@pytest.fixture(autouse=True)
def _clear_bind_ip_env(monkeypatch):
    # 実行環境の LAN_IP / TAILSCALE_IP がテスト結果に影響しないようにする
    monkeypatch.delenv("LAN_IP", raising=False)
    monkeypatch.delenv("TAILSCALE_IP", raising=False)
