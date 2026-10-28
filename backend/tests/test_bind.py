import pytest

from deep_tracker.config.bind import BindError, resolve_bind_ip


def test_unset_means_local_only():
    assert resolve_bind_ip({}) is None
    assert resolve_bind_ip({"LAN_IP": " ", "TAILSCALE_IP": ""}) is None


@pytest.mark.parametrize("name", ["LAN_IP", "TAILSCALE_IP"])
def test_single_ip(name):
    assert resolve_bind_ip({name: "10.0.0.5"}) == "10.0.0.5"


def test_both_is_error():
    with pytest.raises(BindError):
        resolve_bind_ip({"LAN_IP": "10.0.0.5", "TAILSCALE_IP": "100.64.0.1"})


def test_wildcard_is_error():
    with pytest.raises(BindError):
        resolve_bind_ip({"LAN_IP": "0.0.0.0"})
