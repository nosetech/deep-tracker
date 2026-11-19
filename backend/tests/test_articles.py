from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from deep_tracker.api.deps import get_session
from deep_tracker.config import load_settings
from deep_tracker.db import Article, Feed, create_db_engine, make_session_factory, upgrade_db
from deep_tracker.main import app

BASE = datetime(2026, 10, 1, tzinfo=UTC)


@pytest.fixture
def session(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"db: {{path: {tmp_path / 'test.db'}}}\n", encoding="utf-8")
    settings = load_settings(cfg)
    upgrade_db(settings)
    engine = create_db_engine(settings.db.path)
    with make_session_factory(engine)() as s:
        yield s
    engine.dispose()


@pytest.fixture
def client(session):
    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def data(session):
    """feed A: a0..a4（a0が最古）、feed B: b0..b1。a4 は公開日時なし（取得日時=最新扱い）。"""
    fa, fb = (
        Feed(name="A", url="https://a.example/rss"),
        Feed(name="B", url="https://b.example/rss"),
    )
    session.add_all([fa, fb])
    session.flush()
    arts = {}
    for i in range(4):
        arts[f"a{i}"] = Article(
            feed_id=fa.id,
            guid=f"a{i}",
            title=f"Alpha {i}",
            content="100% sure <b>x</b>" if i == 1 else f"body {i}",
            published_at=BASE + timedelta(days=i),
        )
    arts["a4"] = Article(
        feed_id=fa.id,
        guid="a4",
        title="No date",
        published_at=None,
        fetched_at=BASE + timedelta(days=10),
    )
    for i in range(2):
        arts[f"b{i}"] = Article(
            feed_id=fb.id,
            guid=f"b{i}",
            title=f"Beta {i}",
            published_at=BASE + timedelta(days=i, hours=1),
        )
    session.add_all(arts.values())
    session.commit()
    return {"fa": fa.id, "fb": fb.id, **{k: v.id for k, v in arts.items()}}


def test_list_order_and_paging(client, data):
    res = client.get("/api/articles", params={"per_page": 3}).json()
    assert res["total"] == 7
    assert [i["title"] for i in res["items"]] == ["No date", "Alpha 3", "Alpha 2"]
    assert res["items"][0]["feed_name"] == "A"
    p2 = client.get("/api/articles", params={"per_page": 3, "page": 3}).json()
    assert [i["title"] for i in p2["items"]] == ["Alpha 0"]


def test_list_filters(client, data):
    def titles(**params):
        return [i["title"] for i in client.get("/api/articles", params=params).json()["items"]]

    assert titles(feed_id=data["fb"]) == ["Beta 1", "Beta 0"]
    assert titles(since="2026-10-03T00:00:00Z", feed_id=data["fa"]) == [
        "No date",
        "Alpha 3",
        "Alpha 2",
    ]
    assert titles(until="2026-10-02T00:00:00", feed_id=data["fa"]) == ["Alpha 0"]
    assert titles(q="beta") == ["Beta 1", "Beta 0"]
    assert titles(q="sure") == ["Alpha 1"]  # 本文も検索対象
    assert titles(q="%") == ["Alpha 1"]  # ワイルドカードはリテラル
    assert titles(q="alpha sure") == ["Alpha 1"]  # AND
    client.patch(f"/api/articles/{data['b1']}/read", json={"is_read": True})
    assert titles(unread_only=True, feed_id=data["fb"]) == ["Beta 0"]


def test_unread_counts(client, data):
    client.patch(f"/api/articles/{data['a0']}/read", json={"is_read": True})
    res = client.get("/api/articles/unread-counts").json()
    assert res["total"] == 6
    assert {f["feed_id"]: f["unread"] for f in res["feeds"]} == {data["fa"]: 4, data["fb"]: 2}


def test_detail_neighbors(client, data):
    mid = client.get(f"/api/articles/{data['a2']}").json()
    assert mid["feed_name"] == "A"
    assert mid["newer"]["title"] == "Alpha 3"  # 全体の並びでの隣
    assert mid["older"]["title"] == "Beta 1"
    scoped = client.get(f"/api/articles/{data['a2']}", params={"feed_id": data["fa"]}).json()
    assert scoped["newer"]["title"] == "Alpha 3"
    assert scoped["older"]["title"] == "Alpha 1"
    newest = client.get(f"/api/articles/{data['a4']}").json()
    assert newest["newer"] is None
    oldest = client.get(f"/api/articles/{data['a0']}", params={"feed_id": data["fa"]}).json()
    assert oldest["older"] is None
    assert client.get("/api/articles/99999").status_code == 404


def test_detail_neighbors_unread_only(client, data):
    # 現在の記事(a2)が既読でも、その位置から見た未読の前後を返す。既読の記事は飛ばす
    for key in ("a2", "a3"):
        client.patch(f"/api/articles/{data[key]}/read", json={"is_read": True})
    res = client.get(f"/api/articles/{data['a2']}", params={"unread_only": True}).json()
    assert res["newer"]["id"] == data["a4"]  # a3(既読)を飛ばす
    assert res["older"]["title"] == "Beta 1"
    # 前後の未読がなくなれば None
    client.patch(f"/api/articles/{data['a4']}/read", json={"is_read": True})
    res = client.get(f"/api/articles/{data['a2']}", params={"unread_only": True}).json()
    assert res["newer"] is None
    # unread_only なしなら従来どおり既読も含む
    res = client.get(f"/api/articles/{data['a2']}").json()
    assert res["newer"]["title"] == "Alpha 3"


