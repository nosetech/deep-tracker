"""DBの日次バックアップ。launchd から `python -m deep_tracker.jobs.backup` として起動する。

SQLite のオンラインバックアップAPI（`sqlite3.Connection.backup()`）で、稼働中でも整合した
コピーを作る（WAL も考慮される。`cp` は使わない）。一時ファイルに書いて検証してから rename
するため、途中で失敗しても不完全なバックアップは残らない。

バックアップは `<backup.dir>/<instance>/` に `deep-tracker-<instance>-YYYYmmdd-HHMMSS.db`
（JST）で置き、`backup.retention_days` を超えたものを削除する。
"""

import argparse
import logging
import os
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from deep_tracker.config import ConfigError, Settings, get_settings
from deep_tracker.logging_config import JST, configure_logging
from deep_tracker.notify.slack import SlackNotifier

logger = logging.getLogger("deep_tracker.jobs.backup")

SECONDS_PER_DAY = 86400


class BackupError(Exception):
    """バックアップまたはその検証に失敗した。"""


def backup_dir_for(settings: Settings) -> Path:
    return Path(settings.backup.dir) / settings.instance


def _filename_prefix(instance: str) -> str:
    return f"deep-tracker-{instance}-"


def _filename_pattern(instance: str) -> re.Pattern[str]:
    return re.compile(rf"^{re.escape(_filename_prefix(instance))}\d{{8}}-\d{{6}}\.db$")


def _verify(path: Path) -> None:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows = conn.execute("PRAGMA integrity_check").fetchall()
    finally:
        conn.close()
    if rows != [("ok",)]:
        raise BackupError(f"バックアップの整合性検証に失敗しました: {rows[:3]}")


def create_backup(db_path: Path, dest_dir: Path, instance: str, now: datetime) -> Path:
    """オンラインバックアップAPIで `db_path` を `dest_dir` へコピーし、作ったパスを返す。"""
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = now.astimezone(JST).strftime("%Y%m%d-%H%M%S")
    dest = dest_dir / f"{_filename_prefix(instance)}{stamp}.db"
    # 取りこぼし対象外の拡張子（.tmp）にしておき、完成するまで世代として数えない
    tmp = dest.with_name(dest.name + ".tmp")
    tmp.unlink(missing_ok=True)
    try:
        # 読み取り専用で開く（バックアップが元DBを変更しない）
        src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            dst = sqlite3.connect(tmp)
            try:
                src.backup(dst)
                # 元DBの WAL モードを引き継ぐと -wal / -shm が付いて回るため、単一ファイルにする
                dst.execute("PRAGMA journal_mode=DELETE").fetchone()
            finally:
                dst.close()
        finally:
            src.close()
        _verify(tmp)
        os.replace(tmp, dest)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return dest


def prune_backups(dest_dir: Path, instance: str, retention_days: int, now: datetime) -> list[Path]:
    """保持日数を超えた、自分のファイル名パターンのバックアップだけを削除する。"""
    pattern = _filename_pattern(instance)
    threshold = now.timestamp() - retention_days * SECONDS_PER_DAY
    removed: list[Path] = []
    if not dest_dir.is_dir():
        return removed
    for p in sorted(dest_dir.iterdir()):
        if p.is_file() and pattern.match(p.name) and p.stat().st_mtime < threshold:
            p.unlink()
            removed.append(p)
    return removed


def run_backup(settings: Settings, *, now: datetime | None = None) -> Path | None:
    """バックアップを取り、古い世代を削除する。DBが無ければ何もせず None を返す。"""
    now = now or datetime.now(JST)
    db_path = Path(settings.db.path)
    if not db_path.is_file():
        logger.info("DBが存在しないためスキップします: %s", db_path)
        return None
    dest_dir = backup_dir_for(settings)
    dest = create_backup(db_path, dest_dir, settings.instance, now)
    logger.info("バックアップを作成しました: %s", dest)
    for p in prune_backups(dest_dir, settings.instance, settings.backup.retention_days, now):
        logger.info("保持日数を超えたため削除しました: %s", p)
    return dest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DBの日次バックアップ")
    parser.add_argument(
        "--print-instance", action="store_true", help="設定の instance を表示して終了する"
    )
    args = parser.parse_args(argv)

    try:
        settings = get_settings()
    except ConfigError as e:
        print(f"設定エラー: {e}", file=sys.stderr)
        return 1
    if args.print_instance:
        print(settings.instance)
        return 0

    configure_logging(
        "backup.log", retention_days=settings.logging.retention_days, console=sys.stdout.isatty()
    )
    try:
        run_backup(settings)
    except Exception as e:
        logger.exception("DBのバックアップに失敗しました")
        if settings.slack.notify_on_failure:
            SlackNotifier(settings).notify("DBのバックアップに失敗しました", str(e))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
