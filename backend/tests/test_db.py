from datetime import UTC, datetime

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError, StatementError

from deep_tracker.config import load_settings
from deep_tracker.db import (
    Article,
    Base,
    Feed,
    Summary,
    SummaryArticle,
    create_db_engine,
    make_session_factory,
    upgrade_db,
)
from deep_tracker.db.models import make_guid


@pytest.fixture
def engine(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"db: {{path: {tmp_path / 'sub' / 'test.db'}}}\n", encoding="utf-8")
    settings = load_settings(cfg)
    upgrade_db(settings)
    eng = create_db_engine(settings.db.path)
    yield eng
    eng.dispose()


def test_migration_creates_db_and_tables(engine):
    names = set(inspect(engine).get_table_names())
    assert {"feeds", "articles", "summaries", "summary_articles", "ai_jobs"} <= names
    assert "alembic_version" in names


def test_migration_matches_models(engine):
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


def test_indexes(engine):
    idx = {i["name"] for i in inspect(engine).get_indexes("articles")}
    assert {
        "ix_articles_published_at",
        "ix_articles_feed_id_published_at",
        "ix_articles_is_read_published_at",
    } <= idx


def test_wal_and_foreign_keys(engine):
    with engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1


def test_duplicate_article_rejected(engine):
    Session = make_session_factory(engine)
    with Session() as s:
        feed = Feed(name="AWS", url="https://aws.amazon.com/jp/about-aws/whats-new/recent/feed/")
        s.add(feed)
        s.flush()
        s.add(Article(feed_id=feed.id, guid="g1", title="a"))
        s.commit()
        s.add(Article(feed_id=feed.id, guid="g1", title="b"))
        with pytest.raises(IntegrityError):
            s.commit()
        s.rollback()
        # 別フィードなら同じGUIDでも登録できる
        other = Feed(name="Other", url="https://example.com/feed")
        s.add(other)
        s.flush()
        s.add(Article(feed_id=other.id, guid="g1", title="c"))
        s.commit()


def test_defaults_and_utc_roundtrip(engine):
    Session = make_session_factory(engine)
    with Session() as s:
        feed = Feed(name="f", url="https://example.com/feed")
        s.add(feed)
        s.flush()
        art = Article(
            feed_id=feed.id,
            guid="g",
            title="t",
            published_at=datetime(2026, 1, 2, 3, 4, tzinfo=UTC),
        )
        s.add(art)
        s.commit()
        s.expire_all()
        got = s.get(Article, art.id)
        assert got.is_read is False and got.read_at is None
        assert got.published_at == datetime(2026, 1, 2, 3, 4, tzinfo=UTC)
        assert s.get(Feed, feed.id).enabled is True
        with pytest.raises(StatementError):
            s.add(Article(feed_id=feed.id, guid="n", title="x", published_at=datetime(2026, 1, 1)))
            s.flush()


def test_cascade_delete(engine):
    Session = make_session_factory(engine)
    now = datetime.now(UTC)
    with Session() as s:
        feed = Feed(name="f", url="https://example.com/feed")
        s.add(feed)
        s.flush()
        art = Article(feed_id=feed.id, guid="g", title="t")
        summary = Summary(period_start=now, period_end=now)
        s.add_all([art, summary])
        s.flush()
        s.add(SummaryArticle(summary_id=summary.id, article_id=art.id))
        s.commit()
        s.delete(feed)
        s.commit()
        assert s.query(Article).count() == 0
        assert s.query(SummaryArticle).count() == 0
        assert s.query(Summary).count() == 1


def test_make_guid_fallback():
    t = datetime(2026, 1, 1, tzinfo=UTC)
    assert make_guid("g", "https://x", "t", t) == "g"
    by_url = make_guid(None, "https://x", "t", t)
    assert by_url.startswith("url:") and by_url == make_guid("", "https://x", "other", None)
    by_title = make_guid(None, None, "t", t)
    assert by_title.startswith("title:")
    assert by_title != make_guid(None, None, "t", None)
