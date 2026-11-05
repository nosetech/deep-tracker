from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from deep_tracker.api.deps import get_session
from deep_tracker.db import AiJob
from deep_tracker.jobs.ai_jobs import STATUSES, is_rate_limited

router = APIRouter(prefix="/ai-jobs", tags=["ai-jobs"])

SessionDep = Annotated[Session, Depends(get_session)]


class AiJobOut(BaseModel):
    id: int
    kind: str
    status: str
    input: Any | None
    result: Any | None
    error: str | None
    # 利用制限による失敗。GUIは再試行を促す
    rate_limited: bool
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


def _to_out(job: AiJob) -> AiJobOut:
    return AiJobOut(
        id=job.id,
        kind=job.kind,
        status=job.status,
        input=job.input,
        result=job.result,
        error=job.error,
        rate_limited=is_rate_limited(job),
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


@router.get("", response_model=list[AiJobOut])
def list_ai_jobs(
    session: SessionDep,
    status: str | None = None,
    kind: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[AiJobOut]:
    if status is not None and status not in STATUSES:
        raise HTTPException(status_code=422, detail=f"status は {', '.join(STATUSES)} のいずれか")
    stmt = select(AiJob).order_by(AiJob.id.desc()).limit(limit)
    if status is not None:
        stmt = stmt.where(AiJob.status == status)
    if kind is not None:
        stmt = stmt.where(AiJob.kind == kind)
    return [_to_out(j) for j in session.scalars(stmt)]


@router.get("/{job_id}", response_model=AiJobOut)
def get_ai_job(job_id: int, session: SessionDep) -> AiJobOut:
    job = session.get(AiJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="ジョブが見つかりません")
    return _to_out(job)