def test_set_read_and_unread(client, data):
    url = f"/api/articles/{data['a0']}/read"
    res = client.patch(url, json={"is_read": True}).json()
    assert res["is_read"] and res["read_at"]
    res = client.patch(url, json={"is_read": False}).json()
    assert not res["is_read"] and res["read_at"] is None
    assert client.patch("/api/articles/99999/read", json={"is_read": True}).status_code == 404


def test_bulk_read_and_undo(client, data):
    client.patch(f"/api/articles/{data['b0']}/read", json={"is_read": True})
    res = client.post("/api/articles/mark-read", params={"feed_id": data["fb"]}).json()
    # 既に既読の b0 は変更対象に含まれない
    assert res == {"count": 1, "article_ids": [data["b1"]]}
    assert client.get("/api/articles", params={"unread_only": True}).json()["total"] == 5

    undo = client.post("/api/articles/mark-unread", json={"article_ids": res["article_ids"]}).json()
    assert undo["count"] == 1
    detail = client.get(f"/api/articles/{data['b1']}").json()
    assert not detail["is_read"] and detail["read_at"] is None
    # b0 は元から既読のままなので、Undoで未読に戻らない
    assert client.get(f"/api/articles/{data['b0']}").json()["is_read"]


def test_bulk_read_with_search_filter(client, data):
    res = client.post("/api/articles/mark-read", params={"q": "alpha"}).json()
    assert res["count"] == 4
    assert client.get("/api/articles/unread-counts").json()["total"] == 3


def test_feed_mark_read(client, data):
    res = client.post(f"/api/feeds/{data['fa']}/mark-read").json()
    assert res["count"] == 5
    assert client.get("/api/articles/unread-counts").json()["total"] == 2
    assert client.post("/api/feeds/99999/mark-read").status_code == 404
    again = client.post(f"/api/feeds/{data['fa']}/mark-read").json()
    assert again == {"count": 0, "article_ids": []}


def test_set_mark_and_unmark(client, data):
    url = f"/api/articles/{data['a0']}/mark"
    res = client.patch(url, json={"is_marked": True}).json()
    assert res["is_marked"] and res["marked_at"]
    first = res["marked_at"]
    # 同じ値の再送では marked_at が変わらない
    assert client.patch(url, json={"is_marked": True}).json()["marked_at"] == first
    res = client.patch(url, json={"is_marked": False}).json()
    assert not res["is_marked"] and res["marked_at"] is None
    assert client.patch("/api/articles/99999/mark", json={"is_marked": True}).status_code == 404


def test_mark_is_independent_of_read(client, data):
    mark = f"/api/articles/{data['a0']}/mark"
    read = f"/api/articles/{data['a0']}/read"
    # マークしても未読のまま
    client.patch(mark, json={"is_marked": True})
    detail = client.get(f"/api/articles/{data['a0']}").json()
    assert detail["is_marked"] and not detail["is_read"] and detail["marked_at"]
    # 既読にしてもマークは外れない
    client.patch(read, json={"is_read": True})
    detail = client.get(f"/api/articles/{data['a0']}").json()
    assert detail["is_marked"] and detail["is_read"]
    # 既読を戻してもマークは保持
    client.patch(read, json={"is_read": False})
    assert client.get(f"/api/articles/{data['a0']}").json()["is_marked"]
    # 一括既読でもマークは変わらない
    client.post("/api/articles/mark-read")
    assert client.get(f"/api/articles/{data['a0']}").json()["is_marked"]


def test_list_marked_only(client, data):
    def titles(**params):
        return [i["title"] for i in client.get("/api/articles", params=params).json()["items"]]

    assert titles(marked_only=True) == []
    for key in ("a1", "b0", "a3"):
        client.patch(f"/api/articles/{data[key]}/mark", json={"is_marked": True})
    assert titles(marked_only=True) == ["Alpha 3", "Alpha 1", "Beta 0"]
    items = client.get("/api/articles", params={"marked_only": True}).json()["items"]
    assert all(i["is_marked"] for i in items)
    # 他の条件と併用できる
    assert titles(marked_only=True, feed_id=data["fb"]) == ["Beta 0"]
    assert titles(marked_only=True, q="sure") == ["Alpha 1"]
    assert titles(marked_only=True, since="2026-10-03T00:00:00Z") == ["Alpha 3"]
    client.patch(f"/api/articles/{data['a3']}/read", json={"is_read": True})
    assert titles(marked_only=True, unread_only=True) == ["Alpha 1", "Beta 0"]
    # 件数は total で取れる
    res = client.get("/api/articles", params={"marked_only": True, "per_page": 1}).json()
    assert res["total"] == 3
    # マーク外しで一覧から消える
    client.patch(f"/api/articles/{data['b0']}/mark", json={"is_marked": False})
    assert titles(marked_only=True) == ["Alpha 3", "Alpha 1"]
    # 一覧の既定ではマークの有無に関わらず全件
    assert len(titles()) == 7


def test_detail_neighbors_marked_only(client, data):
    for key in ("a1", "a3", "b1"):
        client.patch(f"/api/articles/{data[key]}/mark", json={"is_marked": True})
    # 現在の記事(a2)がマーク外でも、その位置から見たマーク済みの前後を返す
    res = client.get(f"/api/articles/{data['a2']}", params={"marked_only": True}).json()
    assert res["newer"]["id"] == data["a3"]
    assert res["older"]["id"] == data["b1"]
    res = client.get(f"/api/articles/{data['a3']}", params={"marked_only": True}).json()
    assert res["newer"] is None
    res = client.get(f"/api/articles/{data['a1']}", params={"marked_only": True}).json()
    assert res["older"] is None
    # 指定なしなら従来どおりマーク外も含む
    assert client.get(f"/api/articles/{data['a2']}").json()["newer"]["title"] == "Alpha 3"
