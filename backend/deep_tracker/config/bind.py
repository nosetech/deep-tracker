import os
from collections.abc import Mapping

LAN_IP_ENV = "LAN_IP"
TAILSCALE_IP_ENV = "TAILSCALE_IP"


class BindError(Exception):
    """frontend の待ち受けIPの指定が不正。"""


def resolve_bind_ip(env: Mapping[str, str] | None = None) -> str | None:
    """LAN_IP / TAILSCALE_IP から frontend の待ち受けIPを決める。未指定なら None（ローカルのみ）。

    0.0.0.0 は使わない。両方指定は曖昧なためエラーにする。
    """
    env = os.environ if env is None else env
    lan = env.get(LAN_IP_ENV, "").strip()
    tailscale = env.get(TAILSCALE_IP_ENV, "").strip()
    if lan and tailscale:
        raise BindError(
            f"{LAN_IP_ENV} と {TAILSCALE_IP_ENV} は同時に指定できません。どちらか一方にしてください"
        )
    ip = lan or tailscale
    if ip in ("0.0.0.0", "::"):  # noqa: S104
        raise BindError("0.0.0.0 / :: では待ち受けできません。具体的なIPアドレスを指定してください")
    return ip or None
