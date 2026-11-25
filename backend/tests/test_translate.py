import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select

from deep_tracker.ai import AIProvider, AIResult, RateLimitError
from deep_tracker.api.deps import get_http_client, get_session
from deep_tracker.config import load_settings
from deep_tracker.config.models import TranslationSettings
from deep_tracker.db import AiJob, Article, Feed, create_db_engine, make_session_factory, upgrade_db
from deep_tracker.feeds import fetch_and_store, register_feed
from deep_tracker.jobs.ai_jobs import AIJobRunner, enqueue_job
from deep_tracker.jobs.fetch import run_fetch
from deep_tracker.main import app
from deep_tracker.translate import (
    JOB_KIND,
    InvalidTranslationOutput,
    detect_language,
    enqueue_new_articles,
    make_translate_handler,
    parse_translation_output,
    truncate_content,
)

FIXTURES = Path(__file__).parent / "fixtures"
AWS_URL = "https://aws.amazon.com/jp/about-aws/whats-new/recent/feed/"
AWS_XML = (FIXTURES / "aws_whats_new.xml").read_bytes()
BASE = datetime(2026, 10, 1, tzinfo=UTC)


def english_rss(n: int) -> bytes:
    """日本語以外の記事の固定サンプル。i が大きいほど新しい。"""
    items = "".join(
        f"<item><guid>en-{i}</guid><title>New feature {i} is now available</title>"
        f"<link>https://example.com/{i}</link>"
        f"<description>&lt;p&gt;You can now use feature {i} in all regions.&lt;/p&gt;</description>"
        f"<pubDate>Mon, {5 + i:02d} Oct 2026 01:00:00 GMT</pubDate></item>"
        for i in range(n)
    )
    head = '<?xml version="1.0"?><rss version="2.0"><channel><title>EN</title>'
    return f"{head}{items}</channel></rss>".encode()


def mock_client(content: bytes) -> httpx.Client:
    return httpx.Client(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, content=content))
    )


class MockProvider(AIProvider):
    def __init__(self, text=None, error=None):
        self.text = text or json.dumps({"title": "新機能が利用可能に", "content": "<p>本文</p>"})
        self.error = error
        self.calls = []

    def generate(self, prompt, *, system_prompt=None, input_text=None):
        self.calls.append((prompt, input_text))
        if self.error:
            raise self.error
        return AIResult(text=self.text)


@pytest.fixture
def settings(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"db: {{path: {tmp_path / 'test.db'}}}\n", encoding="utf-8")
    s = load_settings(cfg)
    upgrade_db(s)
    return s


@pytest.fixture
def factory(settings):
    engine = create_db_engine(settings.db.path)
    yield make_session_factory(engine)
    engine.dispose()


def add_article(session, **kw):
    feed = session.scalar(select(Feed).limit(1))
    if feed is None:
        feed = Feed(name="EN", url="https://example.com/rss")
        session.add(feed)
        session.flush()
    defaults = dict(
        guid=f"g{kw.get('title', '')}{datetime.now().timestamp()}",
        title="New feature",
        content="<p>Body text</p>",
        published_at=BASE,
        language="other",
    )
    article = Article(feed=feed, **{**defaults, **kw})
    session.add(article)
    session.commit()
    return article


def translate_jobs(session):
    return list(session.scalars(select(AiJob).where(AiJob.kind == JOB_KIND).order_by(AiJob.id)))


# --- 言語判定 ---


@pytest.mark.parametrize(
    ("title", "content", "expected"),
    [
        (
            "Amazon EC2 で新しいインスタンスが利用可能に",
            "<p>本日より提供を開始しました。</p>",
            "ja",
        ),
        ("New feature is now available", "<p>You can now use it.</p>", "other"),
        ("亚马逊云科技宣布推出新功能", "<p>今天我们宣布在所有区域推出新的实例类型。</p>", "other"),
        ("새로운 기능 출시", "<p>오늘부터 사용할 수 있습니다.</p>", "other"),
        # 製品名が多くても仮名があれば日本語
        (
            "AWS Lambda で Amazon S3 Express One Zone のイベント通知をサポート",
            "<p>AWS Lambda functions can now ... を利用できます。</p>",
            "ja",
        ),
        # タグ内の属性は判定に使わない
        ("Release notes", '<a href="https://example.com/ja/ほげ">link</a>', "other"),
        ("", None, "ja"),
        ("2026", "<p>123</p>", "ja"),
    ],
)
def test_detect_language(title, content, expected):
    assert detect_language(title, content) == expected


def test_aws_feed_articles_are_japanese():
    from deep_tracker.feeds import parse_feed

    entries = parse_feed(AWS_XML)
    assert entries
    assert {detect_language(e.title, e.content) for e in entries} == {"ja"}


