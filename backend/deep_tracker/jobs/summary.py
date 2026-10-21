"""サマリの定期実行バッチ。launchd から `python -m deep_tracker.jobs.summary` として起動する。

`summary.interval`（daily / weekly / monthly）に応じて、直近に完了した暦期間（ローカル時刻の
0時区切り。週次は月曜始まり）を対象にサマリを生成する。起動は頻繁でよく、同一期間のサマリが
既にある（失敗・実行中を含む）場合は何もしない。失敗しても自動リトライはせず、次の期間まで待つ。
"""

import argparse
import logging
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from deep_tracker.ai import AIProvider, create_provider
from deep_tracker.config import ConfigError, Settings, get_settings
from deep_tracker.config.models import SummaryInterval
from deep_tracker.db import Summary, create_db_engine, make_session_factory, upgrade_db
from deep_tracker.jobs.ai_jobs import STATUS_SUCCEEDED
from deep_tracker.jobs.fetch import (
    AlreadyRunningError,
    configure_logging,
    single_instance,
)
from deep_tracker.notify.slack import SlackNotifier
from deep_tracker.summary import generate_summary

logger = logging.getLogger("deep_tracker.jobs.summary")


def _previous_month_start(first_of_month: datetime) -> datetime:
    last_day_of_prev = first_of_month - timedelta(days=1)
    return last_day_of_prev.replace(day=1)


def summary_period(interval: SummaryInterval, now: datetime) -> tuple[datetime, datetime]:
    """`now` 時点で直近に完了した期間 [start, end) を、UTC の aware datetime で返す。

    期間の区切りは `now` のタイムゾーン（ローカル時刻）の暦で決める。
    """
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if interval == SummaryInterval.DAILY:
        end, start = today, today - timedelta(days=1)
    elif interval == SummaryInterval.WEEKLY:
        end = today - timedelta(days=today.weekday())
        start = end - timedelta(days=7)
    else:
        end = today.replace(day=1)
        start = _previous_month_start(end)
    return start.astimezone(UTC), end.astimezone(UTC)


def run_scheduled_summary(
    session: Session,
    provider: AIProvider,
    settings: Settings,
    *,
    now: datetime | None = None,
    notifier: SlackNotifier | None = None,
) -> Summary | None:
    """対象期間のサマリを未生成なら生成する。生成しなかった（済み・記事なし）場合は None。

    AI処理が失敗した場合は status=failed のサマリが残り、例外は再送出される。
    """
    now = now or datetime.now().astimezone()
    start, end = summary_period(settings.summary.interval, now)
    existing = session.scalar(
        select(Summary.id).where(
            Summary.period_start == start,
            Summary.period_end == end,
        )
    )
    if existing is not None:
        logger.info("期間 %s〜%s のサマリは生成済みのためスキップします", start, end)
        return None

    notifier = notifier or SlackNotifier(settings)
    try:
        summary = generate_summary(session, provider, start, end)
    except Exception as e:
        notifier.notify(
            "サマリの生成に失敗しました", f"期間: {start:%Y-%m-%d}〜{end:%Y-%m-%d}\n{e}"
        )
        raise
    if summary is not None and summary.status == STATUS_SUCCEEDED:
        notifier.notify(
            "サマリを生成しました",
            f"期間: {start:%Y-%m-%d}〜{end:%Y-%m-%d} / 元記事 {len(summary.articles)} 件",
            path="/",
        )
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="サマリの定期実行バッチ")
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

    configure_logging(filename="summary.log")
    try:
        with single_instance(lock_path_for(settings)):
            upgrade_db(settings)
            engine = create_db_engine(settings.db.path)
            try:
                with make_session_factory(engine)() as session:
                    run_scheduled_summary(session, create_provider(settings.ai), settings)
            finally:
                engine.dispose()
    except AlreadyRunningError:
        logger.info("別のバッチが実行中のためスキップしました")
        return 0
    except Exception:
        # 失敗は summaries.status=failed と本ログに記録済み。自動リトライはしない
        logger.exception("サマリの定期実行が失敗しました")
        return 1
    return 0


def lock_path_for(settings: Settings) -> Path:
    return Path(settings.db.path).with_name("summary.lock")


if __name__ == "__main__":
    sys.exit(main())
