from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select

from deep_tracker.config import load_settings
from deep_tracker.db import Article, Feed, create_db_engine, make_session_factory, upgrade_db
from deep_tracker.db.models import utcnow
from deep_tracker.jobs.fetch import (
    AlreadyRunningError,
    is_due,
    lock_path_for,
    run_fetch,
    single_instance,
)

AWS_URL = "https://aws.amazon.com/jp/about-aws/whats-new/recent/feed/"
AWS_XML = (Path(__file__).parent / "fixtures" / "aws_whats_new.xml").read_bytes()


def mock_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def aws_client() -> httpx.Client:
    return mock_client(lambda req: httpx.Response(200, content=AWS_XML))


def add_feed(session, url, name) -> Feed:
    feed = Feed(name=name, url=url)
    session.add(feed)
    session.commit()
    return feed


@pytest.fixture
def settings(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"db: {{path: {tmp_path / 'test.db'}}}\n", encoding="utf-8")
    s = load_settings(cfg)
    upgrade_db(s)
    return s


@pytest.fixture
def session(settings):
    engine = create_db_engine(settings.db.path)
    with make_session_factory(engine)() as s:
        yield s
    engine.dispose()


def test_is_due_never_fetched():
    assert is_due(Feed(name="f", url="u"), 60, utcnow())


def test_is_due_respects_interval_and_tolerance():
    now = utcnow()
    feed = Feed(name="f", url="u", last_fetched_at=now - timedelta(minutes=30))
    assert not is_due(feed, 60, now)
    assert is_due(feed, 30, now)  # 間隔ちょうど
    feed.last_fetched_at = now - timedelta(minutes=59, seconds=30)
    assert is_due(feed, 60, now)  # 起動の揺らぎ分は許容
    feed.fetch_interval_minutes = 120  # フィード個別の間隔が優先される
    assert not is_due(feed, 60, now)


def test_is_due_naive_datetime_from_sqlite():
    now = utcnow()
    feed = Feed(name="f", url="u", last_fetched_at=(now - timedelta(hours=2)).replace(tzinfo=None))
    assert is_due(feed, 60, now)


def test_run_fetch_only_due_enabled_feeds(session, settings):
    due = add_feed(session, AWS_URL, "due")
    recent = add_feed(session, "https://example.com/recent.xml", "recent")
    recent.last_fetched_at = utcnow()
    disabled = add_feed(session, "https://example.com/disabled.xml", "disabled")
    disabled.enabled = False
    session.commit()

    report = run_fetch(session, settings, client=aws_client())

    assert (report.total, report.due) == (2, 1)
    assert report.added > 0 and report.failed == []
    assert session.get(Feed, due.id).last_fetched_at is not None
    assert session.scalar(select(func.count()).select_from(Article)) == report.added


def test_run_fetch_reports_failures_and_continues(session, settings):
    add_feed(session, "https://example.com/broken.xml", "broken")
    add_feed(session, AWS_URL, "ok")

    def handler(req: httpx.Request) -> httpx.Response:
        if "broken" in str(req.url):
            return httpx.Response(500)
        return httpx.Response(200, content=AWS_XML)

    report = run_fetch(session, settings, client=mock_client(handler))

    assert report.due == 2 and report.added > 0
    assert [u for u, _ in report.failed] == ["https://example.com/broken.xml"]


def test_single_instance_blocks_second_runner(tmp_path):
    lock = tmp_path / "fetch.lock"
    with single_instance(lock):
        with pytest.raises(AlreadyRunningError):
            with single_instance(lock):
                pass
    with single_instance(lock):  # 解放後は再取得できる
        pass


def test_lock_path_is_next_to_db(settings, tmp_path):
    assert lock_path_for(settings) == tmp_path / "fetch.lock"
