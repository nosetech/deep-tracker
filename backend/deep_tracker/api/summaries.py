import json
import re
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from deep_tracker.api.articles import SORT_KEY
from deep_tracker.api.deps import get_session
from deep_tracker.config import get_settings
from deep_tracker.config.models import SummaryInterval
from deep_tracker.db import AiJob, Article, Feed, Summary
from deep_tracker.jobs.ai_jobs import (
    STATUS_PENDING,
    STATUS_RUNNING,
    STATUS_SUCCEEDED,
    enqueue_job,
    is_rate_limited,
)
from deep_tracker.jobs.summary import next_summary_run
from deep_tracker.summary.service import JOB_KIND

router = APIRouter(prefix="/summaries", tags=["summaries"])

SessionDep = Annotated[Session, Depends(get_session)]

# 手動生成の対象期間。直近のサマリが無い場合にさかのぼる日数
INTERVAL_DAYS = {SummaryInterval.DAILY: 1, SummaryInterval.WEEKLY: 7, SummaryInterval.MONTHLY: 30}

_RESET_RE = re.compile(r"（解除予定: (.+)）$")


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _kind(start: datetime, end: datetime) -> str:
    """期間の形から、定期実行（日次・週次・月次）か手動生成かを判定する。"""
    s, e = start.astimezone(), end.astimezone()

    def midnight(d: datetime) -> bool:
        return (d.hour, d.minute, d.second, d.microsecond) == (0, 0, 0, 0)

    if midnight(s) and midnight(e):
        days = (e.date() - s.date()).days
        if days == 1:
            return "日次サマリ"
        if days == 7 and s.weekday() == 0:
            return "週次サマリ"
        if s.day == 1 and e.day == 1 and 28 <= days <= 31:
            return "月次サマリ"
    return "手動生成"


class SummaryListItem(BaseModel):
    id: int
    kind: str
    period_start: datetime
    period_end: datetime
    created_at: datetime
    article_count: int
    topic_count: int


class SummarySource(BaseModel):
    id: int
    title: str
    url: str | None
    feed_name: str
    published_at: datetime | None
    is_read: bool


class SummaryTopic(BaseModel):
    title: str
    summary: str
    sources: list[SummarySource]


class NewSince(BaseModel):
    count: int
    unread_count: int


class SummaryDetail(BaseModel):
    id: int
    kind: str
    period_start: datetime
    period_end: datetime
    created_at: datetime
    article_count: int
    topic_count: int
    overview: str
    topics: list[SummaryTopic]
    # サマリの対象期間より後に届いた記事
    new_since: NewSince
    is_latest: bool


class GenerationState(BaseModel):
    """手動生成ジョブの状態。state が idle の場合、ジョブは存在しない（または閉じられた）。"""

    state: str  # idle / running / failed
    job_id: int | None = None
    # 進捗: 1=記事収集 / 2=Claude Codeで要約 / 3=保存
    step: int = 0
    period_start: datetime | None = None
    article_count: int | None = None
    error: str | None = None
    rate_limited: bool = False
    # 利用制限の解除見込み（Claude Code が返した文言）
    reset_text: str | None = None


class SummaryConfig(BaseModel):
    interval: str
    next_run_at: datetime


def _succeeded():
    return Summary.status == STATUS_SUCCEEDED


def _topics(summary: Summary) -> list[dict]:
    try:
        return json.loads(summary.body or "")["topics"]
    except (ValueError, KeyError, TypeError):
        return []


def _list_item(session: Session, s: Summary) -> SummaryListItem:
    return SummaryListItem(
        id=s.id,
        kind=_kind(_as_utc(s.period_start), _as_utc(s.period_end)),
        period_start=_as_utc(s.period_start),
        period_end=_as_utc(s.period_end),
        created_at=_as_utc(s.created_at),
        article_count=len(s.articles),
        topic_count=len(_topics(s)),
    )


def _latest_id(session: Session) -> int | None:
    return session.scalar(
        select(Summary.id)
        .where(_succeeded())
        .order_by(Summary.created_at.desc(), Summary.id.desc())
    )


def _detail(session: Session, s: Summary) -> SummaryDetail:
    body = json.loads(s.body or "{}")
    articles = {a.id: a for a in s.articles}
    feed_names = dict(session.execute(select(Feed.id, Feed.name)).all())
    topics = []
    for t in body.get("topics", []):
        sources = [
            SummarySource(
                id=a.id,
                title=a.title,
                url=a.url,
                feed_name=feed_names.get(a.feed_id, ""),
                published_at=_as_utc(a.published_at) if a.published_at else None,
                is_read=a.is_read,
            )
            for a in (articles.get(i) for i in t.get("article_ids", []))
            if a is not None
        ]
        topics.append(SummaryTopic(title=t["title"], summary=t["summary"], sources=sources))
    since = SORT_KEY >= _as_utc(s.period_end)
    count, unread = session.execute(
        select(func.count(), func.coalesce(func.sum(Article.is_read.is_(False)), 0)).where(since)
    ).one()
    item = _list_item(session, s)
    return SummaryDetail(
        **item.model_dump(),
        overview=body.get("overview", ""),
        topics=topics,
        new_since=NewSince(count=count, unread_count=int(unread)),
        is_latest=s.id == _latest_id(session),
    )


