"""dist/scripts/migrate.sh（旧バージョンの展開先から状態を引き継ぐ）のテスト。"""

import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
BACKEND = REPO / "backend"
pytestmark = pytest.mark.skipif(
    not (BACKEND / ".venv/bin/python").exists(), reason="backend/.venv が必要"
)

CONFIG = "instance: old\nbackend:\n  port: 8700\nfrontend:\n  port: 3700\n"


def make_new_root(tmp_path: Path) -> Path:
    new = tmp_path / "new"
    (new / "scripts").mkdir(parents=True)
    (new / "config").mkdir()
    for name in ("migrate.sh", "_migrate_helper.py"):
        shutil.copy(REPO / "dist/scripts" / name, new / "scripts" / name)
    shutil.copy(REPO / "dist/config/config.yaml.example", new / "config")
    (new / "backend").symlink_to(BACKEND)
    return new


def make_db(path: Path, revision: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
    conn.execute("INSERT INTO alembic_version VALUES (?)", (revision,))
    conn.execute("CREATE TABLE t (x)")
    conn.execute("INSERT INTO t VALUES (42)")
    conn.commit()
    conn.close()


def make_old_root(tmp_path: Path, revision: str = "0002") -> Path:
    old = tmp_path / "old"
    (old / "config").mkdir(parents=True)
    (old / "config/config.yaml").write_text(CONFIG, encoding="utf-8")
    (old / ".env").write_text("LAN_IP=192.168.1.5\n", encoding="utf-8")
    (old / "logs").mkdir()
    (old / "logs/backend.log").write_text("log", encoding="utf-8")
    make_db(old / "data/deep-tracker.db", revision)
    return old


def run(new: Path, old: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(new / "scripts/migrate.sh"), str(old), *args],
        capture_output=True,
        text=True,
    )


def test_normal_migration(tmp_path):
    new, old = make_new_root(tmp_path), make_old_root(tmp_path)
    r = run(new, old)
    assert r.returncode == 0, r.stderr + r.stdout
    assert (new / "config/config.yaml").read_text(encoding="utf-8") == CONFIG
    assert (new / ".env").read_text(encoding="utf-8") == "LAN_IP=192.168.1.5\n"
    assert sqlite3.connect(new / "data/deep-tracker.db").execute("SELECT x FROM t").fetchone() == (
        42,
    )
    assert not (new / "logs").exists()  # --with-logs なし
    assert "instance" in r.stdout  # 並行稼働の警告（同値のため）
    assert (old / "config/config.yaml").exists()  # 旧展開先は変更されない


def test_with_logs(tmp_path):
    new, old = make_new_root(tmp_path), make_old_root(tmp_path)
    assert run(new, old, "--with-logs").returncode == 0
    assert (new / "logs/backend.log").read_text(encoding="utf-8") == "log"


def test_existing_files_are_skipped(tmp_path):
    new, old = make_new_root(tmp_path), make_old_root(tmp_path)
    (new / "config/config.yaml").write_text("instance: keep\n", encoding="utf-8")
    (new / ".env").write_text("keep", encoding="utf-8")
    r = run(new, old)
    assert r.returncode == 0, r.stderr
    assert (new / "config/config.yaml").read_text(encoding="utf-8") == "instance: keep\n"
    assert (new / ".env").read_text(encoding="utf-8") == "keep"
    assert "スキップ" in r.stdout


def test_force_backs_up_and_overwrites(tmp_path):
    new, old = make_new_root(tmp_path), make_old_root(tmp_path)
    (new / ".env").write_text("keep", encoding="utf-8")
    r = run(new, old, "--force")
    assert r.returncode == 0, r.stderr
    assert (new / ".env").read_text(encoding="utf-8") == "LAN_IP=192.168.1.5\n"
    backups = list(new.glob(".env.bak-*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "keep"


def test_invalid_yaml_stops(tmp_path):
    new, old = make_new_root(tmp_path), make_old_root(tmp_path)
    (old / "config/config.yaml").write_text("instance: [unclosed\n", encoding="utf-8")
    r = run(new, old)
    assert r.returncode != 0
    assert not (new / "config/config.yaml").exists()
    assert not (new / "data/deep-tracker.db").exists()


def test_unknown_config_key_stops(tmp_path):
    new, old = make_new_root(tmp_path), make_old_root(tmp_path)
    (old / "config/config.yaml").write_text("bogus: 1\n", encoding="utf-8")
    assert run(new, old).returncode != 0


def test_newer_db_schema_stops(tmp_path):
    new, old = make_new_root(tmp_path), make_old_root(tmp_path, revision="9999")
    r = run(new, old)
    assert r.returncode != 0
    assert "中止" in r.stderr
    assert not (new / "data/deep-tracker.db").exists()


def test_older_db_schema_is_copied(tmp_path):
    new, old = make_new_root(tmp_path), make_old_root(tmp_path, revision="0001")
    r = run(new, old)
    assert r.returncode == 0, r.stderr
    assert "自動で最新" in r.stdout
    assert (new / "data/deep-tracker.db").exists()


def test_same_root_stops(tmp_path):
    new = make_new_root(tmp_path)
    r = run(new, new)
    assert r.returncode != 0
    assert "同一" in r.stderr
