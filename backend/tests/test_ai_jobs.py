import threading
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from deep_tracker.ai import AIError, AIProvider, AIResult, RateLimitError
from deep_tracker.api.deps import get_session
from deep_tracker.config import load_settings
from deep_tracker.db import AiJob, create_db_engine, make_session_factory, upgrade_db
from deep_tracker.db.models import utcnow
from deep_tracker.jobs.ai_jobs import (
    INTERRUPTED_ERROR,
    AIJobRunner,
    enqueue_job,
    recover_interrupted_jobs,
)
from deep_tracker.main import app


class FakeProvider(AIProvider):
    def generate(self, prompt, *, system_prompt=None, input_text=None):
        return AIResult(text=f"echo:{prompt}")


@pytest.fixture
def factory(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"db: {{path: {tmp_path / 'test.db'}}}\n", encoding="utf-8")
    settings = load_settings(cfg)
    upgrade_db(settings)
    engine = create_db_engine(settings.db.path)
    yield make_session_factory(engine)
    engine.dispose()


def make_runner(factory, handlers, **kw):
    return AIJobRunner(factory, FakeProvider(), handlers, **kw)


def get_job(factory, job_id):
    with factory() as s:
        return s.get(AiJob, job_id)


def echo(input_data, provider):
    return {"text": provider.generate(input_data["prompt"]).text}


def test_success_saves_transitions(factory):
    with factory() as s:
        job = enqueue_job(s, "echo", {"prompt": "hi"})
        assert job.status == "pending"
        job_id = job.id

    assert make_runner(factory, {"echo": echo}).run_next() is True

    job = get_job(factory, job_id)
    assert job.status == "succeeded"
    assert job.result == {"text": "echo:hi"}
    assert job.error is None
    assert job.started_at is not None
    assert job.finished_at is not None


def test_no_pending_returns_false(factory):
    assert make_runner(factory, {}).run_next() is False


def test_rate_limit_error_saved_without_retry(factory):
    calls = []

    def limited(_input, _provider):
        calls.append(1)
        raise RateLimitError("limit", reset_text="3pm")

    with factory() as s:
        job_id = enqueue_job(s, "x").id
    runner = make_runner(factory, {"x": limited})
    runner.run_next()
    assert runner.run_next() is False  # 自動リトライしない

    job = get_job(factory, job_id)
    assert len(calls) == 1
    assert job.status == "failed"
    assert job.error.startswith("利用制限に達しました")
    assert "3pm" in job.error
    assert job.finished_at is not None


def test_other_errors_saved_as_failure(factory):
    def ai_fail(_i, _p):
        raise AIError("boom")

    def bug(_i, _p):
        raise ValueError("bad")

    with factory() as s:
        a = enqueue_job(s, "ai").id
        b = enqueue_job(s, "bug").id
        c = enqueue_job(s, "unknown").id
    runner = make_runner(factory, {"ai": ai_fail, "bug": bug})
    while runner.run_next():
        pass

    assert get_job(factory, a).error == "boom"
    assert get_job(factory, b).error == "ValueError: bad"
    assert get_job(factory, c).status == "failed"
    assert "未対応" in get_job(factory, c).error


def test_jobs_run_in_creation_order(factory):
    order = []

    def record(input_data, _p):
        order.append(input_data)

    with factory() as s:
        for n in range(3):
            enqueue_job(s, "r", n)
    runner = make_runner(factory, {"r": record})
    while runner.run_next():
        pass
    assert order == [0, 1, 2]


def test_recover_interrupted_jobs(factory):
    with factory() as s:
        running = enqueue_job(s, "x").id
        pending = enqueue_job(s, "x").id
        done = enqueue_job(s, "x").id
        s.get(AiJob, running).status = "running"
        s.get(AiJob, running).started_at = utcnow()
        s.get(AiJob, done).status = "succeeded"
        s.commit()
        assert recover_interrupted_jobs(s) == 1

    job = get_job(factory, running)
    assert job.status == "failed"
    assert job.error == INTERRUPTED_ERROR
    assert job.finished_at is not None
    assert get_job(factory, pending).status == "pending"
    assert get_job(factory, done).status == "succeeded"
    with factory() as s:
        assert not s.scalars(select(AiJob).where(AiJob.status == "running")).all()


def _run_workers(factory, concurrency, total):
    state = {"now": 0, "peak": 0}
    lock = threading.Lock()

    def slow(_i, _p):
        with lock:
            state["now"] += 1
            state["peak"] = max(state["peak"], state["now"])
        time.sleep(0.05)
        with lock:
            state["now"] -= 1

    with factory() as s:
        for _ in range(total):
            enqueue_job(s, "slow")
    runner = make_runner(factory, {"slow": slow}, concurrency=concurrency, poll_seconds=0.02)
    runner.start()
    try:
        deadline = time.time() + 10
        while time.time() < deadline:
            with factory() as s:
                if len(s.scalars(select(AiJob).where(AiJob.status == "succeeded")).all()) == total:
                    break
            time.sleep(0.02)
    finally:
        runner.stop()
    return state["peak"]


def test_default_runs_sequentially(factory):
    assert _run_workers(factory, concurrency=1, total=4) == 1


def test_concurrency_is_configurable(factory):
    assert _run_workers(factory, concurrency=2, total=6) == 2


@pytest.fixture
def client(factory):
    def _session():
        with factory() as s:
            yield s

    app.dependency_overrides[get_session] = _session
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_api_get_and_list(client, factory):
    with factory() as s:
        ok = enqueue_job(s, "a", {"k": 1}).id
        limited = enqueue_job(s, "b").id
    runner = make_runner(
        factory,
        {
            "a": lambda i, p: {"done": True},
            "b": lambda i, p: (_ for _ in ()).throw(RateLimitError("l")),
        },
    )
    while runner.run_next():
        pass

    body = client.get(f"/api/ai-jobs/{ok}").json()
    assert body["status"] == "succeeded"
    assert body["result"] == {"done": True}
    assert body["rate_limited"] is False

    body = client.get(f"/api/ai-jobs/{limited}").json()
    assert body["status"] == "failed"
    assert body["rate_limited"] is True

    assert [j["id"] for j in client.get("/api/ai-jobs").json()] == [limited, ok]
    failed = client.get("/api/ai-jobs", params={"status": "failed"}).json()
    assert [j["id"] for j in failed] == [limited]
    assert client.get("/api/ai-jobs", params={"status": "bogus"}).status_code == 422
    assert client.get("/api/ai-jobs/9999").status_code == 404


def test_max_concurrent_jobs_setting(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("ai: {max_concurrent_jobs: 3}\n", encoding="utf-8")
    assert load_settings(cfg).ai.max_concurrent_jobs == 3
    empty = tmp_path / "empty.yaml"
    empty.write_text("instance: default\n", encoding="utf-8")
    assert load_settings(empty).ai.max_concurrent_jobs == 1
