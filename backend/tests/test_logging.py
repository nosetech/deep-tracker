import io
import logging
import os
import time
from datetime import datetime
from pathlib import Path

import pytest

from deep_tracker import log_rotator
from deep_tracker.config import ConfigError, load_settings
from deep_tracker.logging_config import (
    JST,
    JstFormatter,
    JstMidnightRotatingFileHandler,
    configure_logging,
)


@pytest.fixture
def tz_utc(monkeypatch):
    """OSのタイムゾーンをJSTでない環境（UTC）にする。"""
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def _ts(y, mo, d, h, mi) -> int:
    return int(datetime(y, mo, d, h, mi, tzinfo=JST).timestamp())


def test_rollover_is_jst_midnight_regardless_of_os_timezone(tz_utc, tmp_path):
    h = JstMidnightRotatingFileHandler(tmp_path / "a.log", backup_count=3)
    try:
        # JST 2026-01-01 23:30 の次の区切りは JST 2026-01-02 00:00（UTCでは 01-01 15:00）
        assert h.computeRollover(_ts(2026, 1, 1, 23, 30)) == _ts(2026, 1, 2, 0, 0)
        # JST 00:10 は UTC では前日。次の区切りは同じJST日の翌0時
        assert h.computeRollover(_ts(2026, 1, 2, 0, 10)) == _ts(2026, 1, 3, 0, 0)
    finally:
        h.close()


def test_rotated_file_is_named_with_jst_ended_day(tz_utc, tmp_path):
    path = tmp_path / "a.log"
    h = JstMidnightRotatingFileHandler(path, backup_count=3)
    h.setFormatter(logging.Formatter("%(message)s"))
    try:
        h.rolloverAt = _ts(2026, 1, 2, 0, 0)
        h.doRollover()
    finally:
        h.close()
    assert (tmp_path / "a.log.2026-01-01").exists()


def test_old_generations_are_deleted(tmp_path):
    path = tmp_path / "a.log"
    for day in range(1, 5):
        (tmp_path / f"a.log.2026-01-0{day}").write_text("x")
    (tmp_path / "a.log.1").write_text("旧形式")  # 対象外
    h = JstMidnightRotatingFileHandler(path, backup_count=2)
    try:
        h.rolloverAt = _ts(2026, 1, 6, 0, 0)
        h.doRollover()
    finally:
        h.close()
    names = sorted(p.name for p in tmp_path.glob("a.log.*"))
    assert names == ["a.log.1", "a.log.2026-01-04", "a.log.2026-01-05"]


def test_formatter_uses_jst(tz_utc):
    rec = logging.LogRecord("x", logging.INFO, "", 0, "m", None, None)
    rec.created = _ts(2026, 1, 1, 9, 0)
    rec.msecs = 5
    assert JstFormatter().formatTime(rec) == "2026-01-01 09:00:00,005"


def test_configure_logging_writes_file_and_is_idempotent(tmp_path):
    root = logging.getLogger()
    saved = root.handlers[:], root.level
    try:
        configure_logging("t.log", retention_days=3, log_dir=tmp_path)
        configure_logging("t.log", retention_days=3, log_dir=tmp_path)
        assert len(root.handlers) == 1
        logging.getLogger("deep_tracker.x").info("こんにちは")
        text = (tmp_path / "t.log").read_text(encoding="utf-8")
        assert "[INFO] こんにちは" in text
    finally:
        for h in root.handlers[:]:
            root.removeHandler(h)
            h.close()
        for h in saved[0]:
            root.addHandler(h)
        root.setLevel(saved[1])


def test_rotate_stream_writes_lines_verbatim(tmp_path):
    path = tmp_path / "logs" / "out.log"
    log_rotator.rotate_stream(["a  b\n", "日本語\r\n", "no newline"], path, 3)
    assert path.read_text(encoding="utf-8") == "a  b\n日本語\nno newline\n"


def test_rotate_stream_survives_write_errors(tmp_path, monkeypatch):
    path = tmp_path / "out.log"
    calls = {"n": 0}
    orig = JstMidnightRotatingFileHandler.emit

    def flaky(self, record):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("disk full")
        orig(self, record)

    monkeypatch.setattr(JstMidnightRotatingFileHandler, "emit", flaky)
    log_rotator.rotate_stream(["1\n", "2\n"], path, 3)
    assert path.read_text(encoding="utf-8") == "2\n"


def test_main_tolerates_invalid_utf8(tmp_path, monkeypatch):
    path = tmp_path / "out.log"
    stdin = io.TextIOWrapper(io.BytesIO(b"ok\n\xff\xfe bad\n"), encoding="utf-8")
    monkeypatch.setattr("sys.stdin", stdin)
    log_rotator.main(["--path", str(path), "--retention-days", "2"])
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "ok" and lines[1].endswith("bad")


def test_main_falls_back_when_config_is_broken(tmp_path, monkeypatch):
    bad = tmp_path / "c.yaml"
    bad.write_text("logging: {retention_days: 0}\n")
    monkeypatch.setenv("DEEP_TRACKER_CONFIG", str(bad))
    from deep_tracker.config import loader

    loader.get_settings.cache_clear()
    try:
        path = tmp_path / "out.log"
        stdin = io.TextIOWrapper(io.BytesIO(b"x\n"), encoding="utf-8")
        monkeypatch.setattr("sys.stdin", stdin)
        log_rotator.main(["--path", str(path)])
        assert path.read_text(encoding="utf-8") == "x\n"
    finally:
        loader.get_settings.cache_clear()


def _write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "c.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_retention_days_default(tmp_path):
    assert load_settings(_write(tmp_path, "")).logging.retention_days == 7


def test_retention_days_custom(tmp_path):
    s = load_settings(_write(tmp_path, "logging: {retention_days: 30}\n"))
    assert s.logging.retention_days == 30


@pytest.mark.parametrize("value", ["0", "-1", "abc", "1.5"])
def test_retention_days_invalid(tmp_path, value):
    with pytest.raises(ConfigError):
        load_settings(_write(tmp_path, f"logging: {{retention_days: {value}}}\n"))


def test_unused_os_import():
    assert os  # noqa