# --- 出力検証・切り詰め ---


def test_parse_output_accepts_code_fence():
    text = '```json\n{"title": " 題 ", "content": "<p>本文</p>"}\n```'
    assert parse_translation_output(text, has_content=True) == {
        "title": "題",
        "content": "<p>本文</p>",
    }


@pytest.mark.parametrize(
    ("text", "has_content"),
    [
        ("not json", True),
        ('{"title": "題"}', True),
        ('{"title": " ", "content": "x"}', True),
        ('{"title": "題", "content": ""}', True),
    ],
)
def test_parse_output_rejects_invalid(text, has_content):
    with pytest.raises(InvalidTranslationOutput):
        parse_translation_output(text, has_content=has_content)


def test_parse_output_allows_empty_content_without_source():
    assert (
        parse_translation_output('{"title": "題", "content": ""}', has_content=False)["content"]
        == ""
    )


def test_truncate_content():
    assert truncate_content("abc", limit=10) == ("abc", False)
    assert truncate_content("a" * 20, limit=10) == ("a" * 10, True)
    # 閉じていないタグの途中では切らない
    assert truncate_content("<p>hello</p><a href='x'>", limit=20) == ("<p>hello</p>", True)


# --- 翻訳ハンドラ ---


def run_job(factory, provider, article_id):
    with factory() as s:
        job = enqueue_job(s, JOB_KIND, {"article_id": article_id})
        job_id = job.id
    runner = AIJobRunner(factory, provider, {JOB_KIND: make_translate_handler(factory)})
    assert runner.run_next()
    with factory() as s:
        return s.get(AiJob, job_id)


def test_handler_saves_translation_and_keeps_original(factory):
    with factory() as s:
        a = add_article(s, title="New feature", content="<p>Body text</p>")
        article_id = a.id
    provider = MockProvider()
    job = run_job(factory, provider, article_id)
    assert job.status == "succeeded"
    assert job.result == {"article_id": article_id, "truncated": False}
    assert json.loads(provider.calls[0][1]) == {
        "title": "New feature",
        "content": "<p>Body text</p>",
    }
    with factory() as s:
        a = s.get(Article, article_id)
        assert (a.title, a.content) == ("New feature", "<p>Body text</p>")
        assert (a.title_ja, a.content_ja) == ("新機能が利用可能に", "<p>本文</p>")
        assert a.translated_at is not None
        assert a.translation_truncated is False


def test_handler_truncates_long_content(factory, monkeypatch):
    monkeypatch.setattr("deep_tracker.translate.service.MAX_CONTENT_CHARS", 10)
    with factory() as s:
        article_id = add_article(s, content="x" * 50).id
    provider = MockProvider()
    job = run_job(factory, provider, article_id)
    assert job.result["truncated"] is True
    assert json.loads(provider.calls[0][1])["content"] == "x" * 10
    with factory() as s:
        assert s.get(Article, article_id).translation_truncated is True


@pytest.mark.parametrize(
    ("provider", "error_prefix", "rate_limited"),
    [
        (MockProvider(text="not json"), "翻訳の出力が不正です", False),
        (
            MockProvider(error=RateLimitError("limit", reset_text="5pm")),
            "利用制限に達しました",
            True,
        ),
    ],
)
def test_handler_failure_keeps_article_untranslated(factory, provider, error_prefix, rate_limited):
    from deep_tracker.jobs.ai_jobs import is_rate_limited

    with factory() as s:
        article_id = add_article(s).id
    job = run_job(factory, provider, article_id)
    assert job.status == "failed"
    assert job.error.startswith(error_prefix)
    assert is_rate_limited(job) is rate_limited
    with factory() as s:
        a = s.get(Article, article_id)
        assert a.title_ja is None and a.content_ja is None and a.translated_at is None


def test_handler_fails_for_deleted_article(factory):
    job = run_job(factory, MockProvider(), 9999)
    assert job.status == "failed"
    assert "記事が見つかりません" in job.error


# --- 取得時の投入 ---


def test_fetch_enqueues_non_japanese_articles_up_to_limit(factory):
    with factory() as s:
        feed = Feed(name="EN", url="https://example.com/rss")
        s.add(feed)
        s.commit()
        added = fetch_and_store(
            s,
            feed,
            client=mock_client(english_rss(5)),
            translation=TranslationSettings(max_per_fetch=3),
        )
        assert added == 5
        assert {a.language for a in s.scalars(select(Article))} == {"other"}
        jobs = translate_jobs(s)
        # 新しい順に上限件数まで
        guids = [s.get(Article, j.input["article_id"]).guid for j in jobs]
        assert guids == ["en-4", "en-3", "en-2"]


