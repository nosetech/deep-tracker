"""フィードのグループ。グループはフィードと同じくGUIで管理するデータで、設定ファイルでは扱わない。"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import ColumnElement, case, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from deep_tracker.api.articles import BulkReadResult, mark_read_where
from deep_tracker.api.deps import get_session
from deep_tracker.db import Article, Feed, FeedGroup

router = APIRouter(prefix="/feed-groups", tags=["feed-groups"])

SessionDep = Annotated[Session, Depends(get_session)]

ERROR_DUPLICATE_NAME = "duplicate_name"
ERROR_INVALID_NAME = "invalid_name"
ERROR_NOT_FOUND = "group_not_found"


class FeedGroupOut(BaseModel):
    id: int
    name: str
    position: int
    created_at: datetime
    feed_count: int
    enabled_count: int
    # 有効なフィードのうち、最終取得が失敗したもの
    error_count: int
    unread_count: int


class FeedGroupIn(BaseModel):
    name: str = Field(max_length=255)


class EnabledUpdate(BaseModel):
    enabled: bool


class BulkEnabledResult(BaseModel):
    """有効/無効を変更したフィード（すでに指定の状態だったフィードは含まない）。"""

    count: int
    feed_ids: list[int]


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _get_group(session: Session, group_id: int) -> FeedGroup:
    group = session.get(FeedGroup, group_id)
    if group is None:
        raise _error(404, ERROR_NOT_FOUND, "グループが見つかりません")
    return group


def _name(body: FeedGroupIn) -> str:
    name = body.name.strip()
    if not name:
        raise _error(422, ERROR_INVALID_NAME, "グループ名を入力してください")
    return name


def _duplicate() -> HTTPException:
    return _error(409, ERROR_DUPLICATE_NAME, "同じ名前のグループがすでにあります")


def _name_taken(session: Session, name: str, exclude_id: int | None = None) -> bool:
    """同じ名前のグループがあるか。英字の大文字・小文字（全角を含む）は区別しない。

    SQLite の lower() は ASCII しか扱わないため、件数の少ないグループ名を読み出して比較する。
    """
    key = name.casefold()
    return any(
        gid != exclude_id and other.casefold() == key
        for gid, other in session.execute(select(FeedGroup.id, FeedGroup.name))
    )


def _group_outs(session: Session, group_ids: list[int] | None = None) -> list[FeedGroupOut]:
    feed_stats = (
        select(
            Feed.group_id,
            func.count(Feed.id).label("feeds"),
            func.sum(case((Feed.enabled.is_(True), 1), else_=0)).label("enabled"),
            func.sum(
                case((Feed.enabled.is_(True) & Feed.last_fetch_ok.is_(False), 1), else_=0)
            ).label("errors"),
        )
        .group_by(Feed.group_id)
        .subquery()
    )
    unread = (
        select(Feed.group_id, func.count(Article.id).label("unread"))
        .join(Article, Article.feed_id == Feed.id)
        .where(Article.is_read.is_(False))
        .group_by(Feed.group_id)
        .subquery()
    )
    stmt = (
        select(
            FeedGroup,
            feed_stats.c.feeds,
            feed_stats.c.enabled,
            feed_stats.c.errors,
            unread.c.unread,
        )
        .outerjoin(feed_stats, feed_stats.c.group_id == FeedGroup.id)
        .outerjoin(unread, unread.c.group_id == FeedGroup.id)
        .order_by(FeedGroup.name, FeedGroup.id)
    )
    if group_ids is not None:
        stmt = stmt.where(FeedGroup.id.in_(group_ids))
    return [
        FeedGroupOut(
            id=g.id,
            name=g.name,
            position=g.position,
            created_at=g.created_at,
            feed_count=feeds or 0,
            enabled_count=enabled or 0,
            error_count=errors or 0,
            unread_count=n_unread or 0,
        )
        for g, feeds, enabled, errors, n_unread in session.execute(stmt).all()
    ]


def _group_out(session: Session, group: FeedGroup) -> FeedGroupOut:
    return _group_outs(session, [group.id])[0]


@router.get("", response_model=list[FeedGroupOut])
def list_groups(session: SessionDep) -> list[FeedGroupOut]:
    """グループ一覧（名前順）。未分類のフィードはここに含まない。"""
    return _group_outs(session)


@router.post("", response_model=FeedGroupOut, status_code=201)
def create_group(body: FeedGroupIn, session: SessionDep) -> FeedGroupOut:
    name = _name(body)
    if _name_taken(session, name):
        raise _duplicate()
    position = (session.scalar(select(func.max(FeedGroup.position))) or 0) + 1
    group = FeedGroup(name=name, position=position)
    session.add(group)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise _duplicate() from None
    return _group_out(session, group)


@router.patch("/{group_id}", response_model=FeedGroupOut)
def rename_group(group_id: int, body: FeedGroupIn, session: SessionDep) -> FeedGroupOut:
    group = _get_group(session, group_id)
    name = _name(body)
    if _name_taken(session, name, exclude_id=group.id):
        raise _duplicate()
    group.name = name
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise _duplicate() from None
    return _group_out(session, group)


@router.delete("/{group_id}", status_code=204)
def delete_group(group_id: int, session: SessionDep) -> None:
    """グループのみ削除する。所属フィードと記事は残り、未分類に戻る。"""
    group = _get_group(session, group_id)
    # 外部キーの ON DELETE SET NULL に頼らず、明示的に未分類へ戻す
    session.execute(update(Feed).where(Feed.group_id == group.id).values(group_id=None))
    session.delete(group)
    session.commit()


def _feeds_in(group_id: int | None) -> ColumnElement[bool]:
    return Feed.group_id.is_(None) if group_id is None else Feed.group_id == group_id


def _mark_read(session: Session, group_id: int | None) -> BulkReadResult:
    feed_ids = select(Feed.id).where(_feeds_in(group_id))
    return mark_read_where(session, [Article.feed_id.in_(feed_ids)])


def _set_enabled(session: Session, group_id: int | None, enabled: bool) -> BulkEnabledResult:
    ids = list(
        session.scalars(
            select(Feed.id)
            .where(_feeds_in(group_id), Feed.enabled.is_not(enabled))
            .order_by(Feed.id)
        )
    )
    if ids:
        session.execute(update(Feed).where(Feed.id.in_(ids)).values(enabled=enabled))
        session.commit()
    return BulkEnabledResult(count=len(ids), feed_ids=ids)


# 未分類（どのグループにも属さないフィード）への一括操作。/{group_id} より先に定義する
@router.post("/ungrouped/mark-read", response_model=BulkReadResult)
def mark_ungrouped_read(session: SessionDep) -> BulkReadResult:
    return _mark_read(session, None)


@router.post("/ungrouped/enabled", response_model=BulkEnabledResult)
def set_ungrouped_enabled(body: EnabledUpdate, session: SessionDep) -> BulkEnabledResult:
    return _set_enabled(session, None, body.enabled)


@router.post("/{group_id}/mark-read", response_model=BulkReadResult)
def mark_group_read(group_id: int, session: SessionDep) -> BulkReadResult:
    """グループ内の未読記事をすべて既読にする（/articles/mark-unread で元に戻せる）。"""
    _get_group(session, group_id)
    return _mark_read(session, group_id)


@router.post("/{group_id}/enabled", response_model=BulkEnabledResult)
def set_group_enabled(group_id: int, body: EnabledUpdate, session: SessionDep) -> BulkEnabledResult:
    """グループ内のフィードをすべて有効/無効にする。"""
    _get_group(session, group_id)
    return _set_enabled(session, group_id, body.enabled)
