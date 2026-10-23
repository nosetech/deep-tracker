import json
from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from deep_tracker.ai import AIError, AIProvider, AIResult
from deep_tracker.config import load_settings
from deep_tracker.config.models import SummaryInterval
from deep_tracker.db import (
    Article,
    Feed,
    Summary,
    create_db_engine,
    make_session_factory,
    upgrade_db,
)
from deep_tracker.jobs.summary import run_scheduled_summary, summary_period

JST = timezone(timedelta(hours=9))
# 2026-01-14(水) 10:00 JST
NOW = datetime(2026, 1, 14, 10, 0, tzinfo=JST)


class MockProvider(AIProvider):
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = 0

    def generate(self, prompt, *, system_prompt=None, input_text=None):
        self.calls += 1
        if self.fail:
            raise AIError("利用制限に達しました")
        ids = [a["id"] for a in json.loads(input_text)]
        body = {"overview": "o", "topics": [{"title": "t", "summary": "s", "article_ids": ids}]}
        return AIResult(text=json.dumps(body))


class FakeNotifier:
    def __init__(self):
        self.sent = []
        self.bodies = []

    def notify(self, title, body=None, path=None):
        self.sent.append(title)
        self.bodies.append(body)
        return True


@pytest.fixture
def env(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"db: {{path: {tmp_path / 'test.db'}}}\n", encoding="utf-8")
    settings = load_settings(cfg)
    upgrade_db(settings)
    engine = create_db_engine(settings.db.path)
    with make_session_factory(engine)() as session:
        feed = Feed(name="f", url="https://example.com/feed")
        session.add(feed)
        session.flush()
        # 直近の完了週（2026-01-05〜01-12 JST）に収まる記事
        session.add(
            Article(
                feed=feed,
                guid="a",
                title="A",
                content="c",
                url="https://example.com/a",
                published_at=datetime(2026, 1, 7, tzinfo=UTC),
            )
        )
        session.commit()
        yield session, settings
    engine.dispose()


@pytest.mark.parametrize(
    ("interval", "start", "end"),
    [
        (SummaryInterval.DAILY, datetime(2026, 1, 12, 15), datetime(2026, 1, 13, 15)),
        (SummaryInterval.WEEKLY, datetime(2026, 1, 4, 15), datetime(2026, 1, 11, 15)),
        (SummaryInterval.MONTHLY, datetime(2025, 11, 30, 15), datetime(2025, 12, 31, 15)),
    ],
)
def test_summary_period(interval, start, end):
    now = datetime(2026, 1, 14, 10, 0, tzinfo=JST)
    got = summary_period(interval, now)
    assert got == (start.replace(tzinfo=UTC), end.replace(tzinfo=UTC))


def test_generates_once_per_period(env):
    session, settings = env
    provider, notifier = MockProvider(), FakeNotifier()
    first = run_scheduled_summary(session, provider, settings, now=NOW, notifier=notifier)
    assert first is not None
    assert first.status == "succeeded"
    assert run_scheduled_summary(session, provider, settings, now=NOW, notifier=notifier) is None
    assert provider.calls == 1
    assert notifier.sent == ["サマリを生成しました"]


def test_next_period_generates_again(env):
    session, settings = env
    provider = MockProvider()
    run_scheduled_summary(session, provider, settings, now=NOW, notifier=FakeNotifier())
    run_scheduled_summary(
        session, provider, settings, now=NOW + timedelta(days=7), notifier=FakeNotifier()
    )
    # 次の週は記事が無いため生成されない（AI呼び出しも増えない）
    assert provider.calls == 1
    assert len(session.scalars(select(Summary)).all()) == 1


def test_failure_is_recorded_and_not_retried(env):
    session, settings = env
    provider, notifier = MockProvider(fail=True), FakeNotifier()
    with pytest.raises(AIError):
        run_scheduled_summary(session, provider, settings, now=NOW, notifier=notifier)
    assert session.scalars(select(Summary)).one().status == "failed"
    assert notifier.sent == ["サマリの生成に失敗しました"]
    # 同じ期間では再実行しない
    assert run_scheduled_summary(session, provider, settings, now=NOW, notifier=notifier) is None
    assert provider.calls == 1


def test_success_notification_lists_topics(env):
    session, settings = env
    notifier = FakeNotifier()
    run_scheduled_summary(session, MockProvider(), settings, now=NOW, notifier=notifier)
    assert "• t" in notifier.bodies[0]


def test_failure_notification_can_be_disabled(env, tmp_path):
    session, _ = env
    cfg = tmp_path / "off.yaml"
    cfg.write_text("slack: {notify_on_failure: false}\n", encoding="utf-8")
    notifier = FakeNotifier()
    with pytest.raises(AIError):
        run_scheduled_summary(
            session, MockProvider(fail=True), load_settings(cfg), now=NOW, notifier=notifier
        )
    assert notifier.sent == []


def test_topic_titles_tolerate_malformed_body():
    from deep_tracker.jobs.summary import _topic_titles

    assert _topic_titles(Summary(body="[1]")) == []
    assert _topic_titles(Summary(body='{"topics": null}')) == []
    assert _topic_titles(Summary(body='{"topics": [{}]}')) == []
    assert _topic_titles(Summary(body='{"topics": [{"title": "<!channel>"}]}')) == [
        "&lt;!channel&gt;"
    ]
