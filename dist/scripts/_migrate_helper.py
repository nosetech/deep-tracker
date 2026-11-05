"""migrate.sh の補助。新バージョンの backend/.venv の Python で実行する（引数: サブコマンド ...）。

  validate-config <config.yaml>    設定を検証し、instance / ポート / DBパスを表示する
  config-diff <旧config> <example>  設定キーの差分（新規・削除）をヒントとして表示する
  head-revision                    この展開先の Alembic の最新リビジョンを表示する
  db-state <db>                    DBのリビジョンを検査する（OK / OLD / NEWER / NONE）
  backup <src> <dst>               SQLite のオンラインバックアップでコピーする
"""

import sqlite3
import sys
from pathlib import Path

import yaml

NEW_ROOT = Path(__file__).resolve().parents[1]


def _flatten(d, prefix=""):
    keys = set()
    for k, v in (d or {}).items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            keys |= _flatten(v, key + ".")
        else:
            keys.add(key)
    return keys


def _script_dir():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    backend = NEW_ROOT / "backend"
    cfg = Config(str(backend / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend / "migrations"))
    return ScriptDirectory.from_config(cfg)


def validate_config(path: str) -> int:
    from deep_tracker.config import ConfigError, load_settings

    try:
        settings = load_settings(Path(path))
    except ConfigError as e:
        print(f"設定エラー: {e}", file=sys.stderr)
        return 1
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    db_raw = (raw.get("db") or {}).get("path", "data/deep-tracker.db")
    print(f"instance={settings.instance}")
    print(f"backend_port={settings.backend.port}")
    print(f"frontend_port={settings.frontend.port}")
    print(f"db_path={db_raw}")
    return 0


def config_diff(old: str, example: str) -> int:
    o = _flatten(yaml.safe_load(Path(old).read_text(encoding="utf-8")))
    e = _flatten(yaml.safe_load(Path(example).read_text(encoding="utf-8")))
    for k in sorted(e - o):
        print(f"新しい版の example にあり、移行元に無いキー（既定値で動作）: {k}")
    for k in sorted(o - e):
        print(f"移行元にあり、新しい版の example に無いキー（任意項目、または廃止の可能性）: {k}")
    return 0


def head_revision() -> int:
    print(_script_dir().get_current_head())
    return 0


def db_state(db: str) -> int:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
    except sqlite3.DatabaseError:
        row = None
    finally:
        conn.close()
    if row is None:
        print("NONE")
        return 0
    rev = row[0]
    script = _script_dir()
    try:
        known = script.get_revision(rev) is not None
    except Exception:  # noqa: BLE001  新バージョンに存在しないリビジョン
        known = False
    if not known:
        print(f"NEWER {rev}")
        return 0
    print("OK" if rev == script.get_current_head() else f"OLD {rev}")
    return 0


def backup(src: str, dst: str) -> int:
    s = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    d = sqlite3.connect(dst)
    try:
        s.backup(d)
    finally:
        d.close()
        s.close()
    return 0


def main(argv: list[str]) -> int:
    cmd, args = (argv[0] if argv else ""), argv[1:]
    handlers = {
        "validate-config": validate_config,
        "config-diff": config_diff,
        "head-revision": head_revision,
        "db-state": db_state,
        "backup": backup,
    }
    if cmd not in handlers:
        print(__doc__, file=sys.stderr)
        return 2
    return handlers[cmd](*args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
