import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from deep_tracker.api.deps import get_session
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
from deep_tracker.main import app


@pytest.fixture
def factory(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"db: {{path: {tmp_path / 'test.db'}}}\n", encoding="utf-8")
    settings = load_settings(cfg)
    monkeypatch.setattr("deep_tracker.api.summaries.get_settings", lambda: settings)
    upgrade_db(settings)
    engine = create_db_engine(settings.db.path)
    yield make_session_factory(engine)
    engine.dispose()


@pytest.fixture
def client(factory):
    def _session():
        with factory() as s:
            yield s

    app.dependency_overrides[get_session] = _session
    # lifespan（ジョブランナー）は起動しない
    yield TestClient(app)
    app.dependency_overrides.clear()


def _seed(factory, *, with_summary=True):
    now = datetime.now(UTC)
    with factory() as s:
        feed = Feed(name="AWS", url="https://example.com/feed")
        s.add(feed)
        s.flush()
        old = Article(
            feed_id=feed.id,
            guid="1",
            title="古い記事",
            url="https://example.com/1",
            published_at=now - timedelta(days=10),
        )
        new = Article(
            feed_id=feed.id,
            guid="2",
            title="新しい記事",
            url="https://example.com/2",
            published_at=now - timedelta(days=1),
        )
        s.add_all([old, new])
        s.flush()
        if with_summary:
            body = {
                "overview": "総評",
                "topics": [{"title": "T1", "summary": "S1", "article_ids": [old.id]}],
            }
            s.add(
                Summary(
                    period_start=now - timedelta(days=14),
                    period_end=now - timedelta(days=7),
                    body=json.dumps(body),
                    status="succeeded",
                    articles=[old],
                )
            )
            s.add(Summary(period_start=now, period_end=now, status="failed"))
        s.commit()


def test_empty(client):
    assert client.get("/api/summaries").json() == []
    assert client.get("/api/summaries/latest").status_code == 404
    assert client.get("/api/summaries/generation").json()["state"] == "idle"


def test_list_and_detail(client, factory):
    _seed(factory)
    items = client.get("/api/summaries").json()
    assert len(items) == 1
    assert items[0]["kind"] == "手動生成"
    assert items[0]["article_count"] == 1
    assert items[0]["topic_count"] == 1

    detail = client.get("/api/summaries/latest").json()
    assert detail["overview"] == "総評"
    assert detail["is_latest"] is True
    assert detail["topic_count"] == 1
    assert detail["topics"][0]["sources"][0]["title"] == "古い記事"
    assert detail["new_since"] == {"count": 1, "unread_count": 1}
    assert client.get(f"/api/summaries/{items[0]['id']}").status_code == 200
    # 失敗したサマリは見えない
    assert client.get("/api/summaries/2").status_code == 404


def test_generate_enqueues_job_once(client, factory):
    _seed(factory)
    res = client.post("/api/summaries/generate")
    assert res.status_code == 200
    body = res.json()
    assert body["state"] == "running"
    assert body["step"] == 1
    # 直近サマリの終端以降の記事（新しい記事の1件）
    assert body["article_count"] == 1
    # 生成中の再実行は同じジョブを返す
    assert client.post("/api/summaries/generate").json()["job_id"] == body["job_id"]
    with factory() as s:
        assert s.query(AiJob).count() == 1


def test_generate_without_articles(client, factory):
    res = client.post("/api/summaries/generate")
    assert res.status_code == 409


def test_generation_failed_rate_limited(client, factory):
    _seed(factory)
    job_id = client.post("/api/summaries/generate").json()["job_id"]
    with factory() as s:
        job = s.get(AiJob, job_id)
        job.status = "failed"
        job.error = "利用制限に達しました: limit（解除予定: 15:00）"
        s.commit()
    state = client.get("/api/summaries/generation").json()
    assert state["state"] == "failed"
    assert state["rate_limited"] is True
    assert state["reset_text"] == "15:00"
    # 閉じたジョブは idle 扱い
    assert client.get(f"/api/summaries/generation?dismissed={job_id}").json()["state"] == "idle"


@pytest.mark.parametrize("interval", ["daily", "weekly", "monthly"])
def test_config_returns_next_run(client, monkeypatch, tmp_path, interval):
    cfg = tmp_path / "interval.yaml"
    cfg.write_text(f"summary: {{interval: {interval}}}\n", encoding="utf-8")
    monkeypatch.setattr("deep_tracker.api.summaries.get_settings", lambda: load_settings(cfg))
    body = client.get("/api/summaries/config").json()
    assert body["interval"] == interval
    next_run = datetime.fromisoformat(body["next_run_at"])
    assert next_run.tzinfo is not None
    assert next_run > datetime.now(UTC)
    assert (next_run.hour, next_run.minute) == (0, 0)
    assert next_run - datetime.now(UTC) <= timedelta(days=32)
    if interval == "weekly":
        assert next_run.weekday() == 0
    if interval == "monthly":
        assert next_run.day == 1
