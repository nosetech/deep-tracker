from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import ColumnElement, and_, func, or_, select, update
from sqlalchemy.orm import Session

from deep_tracker.api.deps import get_session
from deep_tracker.db import AiJob, Article, Feed
from deep_tracker.db.models import utcnow
from deep_tracker.jobs.ai_jobs import is_rate_limited
from deep_tracker.translate import detect_language, enqueue_translation
from deep_tracker.translate.service import latest_job

router = APIRouter()

SessionDep = Annotated[Session, Depends(get_session)]

# 公開日時が無い記事は取得日時で並べる
SORT_KEY = func.coalesce(Article.published_at, Article.fetched_at)
EXCERPT_LENGTH = 200


def _as_utc(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


class ArticleFilter:
    """一覧・前後記事・一括既読で共通の絞り込み条件。"""

    def __init__(
        self,
        unread_only: bool = False,
        marked_only: bool = False,
        feed_id: int | None = None,
        since: datetime | None = Query(None, description="この日時以降（含む）"),
        until: datetime | None = Query(None, description="この日時より前"),
        q: str | None = Query(
            None,
            description="タイトル・本文（日本語訳を含む）のキーワード検索（空白区切りでAND）",
        ),
    ) -> None:
        self.unread_only = unread_only
        self.marked_only = marked_only
        self.feed_id = feed_id
        self.since = _as_utc(since)
        self.until = _as_utc(until)
        self.q = q

    def conditions(self) -> list[ColumnElement[bool]]:
        conds: list[ColumnElement[bool]] = []
        if self.unread_only:
            conds.append(Article.is_read.is_(False))
        if self.marked_only:
            conds.append(Article.is_marked.is_(True))
        if self.feed_id is not None:
            conds.append(Article.feed_id == self.feed_id)
        if self.since is not None:
            conds.append(SORT_KEY >= self.since)
        if self.until is not None:
            conds.append(SORT_KEY < self.until)
        for term in (self.q or "").split():
            # LIKE のワイルドカードはリテラルとして扱う
            escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{escaped}%"
            conds.append(
                or_(
                    Article.title.like(pattern, escape="\\"),
                    Article.content.like(pattern, escape="\\"),
                    Article.title_ja.like(pattern, escape="\\"),
                    Article.content_ja.like(pattern, escape="\\"),
                )
            )
        return conds


FilterDep = Annotated[ArticleFilter, Depends()]


class ArticleListItem(BaseModel):
    id: int
    feed_id: int
    feed_name: str
    title: str
    # 日本語訳。未翻訳は None
    title_ja: str | None
    url: str | None
    # 翻訳済みなら日本語訳から作る
    excerpt: str | None
    published_at: datetime | None
    is_read: bool
    is_marked: bool
    # ja / other。保存時に未判定の記事（翻訳機能の追加前の記事）はその場で判定する
    language: str
    translated_at: datetime | None


class ArticleList(BaseModel):
    items: list[ArticleListItem]
    total: int
    page: int
    per_page: int


class ArticleNeighbor(BaseModel):
    id: int
    # 翻訳済みなら日本語訳
    title: str


class TranslationJob(BaseModel):
    """記事の最新の翻訳ジョブ。進捗は GET /api/ai-jobs/{id} でも確認できる。"""

    id: int
    status: str
    error: str | None
    rate_limited: bool


class ArticleDetail(BaseModel):
    id: int
    feed_id: int
    feed_name: str
    title: str
    url: str | None
    content: str | None
    language: str
    title_ja: str | None
    content_ja: str | None
    translated_at: datetime | None
    # 本文が長いため先頭のみ翻訳した
    translation_truncated: bool
    translation_job: TranslationJob | None
    published_at: datetime | None
    fetched_at: datetime
    is_read: bool
    read_at: datetime | None
    is_marked: bool
    marked_at: datetime | None
    newer: ArticleNeighbor | None
    older: ArticleNeighbor | None


class FeedUnreadCount(BaseModel):
    feed_id: int
    unread: int


class UnreadCounts(BaseModel):
    total: int
    feeds: list[FeedUnreadCount]


class ReadUpdate(BaseModel):
    is_read: bool


class ReadState(BaseModel):
    id: int
    is_read: bool
    read_at: datetime | None


class MarkUpdate(BaseModel):
    is_marked: bool


class MarkState(BaseModel):
    id: int
    is_marked: bool
    marked_at: datetime | None


class TranslateResult(BaseModel):
    job_id: int


class BulkReadResult(BaseModel):
    """未読 → 既読に変更した記事。article_ids を /articles/mark-unread に渡すと元に戻せる。"""

    count: int
    article_ids: list[int]


class MarkUnreadRequest(BaseModel):
    article_ids: list[int] = Field(max_length=100_000)


def _excerpt(content: str | None) -> str | None:
    if not content:
        return None
    text = " ".join(content.split())
    return text[:EXCERPT_LENGTH]


def _language(article: Article) -> str:
    return article.language or detect_language(article.title, article.content)


def _translation_job(job: AiJob | None) -> TranslationJob | None:
    if job is None:
        return None
    return TranslationJob(
        id=job.id, status=job.status, error=job.error, rate_limited=is_rate_limited(job)
    )


def _get_article(session: Session, article_id: int) -> Article:
    article = session.get(Article, article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="記事が見つかりません")
    return article


@router.get("/articles", response_model=ArticleList)
def list_articles(
    session: SessionDep,
    flt: FilterDep,
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ArticleList:
    conds = flt.conditions()
    total = session.scalar(select(func.count()).select_from(Article).where(*conds)) or 0
    rows = session.execute(
        select(Article, Feed.name)
        .join(Feed, Feed.id == Article.feed_id)
        .where(*conds)
        .order_by(SORT_KEY.desc(), Article.id.desc())
        .limit(per_page)
        .offset((page - 1) * per_page)
    ).all()
    items = [
        ArticleListItem(
            id=a.id,
            feed_id=a.feed_id,
            feed_name=feed_name,
            title=a.title,
            title_ja=a.title_ja,
            url=a.url,
            excerpt=_excerpt(a.content_ja or a.content),
            published_at=a.published_at,
            is_read=a.is_read,
            is_marked=a.is_marked,
            language=_language(a),
            translated_at=a.translated_at,
        )
        for a, feed_name in rows
    ]
    return ArticleList(items=items, total=total, page=page, per_page=per_page)


@router.get("/articles/unread-counts", response_model=UnreadCounts)
def unread_counts(session: SessionDep) -> UnreadCounts:
    rows = session.execute(
        select(Article.feed_id, func.count())
        .where(Article.is_read.is_(False))
        .group_by(Article.feed_id)
        .order_by(Article.feed_id)
    ).all()
    feeds = [FeedUnreadCount(feed_id=fid, unread=n) for fid, n in rows]
    return UnreadCounts(total=sum(f.unread for f in feeds), feeds=feeds)


@router.get("/articles/{article_id}", response_model=ArticleDetail)
def get_article(article_id: int, session: SessionDep, flt: FilterDep) -> ArticleDetail:
    """記事詳細。前後の記事は、絞り込み条件を指定した場合はその結果内での隣接記事を返す。"""
    article = _get_article(session, article_id)
    feed = session.get(Feed, article.feed_id)
    assert feed is not None
    key = article.published_at or article.fetched_at
    conds = flt.conditions()

    def neighbor(newer: bool) -> ArticleNeighbor | None:
        if newer:
            pos = or_(SORT_KEY > key, and_(SORT_KEY == key, Article.id > article.id))
            order = (SORT_KEY.asc(), Article.id.asc())
        else:
            pos = or_(SORT_KEY < key, and_(SORT_KEY == key, Article.id < article.id))
            order = (SORT_KEY.desc(), Article.id.desc())
        row = session.execute(
            select(Article.id, func.coalesce(Article.title_ja, Article.title))
            .where(pos, *conds)
            .order_by(*order)
            .limit(1)
        ).first()
        return ArticleNeighbor(id=row[0], title=row[1]) if row else None

    return ArticleDetail(
        id=article.id,
        feed_id=article.feed_id,
        feed_name=feed.name,
        title=article.title,
        url=article.url,
        content=article.content,
        language=_language(article),
        title_ja=article.title_ja,
        content_ja=article.content_ja,
        translated_at=article.translated_at,
        translation_truncated=article.translation_truncated,
        translation_job=_translation_job(latest_job(session, article.id)),
        published_at=article.published_at,
        fetched_at=article.fetched_at,
        is_read=article.is_read,
        read_at=article.read_at,
        is_marked=article.is_marked,
        marked_at=article.marked_at,
        newer=neighbor(newer=True),
        older=neighbor(newer=False),
    )


@router.post("/articles/{article_id}/translate", response_model=TranslateResult, status_code=202)
def translate(article_id: int, request: Request, session: SessionDep) -> TranslateResult:
    """未翻訳の記事を翻訳ジョブに投入する。翻訳中（待機中・実行中）なら、そのジョブを返す。

    設定 translation.enabled（取得時の自動投入）にかかわらず実行できる。
    """
    article = _get_article(session, article_id)
    if article.translated_at is not None:
        raise HTTPException(status_code=409, detail="この記事は翻訳済みです")
    job = enqueue_translation(session, article.id)
    runner = getattr(request.app.state, "ai_runner", None)
    if runner is not None:
        runner.notify()
    return TranslateResult(job_id=job.id)


@router.patch("/articles/{article_id}/read", response_model=ReadState)
def set_read(article_id: int, body: ReadUpdate, session: SessionDep) -> ReadState:
    article = _get_article(session, article_id)
    if article.is_read != body.is_read:
        article.is_read = body.is_read
        article.read_at = utcnow() if body.is_read else None
        session.commit()
    return ReadState(id=article.id, is_read=article.is_read, read_at=article.read_at)


@router.patch("/articles/{article_id}/mark", response_model=MarkState)
def set_mark(article_id: int, body: MarkUpdate, session: SessionDep) -> MarkState:
    article = _get_article(session, article_id)
    if article.is_marked != body.is_marked:
        article.is_marked = body.is_marked
        article.marked_at = utcnow() if body.is_marked else None
        session.commit()
    return MarkState(id=article.id, is_marked=article.is_marked, marked_at=article.marked_at)


def _mark_read(session: Session, conds: list[ColumnElement[bool]]) -> BulkReadResult:
    ids = list(
        session.scalars(
            select(Article.id).where(Article.is_read.is_(False), *conds).order_by(Article.id)
        )
    )
    now = utcnow()
    # SQLite の変数上限を避けるため分割して更新する
    for i in range(0, len(ids), 500):
        session.execute(
            update(Article)
            .where(Article.id.in_(ids[i : i + 500]))
            .values(is_read=True, read_at=now)
        )
    session.commit()
    return BulkReadResult(count=len(ids), article_ids=ids)


@router.post("/articles/mark-read", response_model=BulkReadResult)
def mark_read(session: SessionDep, flt: FilterDep) -> BulkReadResult:
    """絞り込み条件に一致する未読記事をすべて既読にする。条件なしの場合は全記事が対象。"""
    return _mark_read(session, flt.conditions())


@router.post("/feeds/{feed_id}/mark-read", response_model=BulkReadResult)
def mark_feed_read(feed_id: int, session: SessionDep) -> BulkReadResult:
    if session.get(Feed, feed_id) is None:
        raise HTTPException(status_code=404, detail="フィードが見つかりません")
    return _mark_read(session, [Article.feed_id == feed_id])


@router.post("/articles/mark-unread", response_model=BulkReadResult)
def mark_unread(body: MarkUnreadRequest, session: SessionDep) -> BulkReadResult:
    """一括既読の取り消し。指定した記事のうち既読のものを未読に戻す。"""
    ids = sorted(
        set(
            id_
            for i in range(0, len(body.article_ids), 500)
            for id_ in session.scalars(
                select(Article.id).where(
                    Article.id.in_(body.article_ids[i : i + 500]), Article.is_read.is_(True)
                )
            )
        )
    )
    for i in range(0, len(ids), 500):
        session.execute(
            update(Article)
            .where(Article.id.in_(ids[i : i + 500]))
            .values(is_read=False, read_at=None)
        )
    session.commit()
    return BulkReadResult(count=len(ids), article_ids=ids)
