"""AIジョブの実行管理。

`ai_jobs` テーブルに状態を保存しながら、待機中のジョブを設定された同時実行数（既定1）で処理する。
失敗時の自動リトライはしない。利用制限エラーは理由として保存し、再試行は画面から促す。
"""

import logging
import threading
from collections.abc import Callable
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from deep_tracker.ai import AIError, AIProvider, RateLimitError
from deep_tracker.db import AiJob
from deep_tracker.db.models import utcnow

logger = logging.getLogger("deep_tracker.jobs.ai_jobs")

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"
STATUSES = (STATUS_PENDING, STATUS_RUNNING, STATUS_SUCCEEDED, STATUS_FAILED)

# 利用制限エラーの失敗理由の接頭辞。GUIはこれで再試行を促す表示に切り替える
RATE_LIMIT_ERROR_PREFIX = "利用制限に達しました"
INTERRUPTED_ERROR = "アプリの再起動により中断されました"

# (入力, プロバイダ) -> 結果。AIError 以外の例外も失敗として記録される
JobHandler = Callable[[Any, AIProvider], Any]


def enqueue_job(session: Session, kind: str, input_data: Any = None) -> AiJob:
    job = AiJob(kind=kind, status=STATUS_PENDING, input=input_data)
    session.add(job)
    session.commit()
    return job


def is_rate_limited(job: AiJob) -> bool:
    return job.status == STATUS_FAILED and (job.error or "").startswith(RATE_LIMIT_ERROR_PREFIX)


def recover_interrupted_jobs(session: Session) -> int:
    """再起動時に、実行中のまま残ったジョブを失敗として整理する。"""
    result = session.execute(
        update(AiJob)
        .where(AiJob.status == STATUS_RUNNING)
        .values(status=STATUS_FAILED, error=INTERRUPTED_ERROR, finished_at=utcnow())
    )
    session.commit()
    count = result.rowcount
    if count:
        logger.warning("実行中のまま残ったAIジョブ %d 件を失敗として整理しました", count)
    return count


def _claim_next(session: Session) -> int | None:
    """待機中の最古のジョブを実行中にして返す。複数ワーカーでも二重に取らない。"""
    while True:
        job_id = session.scalar(
            select(AiJob.id)
            .where(AiJob.status == STATUS_PENDING)
            .order_by(AiJob.created_at, AiJob.id)
            .limit(1)
        )
        if job_id is None:
            return None
        claimed = session.execute(
            update(AiJob)
            .where(AiJob.id == job_id, AiJob.status == STATUS_PENDING)
            .values(status=STATUS_RUNNING, started_at=utcnow())
        )
        session.commit()
        if claimed.rowcount:
            return job_id


def _failure_message(e: Exception) -> str:
    if isinstance(e, RateLimitError):
        message = f"{RATE_LIMIT_ERROR_PREFIX}: {e}"
        if e.reset_text:
            message += f"（解除予定: {e.reset_text}）"
        return message
    if isinstance(e, AIError):
        return str(e) or type(e).__name__
    return f"{type(e).__name__}: {e}"


class AIJobRunner:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        provider: AIProvider,
        handlers: dict[str, JobHandler],
        *,
        concurrency: int = 1,
        poll_seconds: float = 1.0,
    ):
        self._session_factory = session_factory
        self._provider = provider
        self._handlers = handlers
        self._concurrency = concurrency
        self._poll_seconds = poll_seconds
        self._stop = threading.Event()
        self._wakeup = threading.Event()
        self._threads: list[threading.Thread] = []

    def run_next(self) -> bool:
        """待機中のジョブを1件処理する。処理したら True、無ければ False。"""
        with self._session_factory() as session:
            job_id = _claim_next(session)
            if job_id is None:
                return False
            job = session.get(AiJob, job_id)
            try:
                handler = self._handlers.get(job.kind)
                if handler is None:
                    raise AIError(f"未対応のジョブ種別: {job.kind}")
                job.result = handler(job.input, self._provider)
                job.status = STATUS_SUCCEEDED
            except Exception as e:
                # 自動リトライはしない。理由を保存して終わる
                logger.warning("AIジョブ %d (%s) が失敗しました: %s", job.id, job.kind, e)
                job.status = STATUS_FAILED
                job.error = _failure_message(e)
            job.finished_at = utcnow()
            session.commit()
        return True

    def notify(self) -> None:
        """ジョブを追加した際に呼び、待機中のワーカーを即座に起こす。"""
        self._wakeup.set()

    def start(self) -> None:
        for i in range(self._concurrency):
            t = threading.Thread(target=self._work, name=f"ai-job-{i}", daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self) -> None:
        self._stop.set()
        self._wakeup.set()
        for t in self._threads:
            t.join()
        self._threads.clear()

    def _work(self) -> None:
        while not self._stop.is_set():
            try:
                if self.run_next():
                    continue
            except Exception:
                logger.exception("AIジョブの実行ループでエラーが発生しました")
            self._wakeup.wait(self._poll_seconds)
            self._wakeup.clear()
