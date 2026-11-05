"""期間内の記事からトピックごとのサマリを生成して保存する。

`summaries.body` には {"overview", "topics": [{"title", "summary", "article_ids"}]} のJSONを保存し、
トピックに挙がった元記事を `summary_articles` に紐づける。
"""

import json
import logging
from datetime import datetime
from importlib import resources
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from deep_tracker.ai import AIError, AIProvider
from deep_tracker.db import Article, Summary
from deep_tracker.jobs.ai_jobs import (
    STATUS_FAILED,
    STATUS_RUNNING,
    STATUS_SUCCEEDED,
    JobHandler,
)

logger = logging.getLogger("deep_tracker.summary")

JOB_KIND = "summary"

# プロンプトに含める記事数の上限。超えた分は新しい順に切り捨てる
MAX_ARTICLES = 200
# 記事1件あたりの抜粋の最大文字数。タイトルを優先し、本文は先頭のみ使う
MAX_EXCERPT_CHARS = 300


class InvalidSummaryOutput(AIError):
    """AIの出力が期待する構造になっていない。"""


class _Topic(BaseModel):
    title: str
    summary: str
    article_ids: list[int]


class _SummaryOutput(BaseModel):
    overview: str
    topics: list[_Topic]


def load_prompt() -> str:
    return resources.files("deep_tracker.summary").joinpath("prompts/summary.md").read_text("utf-8")


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines[1:])
    return text.strip()


def parse_summary_output(text: str, valid_article_ids: set[int]) -> dict[str, Any]:
    """AIの出力を検証して返す。入力に無い記事IDは取り除き、不正なら InvalidSummaryOutput。"""
    try:
        output = _SummaryOutput.model_validate_json(_strip_code_fence(text))
    except ValidationError as e:
        raise InvalidSummaryOutput(
            f"サマリの出力が不正です: {e.error_count()} 件の検証エラー"
        ) from e
    if not output.overview.strip() or not output.topics:
        raise InvalidSummaryOutput("サマリの出力が不正です: 総評またはトピックが空です")

    topics = []
    for topic in output.topics:
        ids = [i for i in dict.fromkeys(topic.article_ids) if i in valid_article_ids]
        if not topic.title.strip() or not topic.summary.strip() or not ids:
            raise InvalidSummaryOutput(
                f"サマリの出力が不正です: トピック「{topic.title}」に有効な元記事がありません"
            )
        topics.append({"title": topic.title, "summary": topic.summary, "article_ids": ids})
    return {"overview": output.overview, "topics": topics}


def _article_payload(article: Article) -> dict[str, Any]:
    excerpt = (article.content or "").strip()[:MAX_EXCERPT_CHARS]
    return {"id": article.id, "title": article.title, "excerpt": excerpt}


def generate_summary(
    session: Session,
    provider: AIProvider,
    period_start: datetime,
    period_end: datetime,
) -> Summary | None:
    """期間内の記事からサマリを生成する。記事が0件なら生成せず None を返す。

    AI呼び出しや出力検証に失敗した場合は、status=failed のサマリを残して例外を再送出する。
    """
    articles = list(
        session.scalars(
            select(Article)
            .where(Article.published_at >= period_start, Article.published_at < period_end)
            .order_by(Article.published_at.desc(), Article.id.desc())
            .limit(MAX_ARTICLES)
        )
    )
    if not articles:
        logger.info("対象期間に記事が無いため、サマリを生成しません")
        return None

    summary = Summary(period_start=period_start, period_end=period_end, status=STATUS_RUNNING)
    session.add(summary)
    session.commit()
    try:
        payload = json.dumps([_article_payload(a) for a in articles], ensure_ascii=False)
        result = provider.generate(load_prompt(), input_text=payload)
        body = parse_summary_output(result.text, {a.id for a in articles})
    except Exception:
        summary.status = STATUS_FAILED
        session.commit()
        raise

    used_ids = {i for t in body["topics"] for i in t["article_ids"]}
    summary.body = json.dumps(body, ensure_ascii=False)
    summary.articles = [a for a in articles if a.id in used_ids]
    summary.status = STATUS_SUCCEEDED
    session.commit()
    return summary


def make_summary_handler(session_factory: sessionmaker[Session]) -> JobHandler:
    """AIジョブ（kind=summary）のハンドラを返す。

    入力は {"period_start": ISO8601, "period_end": ISO8601}（タイムゾーン付き）。
    """

    def handler(input_data: Any, provider: AIProvider) -> dict[str, Any]:
        start = datetime.fromisoformat(input_data["period_start"])
        end = datetime.fromisoformat(input_data["period_end"])
        with session_factory() as session:
            summary = generate_summary(session, provider, start, end)
            if summary is None:
                return {"summary_id": None, "skipped": "対象期間に記事がありません"}
            return {"summary_id": summary.id, "article_count": len(summary.articles)}

    return handler
