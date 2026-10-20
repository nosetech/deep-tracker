import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from deep_tracker.ai import AIProvider, AIResult
from deep_tracker.config import load_settings
from deep_tracker.db import (
    AiJob,
    Article,
    Feed,
    Summary,
    create_db_engine,
    make_session_factory,
    upgrade_db,
)
from deep_tracker.jobs.ai_jobs import AIJobRunner, enqueue_job
from deep_tracker.summary import (
    InvalidSummaryOutput,
    generate_summary,
    make_summary_handler,
    parse_summary_output,
)

END = datetime(2026, 1, 8, tzinfo=UTC)
START = END - timedelta(days=7)


class MockProvider(AIProvider):
    def __init__(self, text):
        self.text = text
        self.calls = []

    def generate(self, prompt, *, system_prompt=None, input_text=None):
        self.calls.append((prompt, input_text))
        return AIResult(text=self.text)


@pytest.fixture
def factory(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"db: {{path: {tmp_path / 'test.db'}}}\n", encoding="utf-8")
    settings = load_settings(cfg)
    upgrade_db(settings)
    engine = create_db_engine(settings.db.path)
    yield make_session_factory(engine)
    engine.dispose()


def add_articles(session):
    feed = Feed(name="f", url="https://example.com/feed")
    session.add(feed)
    session.flush()
    arts = [
        Article(
            feed=feed,
            guid="a",
            title="A",
            content="x" * 1000,
            published_at=START + timedelta(days=1),
        ),
        Article(feed=feed, guid="b", title="B", published_at=START + timedelta(days=2)),
        Article(feed=feed, guid="old", title="Old", published_at=START - timedelta(days=1)),
    ]
    session.add_all(arts)
    session.commit()
    return arts


def output(ids):
    return json.dumps(
        {"overview": "総評", "topics": [{"title": "T", "summary": "S", "article_ids": ids}]}
    )


def test_generates_and_links_articles(factory):
    with factory() as s:
        a, b, _old = add_articles(s)
        provider = MockProvider(output([a.id, b.id]))
        summary = generate_summary(s, provider, START, END)

        assert summary.status == "succeeded"
        assert json.loads(summary.body)["topics"][0]["article_ids"] == [a.id, b.id]
        assert {x.id for x in summary.articles} == {a.id, b.id}
        sent = json.loads(provider.calls[0][1])
        assert [x["title"] for x in sent] == ["B", "A"]  # 期間外は含まれず、新しい順
        assert len(sent[1]["excerpt"]) == 300


def test_unknown_ids_dropped(factory):
    with factory() as s:
        a, _b, _old = add_articles(s)
        summary = generate_summary(s, MockProvider(output([a.id, 9999])), START, END)
        assert json.loads(summary.body)["topics"][0]["article_ids"] == [a.id]


def test_no_articles_skips(factory):
    with factory() as s:
        provider = MockProvider(output([1]))
        assert generate_summary(s, provider, START, END) is None
        assert provider.calls == []
        assert s.scalar(select(Summary)) is None


@pytest.mark.parametrize(
    "text",
    ["not json", "{}", '{"overview": "x", "topics": []}', output([9999]), output([])],
)
def test_invalid_output_recorded_as_failed(factory, text):
    with factory() as s:
        add_articles(s)
        with pytest.raises(InvalidSummaryOutput):
            generate_summary(s, MockProvider(text), START, END)
        summary = s.scalar(select(Summary))
        assert summary.status == "failed"
        assert summary.body is None


def test_code_fence_tolerated():
    body = parse_summary_output("```json\n" + output([1]) + "\n```", {1})
    assert body["overview"] == "総評"


def test_job_handler_success_and_failure(factory):
    with factory() as s:
        a, _b, _old = add_articles(s)
        ids = [a.id]
        payload = {"period_start": START.isoformat(), "period_end": END.isoformat()}
        ok = enqueue_job(s, "summary", payload).id

    handlers = {"summary": make_summary_handler(factory)}
    assert AIJobRunner(factory, MockProvider(output(ids)), handlers).run_next()
    with factory() as s:
        job = s.get(AiJob, ok)
        assert job.status == "succeeded"
        assert job.result["article_count"] == 1
        bad = enqueue_job(s, "summary", payload).id

    assert AIJobRunner(factory, MockProvider("oops"), handlers).run_next()
    with factory() as s:
        job = s.get(AiJob, bad)
        assert job.status == "failed"
        assert "不正" in job.error
