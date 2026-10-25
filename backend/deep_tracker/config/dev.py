"""動作確認用インスタンス（scripts/dev-instance.sh）向けの設定生成と、外部副作用の遮断スイッチ。

運用インスタンスと分離するため、ポート・DB・設定ファイルは専用の値にする。
DEV_MODE_ENV が有効なプロセスでは、Slack通知とAI(Claude Code CLI)呼び出しを行わない。
"""

import argparse
import json
import os
import re
import socket
import sys
from pathlib import Path

import yaml

from deep_tracker.config.models import BackendSettings, FrontendSettings, Settings

DEV_MODE_ENV = "DEEP_TRACKER_DEV_MODE"
# 運用インスタンスの既定ポート。動作確認用では使わない
PRODUCTION_PORTS = frozenset({BackendSettings().port, FrontendSettings().port})
PORT_RANGE = range(18000, 19000)


class DevInstanceError(Exception):
    """動作確認用インスタンスの設定が不正。"""


def is_dev_mode() -> bool:
    return os.environ.get(DEV_MODE_ENV) == "1"


def is_port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def validate_port(port: int, label: str) -> int:
    if port in PRODUCTION_PORTS:
        raise DevInstanceError(f"{label} に運用の既定ポート {port} は指定できません")
    if not 1 <= port <= 65535:
        raise DevInstanceError(f"{label} が範囲外です: {port}")
    if not is_port_free(port):
        raise DevInstanceError(f"{label} {port} は使用中です")
    return port


def allocate_ports(backend: int | None = None, frontend: int | None = None) -> tuple[int, int]:
    """backend / frontend のポートを決める。未指定は 18000 番台の空きから採番する。"""
    taken: set[int] = set()
    for explicit in (backend, frontend):
        if explicit is not None:
            validate_port(explicit, "ポート")
            taken.add(explicit)
    if backend is not None and backend == frontend:
        raise DevInstanceError("backend と frontend に同じポートは指定できません")

    def pick() -> int:
        for port in PORT_RANGE:
            if port not in taken and port not in PRODUCTION_PORTS and is_port_free(port):
                taken.add(port)
                return port
        raise DevInstanceError(f"{PORT_RANGE.start} 番台に空きポートがありません")

    return backend or pick(), frontend or pick()


def instance_name(worktree: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", worktree).strip("-") or "unknown"
    return f"dev-{safe}"


def build_dev_config(run_dir: Path, worktree: str, backend_port: int, frontend_port: int) -> dict:
    """運用の設定を引き継がない、動作確認用の設定を作る。"""
    config = {
        "instance": instance_name(worktree),
        "backend": {"port": backend_port},
        "frontend": {"host": "127.0.0.1", "port": frontend_port},
        "db": {"path": str(run_dir / "deep-tracker.db")},
        "slack": {"enabled": False},
    }
    Settings.model_validate(config)  # 生成物が設定として有効であることを保証する
    return config


def _prepare(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).resolve()
    backend_port, frontend_port = allocate_ports(args.backend_port, args.frontend_port)
    config = build_dev_config(run_dir, args.worktree, backend_port, frontend_port)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "config.yaml").write_text(
        yaml.safe_dump(config, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    print(json.dumps({"backend_port": backend_port, "frontend_port": frontend_port}))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m deep_tracker.config.dev")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare", help="ポートを決め、開発用 config.yaml を生成する")
    prepare.add_argument("--run-dir", required=True)
    prepare.add_argument("--worktree", required=True)
    prepare.add_argument("--backend-port", type=int)
    prepare.add_argument("--frontend-port", type=int)
    prepare.set_defaults(func=_prepare)
    args = parser.parse_args()
    try:
        return args.func(args)
    except DevInstanceError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
