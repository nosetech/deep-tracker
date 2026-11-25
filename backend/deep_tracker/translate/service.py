"""日本語以外の記事のタイトルと本文を日本語に翻訳して保存する。

翻訳は `articles.title_ja` / `content_ja` に保存し、原文（`title` / `content`）は変更しない。
"""

import json
import logging
from collections.abc import Iterable
from importlib import resources
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from deep_tracker.ai import AIError, AIProvider
from deep_tracker.ai.output import strip_code_fence
from deep_tracker.config.models import TranslationSettings
from deep_tracker.db import AiJob, Article
from deep_tracker.db.models import utcnow
from deep_tracker.jobs.ai_jobs import (
    STATUS_PENDING,
    STATUS_RUNNING,
    JobHandler,
    enqueue_job,
)
from deep_tracker.translate.detect import LANG_OTHER

logger = logging.getLogger("deep_tracker.translate")

JOB_KIND = "translate_article"

# 翻訳する本文の最大文字数。超えた分は翻訳せず、先頭のみ翻訳した旨を記録する
MAX_CONTENT_CHARS = 20_000


class InvalidTranslationOutput(AIError):
    """AIの出力が期待する構造になっていない。"""


class _TranslationOutput(BaseModel):
    title: str
    content: str


def load_prompt() -> str:
    return (
        resources.files("deep_tracker.translate")
        .joinpath("prompts/translate.md")
        .read_text("utf-8")
    )


def truncate_content(content: str, limit: int | None = None) -> tuple[str, bool]:
    """本文を上限文字数（既定 MAX_CONTENT_CHARS）で切り詰め、(本文, 切り詰めたか) を返す。

    タグの途中では切らない。
    """
    limit = MAX_CONTENT_CHARS if limit is None else limit
    if len(content) <= limit:
        return content, False
    head = content[:limit]
    # 末尾に閉じていないタグが残る場合は、その手前で切る
    lt = head.rfind("<")
    if lt > head.rfind(">"):
        head = head[:lt]
    return head.rstrip(), True


def parse_translation_output(text: str, *, has_content: bool) -> dict[str, str]:
    """AIの出力を検証して返す。不正なら InvalidTranslationOutput。"""
    try:
        output = _TranslationOutput.model_validate_json(strip_code_fence(text))
    except ValidationError as e:
        raise InvalidTranslationOutput(
            f"翻訳の出力が不正です: {e.error_count()} 件の検証エラー"
        ) from e
    if not output.title.strip():
        raise InvalidTranslationOutput("翻訳の出力が不正です: タイトルが空です")
    if has_content and not output.content.strip():
        raise InvalidTranslationOutput("翻訳の出力が不正です: 本文が空です")
    return {"title": output.title.strip(), "content": output.content.strip()}


def translate_article(session: Session, provider: AIProvider, article: Article) -> None:
    """記事を翻訳して保存する。失敗時は例外を送出し、記事は変更しない。"""
    content, truncated = truncate_content((article.content or "").strip())
    payload = json.dumps({"title": article.title, "content": content}, ensure_ascii=False)
    result = provider.generate(load_prompt(), input_text=payload)
    output = parse_translation_output(result.text, has_content=bool(content))
    article.title_ja = output["title"]
    article.content_ja = output["content"] or None
    article.translation_truncated = truncated
    article.translated_at = utcnow()
    # language は判定結果のまま残す（手動翻訳した日本語の記事を other に書き換えない）
    session.commit()


def make_translate_handler(session_factory: sessionmaker[Session]) -> JobHandler:
    """AIジョブ（kind=translate_article）のハンドラを返す。入力は {"article_id": int}。"""

    def handler(input_data: Any, provider: AIProvider) -> dict[str, Any]:
        article_id = int(input_data["article_id"])
        with session_factory() as session:
            article = session.get(Article, article_id)
            if article is None:
                # 保存期間による削除・フィード削除で消えた
                raise AIError(f"記事が見つかりません（id={article_id}）")
            translate_article(session, provider, article)
            return {"article_id": article.id, "truncated": article.translation_truncated}

    return handler


def find_active_job(session: Session, article_id: int) -> AiJob | None:
    """記事の翻訳ジョブのうち、待機中・実行中のものを返す。"""
    return session.scalar(
        select(AiJob)
        .where(
            AiJob.kind == JOB_KIND,
            AiJob.status.in_((STATUS_PENDING, STATUS_RUNNING)),
            AiJob.input["article_id"].as_integer() == article_id,
        )
        .order_by(AiJob.id.desc())
        .limit(1)
    )


def latest_job(session: Session, article_id: int) -> AiJob | None:
    """記事の最新の翻訳ジョブを返す。"""
    return session.scalar(
        select(AiJob)
        .where(AiJob.kind == JOB_KIND, AiJob.input["article_id"].as_integer() == article_id)
        .order_by(AiJob.id.desc())
        .limit(1)
    )


def enqueue_translation(session: Session, article_id: int) -> AiJob:
    """記事の翻訳ジョブを投入する。待機中・実行中のジョブがあればそれを返す。"""
    return find_active_job(session, article_id) or enqueue_job(
        session, JOB_KIND, {"article_id": article_id}
    )


def enqueue_new_articles(
    session: Session, articles: Iterable[Article], settings: TranslationSettings
) -> int:
    """取得で新規保存した記事のうち、日本語以外のものを新しい順に上限件数まで投入する。

    記事は保存（commit）済みであること。投入件数を返す。
    """
    if not settings.enabled:
        return 0
    targets = [a for a in articles if a.language == LANG_OTHER and a.translated_at is None]
    targets.sort(key=lambda a: (a.published_at or a.fetched_at, a.id), reverse=True)
    for article in targets[: settings.max_per_fetch]:
        enqueue_job(session, JOB_KIND, {"article_id": article.id})
    if len(targets) > settings.max_per_fetch:
        logger.info(
            "翻訳対象 %d 件のうち %d 件を投入しました（残りは手動で翻訳できます）",
            len(targets),
            settings.max_per_fetch,
        )
    return min(len(targets), settings.max_per_fetch)
