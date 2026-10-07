from datetime import datetime
from typing import Annotated
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from deep_tracker.api.deps import get_http_client, get_session
from deep_tracker.config import get_settings
from deep_tracker.db import Article, Feed
from deep_tracker.feeds import FeedParseError, describe_error, fetch_and_store, register_feed

router = APIRouter(prefix="/feeds", tags=["feeds"])

SessionDep = Annotated[Session, Depends(get_session)]
ClientDep = Annotated[httpx.Client | None, Depends(get_http_client)]

# フィード追加時のエラー種別（GUIが3種類のエラー表示を出し分ける）
ERROR_INVALID_URL = "invalid_url"
ERROR_DUPLICATE_URL = "duplicate_url"
ERROR_NOT_A_FEED = "not_a_feed"
ERROR_NOT_FOUND = "feed_not_found"


class FeedOut(BaseModel):
    id: int
    name: str
    url: str
    enabled: bool
    # フィード個別の設定。None は設定ファイルの既定値を使う
    fetch_interval_minutes: int | None
    effective_fetch_interval_minutes: int
    article_count: int
    unread_count: int
    created_at: datetime
    last_fetched_at: datetime | None
    # 未取得は None
    last_fetch_ok: bool | None
    last_fetch_error: str | None


class FeedCreate(BaseModel):
    url: str
    # 省略時はフィードのタイトルを使う
    name: str | None = Field(default=None, max_length=255)


class FeedUpdate(BaseModel):
    """送られたフィールドだけ更新する。fetch_interval_minutes に null を送ると既定値に戻す。"""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    fetch_interval_minutes: int | None = Field(default=None, ge=1)
    enabled: bool | None = None


class FetchOut(BaseModel):
    added: int
    feed: FeedOut


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _validate_url(url: str) -> str:
    url = url.strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc or len(url) > 2048:
        raise _error(
            422, ERROR_INVALID_URL, "http:// または https:// で始まるURLを入力してください"
        )
    return url


def _feed_out(session: Session, feed: Feed) -> FeedOut:
    article_count, unread_count = session.execute(
        select(
            func.count(Article.id),
            func.coalesce(func.sum(case((Article.is_read.is_(False), 1), else_=0)), 0),
        ).where(Article.feed_id == feed.id)
    ).one()
    return _build_out(feed, article_count, unread_count)


def _build_out(feed: Feed, article_count: int, unread_count: int) -> FeedOut:
    return FeedOut(
        id=feed.id,
        name=feed.name,
        url=feed.url,
        enabled=feed.enabled,
        fetch_interval_minutes=feed.fetch_interval_minutes,
        effective_fetch_interval_minutes=(
            feed.fetch_interval_minutes or get_settings().feed.fetch_interval_minutes
        ),
        article_count=article_count,
        unread_count=unread_count,
        created_at=feed.created_at,
        last_fetched_at=feed.last_fetched_at,
        last_fetch_ok=feed.last_fetch_ok,
        last_fetch_error=feed.last_fetch_error,
    )


def _get_feed(session: Session, feed_id: int) -> Feed:
    feed = session.get(Feed, feed_id)
    if feed is None:
        raise _error(404, ERROR_NOT_FOUND, "フィードが見つかりません")
    return feed


@router.get("", response_model=list[FeedOut])
def list_feeds(session: SessionDep) -> list[FeedOut]:
    counts = (
        select(
            Article.feed_id,
            func.count(Article.id).label("total"),
            func.sum(case((Article.is_read.is_(False), 1), else_=0)).label("unread"),
        )
        .group_by(Article.feed_id)
        .subquery()
    )
    rows = session.execute(
        select(Feed, counts.c.total, counts.c.unread)
        .outerjoin(counts, counts.c.feed_id == Feed.id)
        .order_by(Feed.id)
    ).all()
    return [_build_out(feed, total or 0, unread or 0) for feed, total, unread in rows]


@router.post("", response_model=FeedOut, status_code=201)
def create_feed(body: FeedCreate, session: SessionDep, client: ClientDep) -> FeedOut:
    url = _validate_url(body.url)
    if session.scalar(select(Feed.id).where(Feed.url == url)) is not None:
        raise _error(409, ERROR_DUPLICATE_URL, "このフィードは既に登録されています")
    name = body.name.strip() if body.name else None
    try:
        feed = register_feed(session, url, name or None, client=client)
    except IntegrityError:
        # 重複チェックと登録の間に同じURLが登録された場合
        session.rollback()
        raise _error(409, ERROR_DUPLICATE_URL, "このフィードは既に登録されています") from None
    except (httpx.HTTPError, FeedParseError) as exc:
        raise _error(422, ERROR_NOT_A_FEED, describe_error(exc)) from exc
    return _feed_out(session, feed)


@router.patch("/{feed_id}", response_model=FeedOut)
def update_feed(feed_id: int, body: FeedUpdate, session: SessionDep) -> FeedOut:
    feed = _get_feed(session, feed_id)
    sent = body.model_fields_set
    if "name" in sent:
        if body.name is None:
            raise _error(422, "invalid_name", "名称を空にはできません")
        feed.name = body.name.strip()
    if "fetch_interval_minutes" in sent:
        feed.fetch_interval_minutes = body.fetch_interval_minutes
    if "enabled" in sent and body.enabled is not None:
        feed.enabled = body.enabled
    session.commit()
    return _feed_out(session, feed)


@router.delete("/{feed_id}", status_code=204)
def delete_feed(feed_id: int, session: SessionDep) -> None:
    # 関連記事は ON DELETE CASCADE で削除される。確認はGUI側で行う
    session.delete(_get_feed(session, feed_id))
    session.commit()


@router.post("/{feed_id}/fetch", response_model=FetchOut)
def fetch_now(feed_id: int, session: SessionDep, client: ClientDep) -> FetchOut:
    """有効/無効にかかわらず今すぐ1回取得する。失敗は例外にせず last_fetch_* に反映する。"""
    feed = _get_feed(session, feed_id)
    added = fetch_and_store(session, feed, client=client)
    return FetchOut(added=added, feed=_feed_out(session, feed))
