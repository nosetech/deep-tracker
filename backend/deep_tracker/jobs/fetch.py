"""定期取得バッチ。launchd から `python -m deep_tracker.jobs.fetch` として起動する。

有効なフィードのうち取得間隔を過ぎたものだけを取得する。多重起動はロックファイルで防ぐ。
"""

import argparse
import fcntl
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from deep_tracker.config import ConfigError, Settings, get_settings
from deep_tracker.config.loader import DEPLOY_ROOT
from deep_tracker.db import Feed, create_db_engine, make_session_factory, upgrade_db
from deep_tracker.db.models import utcnow
from deep_tracker.feeds import fetch_and_store
from deep_tracker.jobs.retention import purge_expired_articles

logger = logging.getLogger("deep_tracker.jobs.fetch")

# launchd の起動間隔の揺らぎで、間隔ちょうどのフィードが次回送りにならないための許容幅
DUE_TOLERANCE = timedelta(seconds=60)

LOG_DIR = DEPLOY_ROOT / "logs"
LOG_MAX_BYTES = 1_000_000
LOG_BACKUP_COUNT = 5


class AlreadyRunningError(Exception):
    """別のバッチが実行中。"""


@dataclass
class FetchReport:
    total: int = 0  # 有効なフィード数
    due: int = 0  # 今回取得対象になった数
    added: int = 0  # 追加された記事数
    failed: list[tuple[str, str]] = field(default_factory=list)  # (フィードURL, エラー内容)


def is_due(feed: Feed, default_interval_minutes: int, now: datetime) -> bool:
    if feed.last_fetched_at is None:
        return True
    last = feed.last_fetched_at
    if last.tzinfo is None:  # SQLite はタイムゾーンを保持しない（保存値は UTC）
        last = last.replace(tzinfo=UTC)
    interval = timedelta(minutes=feed.fetch_interval_minutes or default_interval_minutes)
    return now - last >= interval - DUE_TOLERANCE


def run_fetch(
    session: Session,
    settings: Settings,
    *,
    now: datetime | None = None,
    client: httpx.Client | None = None,
) -> FetchReport:
    """取得間隔を過ぎた有効フィードを取得する。1つが失敗しても残りを続行する。"""
    now = now or utcnow()
    feeds = session.scalars(select(Feed).where(Feed.enabled.is_(True)).order_by(Feed.id)).all()
    report = FetchReport(total=len(feeds))
    for feed in feeds:
        if not is_due(feed, settings.feed.fetch_interval_minutes, now):
            continue
        report.due += 1
        report.added += fetch_and_store(session, feed, client=client)
        if feed.last_fetch_ok is False:
            report.failed.append((feed.url, feed.last_fetch_error or "不明なエラー"))
    return report


@contextmanager
def single_instance(lock_path: Path) -> Iterator[None]:
    """排他ロックを取る。プロセスが異常終了してもOSが解放するため、残骸で止まらない。"""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as e:
            raise AlreadyRunningError(str(lock_path)) from e
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def lock_path_for(settings: Settings) -> Path:
    return Path(settings.db.path).with_name("fetch.lock")


def configure_logging(log_dir: Path = LOG_DIR) -> None:
    """標準出力とローテーション付きファイル（fetch.log）へ出力する。"""
    log_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    handlers: list[logging.Handler] = [
        logging.StreamHandler(sys.stdout),
        RotatingFileHandler(
            log_dir / "fetch.log",
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        ),
    ]
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for h in handlers:
        h.setFormatter(fmt)
        root.addHandler(h)


def log_report(report: FetchReport) -> None:
    logger.info(
        "取得完了: 有効 %d 件 / 対象 %d 件 / 新規記事 %d 件 / 失敗 %d 件",
        report.total,
        report.due,
        report.added,
        len(report.failed),
    )
    for url, error in report.failed:
        logger.warning("取得失敗: %s (%s)", url, error)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="購読フィードの定期取得バッチ")
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

    configure_logging()
    try:
        with single_instance(lock_path_for(settings)):
            upgrade_db(settings)
            engine = create_db_engine(settings.db.path)
            try:
                with make_session_factory(engine)() as session:
                    report = run_fetch(session, settings)
                    purge_expired_articles(session, settings.retention.days)
            finally:
                engine.dispose()
    except AlreadyRunningError:
        logger.info("別のバッチが実行中のためスキップしました")
        return 0
    except Exception:
        logger.exception("定期取得バッチが異常終了しました")
        return 1
    log_report(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
