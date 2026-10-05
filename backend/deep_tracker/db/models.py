import hashlib
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class UtcDateTime(TypeDecorator):
    """SQLite は TZ を保持しないため、UTC の naive 値で保存し、読み出し時に UTC を付ける。"""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("タイムゾーン付きの datetime を指定してください")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        return None if value is None else value.replace(tzinfo=UTC)


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    # Alembic で制約名を安定させる（SQLite の batch mode で必要）
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )
    type_annotation_map = {datetime: UtcDateTime}


class Feed(Base):
    __tablename__ = "feeds"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    url: Mapped[str] = mapped_column(String(2048), unique=True)
    # NULL の場合は設定 feed.fetch_interval_minutes を使う
    fetch_interval_minutes: Mapped[int | None] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    last_fetched_at: Mapped[datetime | None]
    # 最終取得の成否。未取得は NULL
    last_fetch_ok: Mapped[bool | None] = mapped_column(Boolean)
    last_fetch_error: Mapped[str | None] = mapped_column(Text)
    # 条件付きGET用。次回取得時に If-None-Match / If-Modified-Since として送る
    etag: Mapped[str | None] = mapped_column(String(512))
    last_modified: Mapped[str | None] = mapped_column(String(128))

    articles: Mapped[list["Article"]] = relationship(
        back_populates="feed", cascade="all, delete-orphan", passive_deletes=True
    )


def make_guid(guid: str | None, url: str | None, title: str, published_at: datetime | None) -> str:
    """記事の同一性キーを返す。GUID → URL → タイトル+公開日時のハッシュの順でフォールバックする。"""
    if guid:
        return guid
    if url:
        return "url:" + hashlib.sha256(url.encode()).hexdigest()
    basis = f"{title}\n{published_at.isoformat() if published_at else ''}"
    return "title:" + hashlib.sha256(basis.encode()).hexdigest()


class Article(Base):
    __tablename__ = "articles"
    __table_args__ = (
        # 同一記事の二重登録を防ぐ
        UniqueConstraint("feed_id", "guid", name="uq_articles_feed_id_guid"),
        Index("ix_articles_published_at", "published_at"),
        Index("ix_articles_feed_id_published_at", "feed_id", "published_at"),
        Index("ix_articles_is_read_published_at", "is_read", "published_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    feed_id: Mapped[int] = mapped_column(ForeignKey("feeds.id", ondelete="CASCADE"))
    # フィードのGUID。無い場合は make_guid() のフォールバック値
    guid: Mapped[str] = mapped_column(String(2048))
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(String(2048))
    # 本文または要約（フィードが提供するもの）
    content: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None]
    fetched_at: Mapped[datetime] = mapped_column(default=utcnow)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    read_at: Mapped[datetime | None]

    feed: Mapped[Feed] = relationship(back_populates="articles")


class SummaryArticle(Base):
    """サマリと元記事の関連。"""

    __tablename__ = "summary_articles"

    summary_id: Mapped[int] = mapped_column(
        ForeignKey("summaries.id", ondelete="CASCADE"), primary_key=True
    )
    # 記事が保存期間で削除されても、サマリ側の関連のみ消える
    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"), primary_key=True, index=True
    )


class Summary(Base):
    __tablename__ = "summaries"
    __table_args__ = (Index("ix_summaries_period_start", "period_start"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    period_start: Mapped[datetime]
    period_end: Mapped[datetime]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    # 生成前・失敗時は NULL
    body: Mapped[str | None] = mapped_column(Text)
    # pending / running / succeeded / failed
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")

    articles: Mapped[list[Article]] = relationship(secondary="summary_articles")


class AiJob(Base):
    __tablename__ = "ai_jobs"
    __table_args__ = (Index("ix_ai_jobs_status_created_at", "status", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # 例: summary / article_summary
    kind: Mapped[str] = mapped_column(String(32))
    # pending / running / succeeded / failed
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")
    input: Mapped[Any | None] = mapped_column(JSON)
    result: Mapped[Any | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