def test_fetch_does_not_enqueue_japanese_articles(factory):
    with factory() as s:
        feed = Feed(name="AWS", url=AWS_URL)
        s.add(feed)
        s.commit()
        added = fetch_and_store(
            s, feed, client=mock_client(AWS_XML), translation=TranslationSettings()
        )
        assert added > 0
        assert {a.language for a in s.scalars(select(Article))} == {"ja"}
        assert translate_jobs(s) == []


def test_fetch_does_not_enqueue_when_disabled(factory):
    with factory() as s:
        feed = Feed(name="EN", url="https://example.com/rss")
        s.add(feed)
        s.commit()
        fetch_and_store(
            s,
            feed,
            client=mock_client(english_rss(2)),
            translation=TranslationSettings(enabled=False),
        )
        assert translate_jobs(s) == []
        # 言語判定は保存する（手動翻訳のボタン表示に使う）
        assert {a.language for a in s.scalars(select(Article))} == {"other"}


def test_refetch_does_not_enqueue_again(factory):
    with factory() as s:
        feed = Feed(name="EN", url="https://example.com/rss")
        s.add(feed)
        s.commit()
        for _ in range(2):
            fetch_and_store(
                s, feed, client=mock_client(english_rss(2)), translation=TranslationSettings()
            )
        assert len(translate_jobs(s)) == 2


def test_register_feed_enqueues(factory):
    with factory() as s:
        register_feed(
            s,
            "https://example.com/rss",
            client=mock_client(english_rss(2)),
            translation=TranslationSettings(),
        )
        assert len(translate_jobs(s)) == 2


def test_run_fetch_uses_translation_settings(factory, settings):
    settings.translation.max_per_fetch = 1
    with factory() as s:
        s.add(Feed(name="EN", url="https://example.com/rss"))
        s.commit()
        run_fetch(s, settings, client=mock_client(english_rss(3)))
        assert len(translate_jobs(s)) == 1


def test_enqueue_new_articles_skips_translated(factory):
    with factory() as s:
        done = add_article(s, title_ja="訳", translated_at=BASE)
        todo = add_article(s, published_at=BASE + timedelta(days=1))
        ja = add_article(s, language="ja")
        assert enqueue_new_articles(s, [done, todo, ja], TranslationSettings()) == 1
        assert [j.input["article_id"] for j in translate_jobs(s)] == [todo.id]


# --- API ---


@pytest.fixture
def client(factory, settings, monkeypatch):
    def _session():
        with factory() as s:
            yield s

    def _http():
        with mock_client(english_rss(3)) as c:
            yield c

    monkeypatch.setattr("deep_tracker.api.feeds.get_settings", lambda: settings)
    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_http_client] = _http
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_api_add_feed_enqueues(client, factory):
    assert client.post("/api/feeds", json={"url": "https://example.com/rss"}).status_code == 201
    with factory() as s:
        assert len(translate_jobs(s)) == 3


def test_api_change_url_and_fetch_now_enqueue(client, factory):
    with factory() as s:
        feed = Feed(name="EN", url="https://example.com/old.rss")
        s.add(feed)
        s.commit()
        feed_id = feed.id
    res = client.patch(f"/api/feeds/{feed_id}", json={"url": "https://example.com/rss"})
    assert res.status_code == 200
    with factory() as s:
        assert len(translate_jobs(s)) == 3
        # 既存記事は再投入されない。新着記事のみ投入される
        s.query(Article).filter(Article.guid == "en-2").delete()
        s.commit()
    assert client.post(f"/api/feeds/{feed_id}/fetch").json()["added"] == 1
    with factory() as s:
        assert len(translate_jobs(s)) == 4


def test_api_wakes_ai_runner(client, factory):
    class Runner:
        notified = 0

        def notify(self):
            Runner.notified += 1

    app.state.ai_runner = Runner()
    try:
        with factory() as s:
            article_id = add_article(s).id
        assert client.post(f"/api/articles/{article_id}/translate").status_code == 202
        res = client.post("/api/feeds", json={"url": "https://example.com/other.rss"})
        assert res.status_code == 201
        assert Runner.notified == 2
    finally:
        del app.state.ai_runner


def test_manual_translation_keeps_detected_language(factory):
    with factory() as s:
        article_id = add_article(s, title="日本語の記事です", language="ja").id
    run_job(factory, MockProvider(), article_id)
    with factory() as s:
        a = s.get(Article, article_id)
        assert a.language == "ja" and a.translated_at is not None


def test_api_manual_translate(client, factory):
    with factory() as s:
        article_id = add_article(s).id
    res = client.post(f"/api/articles/{article_id}/translate")
    assert res.status_code == 202
    job_id = res.json()["job_id"]
    # 翻訳待ちの間は同じジョブを返す
    assert client.post(f"/api/articles/{article_id}/translate").json()["job_id"] == job_id
    assert client.get(f"/api/ai-jobs/{job_id}").json()["kind"] == JOB_KIND
    detail = client.get(f"/api/articles/{article_id}").json()
    assert detail["translation_job"] == {
        "id": job_id,
        "status": "pending",
        "error": None,
        "rate_limited": False,
    }


