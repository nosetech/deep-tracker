from datetime import timedelta

import pytest
from sqlalchemy import func, select

from deep_tracker.config import load_settings
from deep_tracker.db import Article, Feed, create_db_engine, make_session_factory, upgrade_db
from deep_tracker.db.models import Summary, SummaryArticle, utcnow
from deep_tracker.jobs.retention import purge_expired_articles


@pytest.fixture
def session(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"db: {{path: {tmp_path / 'test.db'}}}\n", encoding="utf-8")
    s = load_settings(cfg)
    upgrade_db(s)
    engine = create_db_engine(s.db.path)
    with make_session_factory(engine)() as sess:
        yield sess
    engine.dispose()


def add_article(session, feed, guid, fetched_at) -> Article:
    a = Article(feed_id=feed.id, guid=guid, title=guid, fetched_at=fetched_at)
    session.add(a)
    session.commit()
    return a


def count(session) -> int:
    return session.scalar(select(func.count()).select_from(Article))


@pytest.fixture
def feed(session):
    f = Feed(name="f", url="https://example.com/feed")
    session.add(f)
    session.commit()
    return f


def test_deletes_only_expired(session, feed):
    now = utcnow()
    add_article(session, feed, "old", now - timedelta(days=366))
    add_article(session, feed, "new", now - timedelta(days=364))
    assert purge_expired_articles(session, 365, now=now) == 1
    assert session.scalars(select(Article.guid)).all() == ["new"]


def test_boundary_is_kept(session, feed):
    now = utcnow()
    add_article(session, feed, "edge", now - timedelta(days=365))
    assert purge_expired_articles(session, 365, now=now) == 0
    assert count(session) == 1


def test_retention_change_applies(session, feed):
    now = utcnow()
    add_article(session, feed, "a", now - timedelta(days=40))
    assert purge_expired_articles(session, 365, now=now) == 0
    assert purge_expired_articles(session, 30, now=now) == 1


def test_nothing_to_delete(session, feed):
    assert purge_expired_articles(session, 365) == 0


def test_summary_kept(session, feed):
    now = utcnow()
    a = add_article(session, feed, "old", now - timedelta(days=400))
    s = Summary(period_start=now, period_end=now, body="b")
    session.add(s)
    session.commit()
    session.add(SummaryArticle(summary_id=s.id, article_id=a.id))
    session.commit()
    purge_expired_articles(session, 365, now=now)
    assert session.get(Summary, s.id) is not None
    assert session.scalar(select(func.count()).select_from(SummaryArticle)) == 0
