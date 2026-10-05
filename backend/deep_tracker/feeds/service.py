import logging

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from deep_tracker.db.models import Article, Feed, utcnow
from deep_tracker.feeds.fetcher import FetchStatus, fetch_feed
from deep_tracker.feeds.parser import FeedParseError, parse_feed

logger = logging.getLogger(__name__)


def fetch_and_store(session: Session, feed: Feed, *, client: httpx.Client | None = None) -> int:
    """1フィードを取得して新規記事のみ保存し、追加件数を返す。

    失敗しても例外は送出せず、feed.last_fetch_ok / last_fetch_error に記録する。
    """
    now = utcnow()
    try:
        result = fetch_feed(
            feed.url, etag=feed.etag, last_modified=feed.last_modified, client=client
        )
        added = 0
        if result.status is FetchStatus.OK:
            entries = parse_feed(result.content)
            existing = set(session.scalars(select(Article.guid).where(Article.feed_id == feed.id)))
            for entry in entries:
                # 同一フィード内で GUID が重複していても1件だけ保存する
                if entry.guid in existing:
                    continue
                existing.add(entry.guid)
                session.add(
                    Article(
                        feed_id=feed.id,
                        guid=entry.guid,
                        title=entry.title,
                        url=entry.url,
                        content=entry.content,
                        published_at=entry.published_at,
                        fetched_at=now,
                    )
                )
                added += 1
            feed.etag = result.etag
            feed.last_modified = result.last_modified
        feed.last_fetch_ok = True
        feed.last_fetch_error = None
        feed.last_fetched_at = now
        session.commit()
        return added
    except Exception as exc:  # noqa: BLE001 - 他フィードの取得を止めないため全て記録する
        session.rollback()
        feed.last_fetch_ok = False
        feed.last_fetch_error = _describe_error(exc)
        feed.last_fetched_at = now
        session.commit()
        logger.warning("フィード取得に失敗: %s (%s)", feed.url, feed.last_fetch_error)
        return 0


def fetch_all_feeds(session: Session, *, client: httpx.Client | None = None) -> dict[int, int]:
    """有効な全フィードを取得する。1つが失敗しても残りを続行し、{feed_id: 追加件数} を返す。"""
    feeds = session.scalars(select(Feed).where(Feed.enabled.is_(True)).order_by(Feed.id)).all()
    return {feed.id: fetch_and_store(session, feed, client=client) for feed in feeds}


def _describe_error(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTPエラー: {exc.response.status_code}"
    if isinstance(exc, httpx.TimeoutException):
        return "タイムアウトしました"
    if isinstance(exc, httpx.HTTPError):
        return f"接続に失敗しました: {exc}"
    if isinstance(exc, FeedParseError):
        return str(exc)
    return f"予期しないエラー: {exc}"
