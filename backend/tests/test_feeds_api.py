from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from deep_tracker.api.deps import get_http_client, get_session
from deep_tracker.config import load_settings
from deep_tracker.db import Article, Feed, create_db_engine, make_session_factory, upgrade_db
from deep_tracker.main import app

AWS_URL = "https://aws.amazon.com/jp/about-aws/whats-new/recent/feed/"
AWS_XML = (Path(__file__).parent / "fixtures" / "aws_whats_new.xml").read_bytes()


@pytest.fixture
def factory(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"db: {{path: {tmp_path / 'test.db'}}}\n", encoding="utf-8")
    settings = load_settings(cfg)
    upgrade_db(settings)
    engine = create_db_engine(settings.db.path)
    yield make_session_factory(engine)
    engine.dispose()


@pytest.fixture
def handler():
    """フィード取得先の応答。テストごとに handler.fn を差し替える。"""

    class H:
        fn = staticmethod(lambda req: httpx.Response(200, content=AWS_XML))

    return H


@pytest.fixture
def client(factory, handler):
    def _session():
        with factory() as s:
            yield s

    def _http():
        with httpx.Client(
            transport=httpx.MockTransport(lambda req: handler.fn(req)), follow_redirects=True
        ) as c:
            yield c

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_http_client] = _http
    yield TestClient(app)
    app.dependency_overrides.clear()


def add(client, url=AWS_URL, **kw):
    return client.post("/api/feeds", json={"url": url, **kw})


def test_add_aws_feed(client, factory):
    res = add(client)
    assert res.status_code == 201
    body = res.json()
    assert body["url"] == AWS_URL
    assert body["name"] != AWS_URL  # フィードのタイトルが既定名称になる
    assert body["enabled"] is True
    assert body["article_count"] >= 10
    assert body["unread_count"] == body["article_count"]
    assert body["last_fetch_ok"] is True
    assert body["fetch_interval_minutes"] is None
    assert body["effective_fetch_interval_minutes"] == 60
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(Article)) == body["article_count"]


def test_add_with_custom_name(client):
    assert add(client, name="  AWS  ").json()["name"] == "AWS"


@pytest.mark.parametrize("url", ["", "not a url", "ftp://example.com/feed", "https://", "/feed"])
def test_add_invalid_url(client, url):
    res = add(client, url)
    assert res.status_code == 422
    assert res.json()["detail"]["code"] == "invalid_url"


def test_add_duplicate(client):
    assert add(client).status_code == 201
    res = add(client)
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "duplicate_url"


def test_add_not_a_feed(client, handler, factory):
    handler.fn = lambda req: httpx.Response(200, content=b"<html><body>hello</body></html>")
    res = add(client, "https://example.com/")
    assert res.status_code == 422
    assert res.json()["detail"]["code"] == "not_a_feed"
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(Feed)) == 0


def test_add_unreachable(client, handler):
    handler.fn = lambda req: httpx.Response(404)
    res = add(client, "https://example.com/missing")
    assert res.status_code == 422
    detail = res.json()["detail"]
    assert detail["code"] == "not_a_feed"
    assert "404" in detail["message"]


def test_list_with_counts(client, factory):
    feed_id = add(client).json()["id"]
    with factory() as s:
        article = s.scalars(select(Article).where(Article.feed_id == feed_id)).first()
        article.is_read = True
        s.commit()
    (item,) = client.get("/api/feeds").json()
    assert item["id"] == feed_id
    assert item["unread_count"] == item["article_count"] - 1


def test_list_includes_feed_without_articles(client, factory):
    with factory() as s:
        s.add(Feed(name="empty", url="https://example.com/e"))
        s.commit()
    (item,) = client.get("/api/feeds").json()
    assert (item["article_count"], item["unread_count"]) == (0, 0)
    assert item["last_fetch_ok"] is None


def test_update(client):
    feed_id = add(client).json()["id"]
    res = client.patch(
        f"/api/feeds/{feed_id}",
        json={"name": "新しい名前", "fetch_interval_minutes": 15, "enabled": False},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["name"] == "新しい名前"
    assert body["fetch_interval_minutes"] == 15
    assert body["effective_fetch_interval_minutes"] == 15
    assert body["enabled"] is False

    # null で既定値に戻る。送っていない項目は変わらない
    body = client.patch(f"/api/feeds/{feed_id}", json={"fetch_interval_minutes": None}).json()
    assert body["fetch_interval_minutes"] is None
    assert body["name"] == "新しい名前"
    assert body["enabled"] is False


@pytest.mark.parametrize(
    "body",
    [
        {"name": ""},
        {"name": "   "},
        {"name": None},
        {"fetch_interval_minutes": 0},
        {"enabled": "x"},
    ],
)
def test_update_rejects_invalid(client, body):
    feed_id = add(client).json()["id"]
    assert client.patch(f"/api/feeds/{feed_id}", json=body).status_code == 422


def test_delete_removes_articles(client, factory):
    feed_id = add(client).json()["id"]
    assert client.delete(f"/api/feeds/{feed_id}").status_code == 204
    assert client.get("/api/feeds").json() == []
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(Article)) == 0


def test_fetch_now(client, handler):
    feed_id = add(client).json()["id"]
    res = client.post(f"/api/feeds/{feed_id}/fetch")
    assert res.status_code == 200
    assert res.json()["added"] == 0  # 既に取得済みの記事は増えない

    handler.fn = lambda req: httpx.Response(500)
    body = client.post(f"/api/feeds/{feed_id}/fetch").json()
    assert body["feed"]["last_fetch_ok"] is False
    assert "500" in body["feed"]["last_fetch_error"]


def test_fetch_now_works_for_disabled_feed(client):
    feed_id = add(client).json()["id"]
    client.patch(f"/api/feeds/{feed_id}", json={"enabled": False})
    assert client.post(f"/api/feeds/{feed_id}/fetch").status_code == 200


@pytest.mark.parametrize(
    ("method", "path"),
    [("patch", "/api/feeds/999"), ("delete", "/api/feeds/999"), ("post", "/api/feeds/999/fetch")],
)
def test_not_found(client, method, path):
    res = getattr(client, method)(path, **({"json": {}} if method == "patch" else {}))
    assert res.status_code == 404
    assert res.json()["detail"]["code"] == "feed_not_found"


def test_openapi_lists_feed_endpoints(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/feeds" in paths
    assert "/api/feeds/{feed_id}/fetch" in paths