@router.get("", response_model=list[SummaryListItem])
def list_summaries(session: SessionDep) -> list[SummaryListItem]:
    rows = session.scalars(
        select(Summary).where(_succeeded()).order_by(Summary.created_at.desc(), Summary.id.desc())
    )
    return [_list_item(session, s) for s in rows]


@router.get("/config", response_model=SummaryConfig)
def get_summary_config() -> SummaryConfig:
    interval = get_settings().summary.interval
    return SummaryConfig(
        interval=interval.value,
        next_run_at=next_summary_run(interval, datetime.now().astimezone()),
    )


@router.get("/latest", response_model=SummaryDetail)
def get_latest_summary(session: SessionDep) -> SummaryDetail:
    latest = _latest_id(session)
    if latest is None:
        raise HTTPException(status_code=404, detail="サマリがありません")
    return _detail(session, session.get(Summary, latest))


def _latest_job(session: Session) -> AiJob | None:
    return session.scalar(
        select(AiJob).where(AiJob.kind == JOB_KIND).order_by(AiJob.id.desc()).limit(1)
    )


def _job_period(job: AiJob) -> tuple[datetime, datetime] | None:
    try:
        return (
            datetime.fromisoformat(job.input["period_start"]),
            datetime.fromisoformat(job.input["period_end"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _generation_state(
    session: Session, job: AiJob | None, dismissed: int | None
) -> GenerationState:
    if job is None or job.id == dismissed:
        return GenerationState(state="idle")
    if job.status == STATUS_SUCCEEDED:
        return GenerationState(state="idle", job_id=job.id)
    period = _job_period(job)
    count = None
    if period:
        count = session.scalar(
            select(func.count())
            .select_from(Article)
            .where(Article.published_at >= period[0], Article.published_at < period[1])
        )
    common = {
        "job_id": job.id,
        "period_start": period[0] if period else None,
        "article_count": count,
    }
    if job.status in (STATUS_PENDING, STATUS_RUNNING):
        return GenerationState(
            state="running", step=1 if job.status == STATUS_PENDING else 2, **common
        )
    match = _RESET_RE.search(job.error or "")
    return GenerationState(
        state="failed",
        error=job.error,
        rate_limited=is_rate_limited(job),
        reset_text=match.group(1) if match else None,
        **common,
    )


@router.get("/generation", response_model=GenerationState)
def get_generation(session: SessionDep, dismissed: int | None = None) -> GenerationState:
    """直近のサマリ生成ジョブの状態。失敗を閉じた場合は `dismissed` にそのジョブIDを渡す。"""
    return _generation_state(session, _latest_job(session), dismissed)


@router.post("/generate", response_model=GenerationState)
def generate_summary(request: Request, session: SessionDep) -> GenerationState:
    """今すぐサマリを生成するジョブを起動する。生成中のジョブがあればそれを返す。

    対象期間は、直近のサマリの終端（無ければ設定の周期ぶん前）から現在まで。
    """
    job = _latest_job(session)
    if job is not None and job.status in (STATUS_PENDING, STATUS_RUNNING):
        return _generation_state(session, job, None)

    end = datetime.now(UTC)
    last_end = session.scalar(select(func.max(Summary.period_end)).where(_succeeded()))
    if last_end is not None and _as_utc(last_end) < end:
        start = _as_utc(last_end)
    else:
        start = end - timedelta(days=INTERVAL_DAYS[get_settings().summary.interval])
    has_articles = session.scalar(
        select(func.count())
        .select_from(Article)
        .where(Article.published_at >= start, Article.published_at < end)
    )
    if not has_articles:
        raise HTTPException(
            status_code=409,
            detail={"code": "no_articles", "message": "対象期間に記事がありません"},
        )

    job = enqueue_job(
        session, JOB_KIND, {"period_start": start.isoformat(), "period_end": end.isoformat()}
    )
    runner = getattr(request.app.state, "ai_runner", None)
    if runner is not None:
        runner.notify()
    return _generation_state(session, job, None)


@router.get("/{summary_id}", response_model=SummaryDetail)
def get_summary(summary_id: int, session: SessionDep) -> SummaryDetail:
    s = session.get(Summary, summary_id)
    if s is None or s.status != STATUS_SUCCEEDED:
        raise HTTPException(status_code=404, detail="サマリが見つかりません")
    return _detail(session, s)
