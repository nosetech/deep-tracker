"""保存期間を過ぎた記事の削除。

起点は取得日時（`fetched_at`）。公開日時を起点にすると、フィードに残っている古い記事が
削除のたびに再取得されて未読として復活するため。サマリ本体は残り、元記事との関連行
（`summary_articles`）のみ外部キーの連鎖削除で消える。
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.orm import Session

from deep_tracker.db import Article
from deep_tracker.db.models import utcnow

logger = logging.getLogger("deep_tracker.jobs.retention")


def purge_expired_articles(
    session: Session, retention_days: int, *, now: datetime | None = None
) -> int:
    """`retention_days` 日より前に取得した記事を削除し、削除件数を返す。"""
    cutoff = (now or utcnow()) - timedelta(days=retention_days)
    result = session.execute(delete(Article).where(Article.fetched_at < cutoff))
    session.commit()
    count = result.rowcount
    logger.info("保存期間切れの記事を削除: %d 件 (保存期間 %d 日)", count, retention_days)
    return count
