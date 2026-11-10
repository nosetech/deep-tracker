import os
import sqlite3
import threading
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from deep_tracker.config import load_settings
from deep_tracker.jobs import backup
from deep_tracker.jobs.backup import create_backup, prune_backups, run_backup

JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 1, 14, 3, 0, 5, tzinfo=JST)


def make_db(path: Path, rows: int = 3) -> None:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    conn.executemany("INSERT INTO t (v) VALUES (?)", [(f"v{i}",) for i in range(rows)])
    conn.commit()
    conn.close()


def count_rows(path: Path) -> int:
    conn = sqlite3.connect(path)
    try:
        return conn.execute("SELECT COUNT(*) FROM t").fetchone()[0]
    finally:
        conn.close()


@pytest.fixture
def settings(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        f"instance: v2\ndb: {{path: {tmp_path / 'app.db'}}}\n"
        f"backup: {{dir: {tmp_path / 'bk'}, retention_days: 30}}\n",
        encoding="utf-8",
    )
    return load_settings(cfg)


def test_backup_filename_is_jst_and_has_instance(settings):
    make_db(Path(settings.db.path))
    # UTC 18:00:05 は JST 翌日 03:00:05
    dest = run_backup(settings, now=datetime(2026, 1, 13, 18, 0, 5, tzinfo=UTC))
    assert dest.name == "deep-tracker-v2-20260114-030005.db"
    assert dest.parent == Path(settings.backup.dir) / "v2"
    assert count_rows(dest) == 3


def test_backup_consistent_while_writing(settings):
    db = Path(settings.db.path)
    make_db(db, rows=100)
    stop = threading.Event()

    def writer():
        conn = sqlite3.connect(db, timeout=10)
        i = 0
        while not stop.is_set():
            conn.execute("INSERT INTO t (v) VALUES (?)", (f"w{i}",))
            conn.commit()
            i += 1
        conn.close()

    th = threading.Thread(target=writer)
    th.start()
    try:
        dest = run_backup(settings, now=NOW)
    finally:
        stop.set()
        th.join()
    conn = sqlite3.connect(dest)
    try:
        assert conn.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] >= 100
    finally:
        conn.close()
    # 一時ファイルは残らない
    assert [p.name for p in dest.parent.iterdir()] == [dest.name]


def test_skips_when_db_missing(settings):
    assert run_backup(settings, now=NOW) is None
    assert not Path(settings.backup.dir).exists()


def test_prune_only_old_files_matching_pattern(tmp_path):
    d = tmp_path / "bk"
    d.mkdir()
    old = d / "deep-tracker-v2-20251201-030000.db"
    new = d / "deep-tracker-v2-20260113-030000.db"
    other_instance = d / "deep-tracker-v3-20251201-030000.db"
    unrelated = d / "notes.txt"
    tmp_file = d / "deep-tracker-v2-20251201-030000.db.tmp"
    for p in (old, new, other_instance, unrelated, tmp_file):
        p.write_text("x")
    old_ts = (NOW - timedelta(days=31)).timestamp()
    for p in (old, other_instance, unrelated, tmp_file):
        os.utime(p, (old_ts, old_ts))
    removed = prune_backups(d, "v2", 30, NOW)
    assert removed == [old]
    assert not old.exists()
    for p in (new, other_instance, unrelated, tmp_file):
        assert p.exists()


def test_prune_keeps_file_within_retention(tmp_path):
    d = tmp_path / "bk"
    d.mkdir()
    f = d / "deep-tracker-v2-20251215-030000.db"
    f.write_text("x")
    ts = (NOW - timedelta(days=29)).timestamp()
    os.utime(f, (ts, ts))
    assert prune_backups(d, "v2", 30, NOW) == []


def test_failure_leaves_no_partial_file(tmp_path, monkeypatch):
    db = tmp_path / "app.db"
    make_db(db)

    def boom(path):
        raise backup.BackupError("検証失敗")

    monkeypatch.setattr(backup, "_verify", boom)
    dest_dir = tmp_path / "bk"
    with pytest.raises(backup.BackupError):
        create_backup(db, dest_dir, "v2", NOW)
    assert list(dest_dir.iterdir()) == []


def test_failure_on_corrupt_db_leaves_no_file(tmp_path):
    db = tmp_path / "app.db"
    db.write_bytes(b"not a sqlite database" * 100)
    dest_dir = tmp_path / "bk"
    with pytest.raises(sqlite3.DatabaseError):
        create_backup(db, dest_dir, "v2", NOW)
    assert list(dest_dir.iterdir()) == []


def test_main_notifies_on_failure(settings, monkeypatch):
    sent = []

    class FakeNotifier:
        def __init__(self, s):
            pass

        def notify(self, title, body=None, path=None):
            sent.append(title)

    monkeypatch.setattr(backup, "get_settings", lambda: settings)
    monkeypatch.setattr(backup, "SlackNotifier", FakeNotifier)
    monkeypatch.setattr(backup, "configure_logging", lambda *a, **k: None)
    Path(settings.db.path).write_bytes(b"garbage" * 100)
    assert backup.main([]) == 1
    assert sent == ["DBのバックアップに失敗しました"]


def test_main_ok_when_db_missing(settings, monkeypatch):
    monkeypatch.setattr(backup, "get_settings", lambda: settings)
    monkeypatch.setattr(backup, "configure_logging", lambda *a, **k: None)
    assert backup.main([]) == 0