def test_api_manual_translate_rejects_translated_and_missing(client, factory):
    with factory() as s:
        article_id = add_article(s, title_ja="訳", translated_at=BASE).id
    assert client.post(f"/api/articles/{article_id}/translate").status_code == 409
    assert client.post("/api/articles/9999/translate").status_code == 404


def test_api_manual_translate_after_failure_creates_new_job(client, factory):
    with factory() as s:
        article_id = add_article(s).id
        failed = enqueue_job(s, JOB_KIND, {"article_id": article_id})
        failed.status = "failed"
        failed.error = "利用制限に達しました: limit"
        s.commit()
        failed_id = failed.id
    detail = client.get(f"/api/articles/{article_id}").json()
    assert detail["translation_job"]["rate_limited"] is True
    res = client.post(f"/api/articles/{article_id}/translate")
    assert res.json()["job_id"] != failed_id


def test_api_returns_translation_fields(client, factory):
    with factory() as s:
        a = add_article(
            s,
            title="New feature",
            content="<p>Body text</p>",
            title_ja="新機能",
            content_ja="<p>本文です</p>",
            translated_at=BASE,
            translation_truncated=True,
        )
        newer = add_article(
            s, title="Newer", title_ja="新しい記事", published_at=BASE + timedelta(days=1)
        )
        article_id, newer_id = a.id, newer.id
    detail = client.get(f"/api/articles/{article_id}").json()
    assert detail["title"] == "New feature"
    assert detail["content"] == "<p>Body text</p>"
    assert detail["title_ja"] == "新機能"
    assert detail["content_ja"] == "<p>本文です</p>"
    assert detail["language"] == "other"
    assert detail["translation_truncated"] is True
    assert detail["translated_at"] is not None
    assert detail["translation_job"] is None
    assert detail["newer"] == {"id": newer_id, "title": "新しい記事"}

    items = {i["id"]: i for i in client.get("/api/articles").json()["items"]}
    assert items[article_id]["title_ja"] == "新機能"
    assert items[article_id]["excerpt"] == "<p>本文です</p>"
    assert items[newer_id]["excerpt"] == "<p>Body text</p>"


def test_api_detects_language_of_legacy_articles(client, factory):
    with factory() as s:
        en = add_article(s, language=None).id
        ja = add_article(s, title="日本語の記事です", content="本文です", language=None).id
    assert client.get(f"/api/articles/{en}").json()["language"] == "other"
    assert client.get(f"/api/articles/{ja}").json()["language"] == "ja"
    langs = {i["id"]: i["language"] for i in client.get("/api/articles").json()["items"]}
    assert langs == {en: "other", ja: "ja"}


def test_api_search_hits_translation(client, factory):
    with factory() as s:
        a = add_article(s, title="New feature", title_ja="新機能のお知らせ", translated_at=BASE)
        add_article(s, title="Other")
        b = add_article(s, title="Another", content_ja="<p>料金の改定</p>", translated_at=BASE)
        ids = (a.id, b.id)
    found = client.get("/api/articles", params={"q": "お知らせ"}).json()["items"]
    assert [i["id"] for i in found] == [ids[0]]
    found = client.get("/api/articles", params={"q": "料金"}).json()["items"]
    assert [i["id"] for i in found] == [ids[1]]


# --- マイグレーション ---


def test_translation_migration_upgrade_and_downgrade(tmp_path):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text

    from deep_tracker.db.session import BACKEND_ROOT

    db_path = tmp_path / "mig.db"
    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    cfg.attributes["db_path"] = db_path
    command.upgrade(cfg, "0003")
    eng = create_db_engine(db_path)
    try:
        with eng.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO feeds (id, name, url, enabled, created_at)"
                    " VALUES (1, 'f', 'https://e.example/rss', 1, '2026-01-01')"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO articles (feed_id, guid, title, fetched_at, is_read, is_marked)"
                    " VALUES (1, 'g', 't', '2026-01-01', 0, 0)"
                )
            )
        command.upgrade(cfg, "0004")
        with eng.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT language, title_ja, content_ja, translated_at, translation_truncated"
                    " FROM articles"
                )
            ).one()
            assert tuple(row) == (None, None, None, None, 0)
        command.downgrade(cfg, "0003")
        cols = {c["name"] for c in inspect(eng).get_columns("articles")}
        assert not {"language", "title_ja", "content_ja", "translated_at"} & cols
        with eng.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM articles")).scalar() == 1
    finally:
        eng.dispose()
