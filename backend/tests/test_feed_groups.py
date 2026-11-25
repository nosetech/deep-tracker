from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select, text

from deep_tracker.api.deps import get_session
from deep_tracker.config import load_settings
from deep_tracker.db import (
    Article,
    Feed,
    FeedGroup,
    create_db_engine,
    make_session_factory,
    upgrade_db,
)
from deep_tracker.main import app

BACKEND_ROOT = Path(__file__).resolve().parents[1]
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
    """AWS: ec2（記事3・未読2）, rds（記事1・未読1・エラー）。未分類: misc（記事2）。"""
    aws = FeedGroup(name="AWS障害情報", position=1)
    session.add(aws)
    session.flush()
    ec2 = Feed(name="ec2", url="https://status.aws.amazon.com/rss/ec2-ap-northeast-1.rss")
    rds = Feed(name="rds", url="https://status.aws.amazon.com/rss/rds-ap-northeast-1.rss")
    misc = Feed(name="misc", url="https://misc.example/rss")
    ec2.group_id = rds.group_id = aws.id
    rds.last_fetch_ok = False
    session.add_all([ec2, rds, misc])
    session.flush()
    arts = [
        Article(feed_id=ec2.id, guid="e0", title="EC2 0", published_at=BASE, is_read=True),
        Article(feed_id=ec2.id, guid="e1", title="EC2 1", published_at=BASE + timedelta(days=1)),
        Article(feed_id=ec2.id, guid="e2", title="EC2 2", published_at=BASE + timedelta(days=2)),
        Article(feed_id=rds.id, guid="r0", title="RDS 0", published_at=BASE + timedelta(days=1)),
        Article(feed_id=misc.id, guid="m0", title="Misc 0", published_at=BASE),
        Article(feed_id=misc.id, guid="m1", title="Misc 1", published_at=BASE + timedelta(days=3)),
    ]
    session.add_all(arts)
    session.commit()
    return {"aws": aws.id, "ec2": ec2.id, "rds": rds.id, "misc": misc.id}


def test_list_groups_with_counts(client, data, session):
    session.add(FeedGroup(name="Blog"))
    session.commit()
    body = client.get("/api/feed-groups").json()
    # 名前順
    assert [g["name"] for g in body] == ["AWS障害情報", "Blog"]
    aws, blog = body
    assert (aws["feed_count"], aws["enabled_count"], aws["error_count"]) == (2, 2, 1)
    assert aws["unread_count"] == 3
    assert (blog["feed_count"], blog["unread_count"]) == (0, 0)


def test_create_rename_group(client, data):
    res = client.post("/api/feed-groups", json={"name": "  Blog  "})
    assert res.status_code == 201
    group = res.json()
    assert group["name"] == "Blog"
    assert group["feed_count"] == 0

    res = client.patch(f"/api/feed-groups/{group['id']}", json={"name": "Tech Blog"})
    assert res.status_code == 200
    assert res.json()["name"] == "Tech Blog"
    # 同じ名前のまま保存しても重複にはならない
    assert client.patch(f"/api/feed-groups/{group['id']}", json={"name": "Tech Blog"}).is_success


def test_duplicate_and_invalid_name(client, data):
    res = client.post("/api/feed-groups", json={"name": "AWS障害情報"})
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "duplicate_name"

    blog = client.post("/api/feed-groups", json={"name": "Blog"}).json()
    res = client.patch(f"/api/feed-groups/{blog['id']}", json={"name": "AWS障害情報"})
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "duplicate_name"

    # 英字の大文字・小文字は区別しない
    res = client.post("/api/feed-groups", json={"name": "BLOG"})
    assert res.status_code == 409

    res = client.post("/api/feed-groups", json={"name": "   "})
    assert res.status_code == 422
    assert res.json()["detail"]["code"] == "invalid_name"


def test_not_found(client, data):
    assert client.patch("/api/feed-groups/999", json={"name": "x"}).status_code == 404
    assert client.delete("/api/feed-groups/999").status_code == 404
    assert client.post("/api/feed-groups/999/mark-read").status_code == 404
    assert client.post("/api/feed-groups/999/enabled", json={"enabled": False}).status_code == 404


def test_delete_group_keeps_feeds(client, data, session):
    assert client.delete(f"/api/feed-groups/{data['aws']}").status_code == 204
    session.expire_all()
    assert session.get(FeedGroup, data["aws"]) is None
    feeds = {f["name"]: f for f in client.get("/api/feeds").json()}
    assert feeds["ec2"]["group_id"] is None
    assert feeds["rds"]["group_id"] is None
    assert client.get("/api/articles").json()["total"] == 6


def test_delete_sets_null_by_foreign_key(data, session):
    # 外部キー（ON DELETE SET NULL）でも未分類に戻る
    session.execute(text("DELETE FROM feed_groups WHERE id = :id"), {"id": data["aws"]})
    session.commit()
    session.expire_all()
    assert session.get(Feed, data["ec2"]).group_id is None


def test_group_mark_read_and_undo(client, data):
    res = client.post(f"/api/feed-groups/{data['aws']}/mark-read")
    assert res.status_code == 200
    body = res.json()
    assert body["count"] == 3
    unread = client.get("/api/articles", params={"unread_only": True}).json()
    # 未分類の記事は対象外
    assert {a["title"] for a in unread["items"]} == {"Misc 0", "Misc 1"}

    undo = client.post("/api/articles/mark-unread", json={"article_ids": body["article_ids"]})
    assert undo.json()["count"] == 3
    assert client.get("/api/articles", params={"unread_only": True}).json()["total"] == 5


def test_ungrouped_mark_read(client, data):
    body = client.post("/api/feed-groups/ungrouped/mark-read").json()
    assert body["count"] == 2
    unread = client.get("/api/articles", params={"unread_only": True}).json()
    assert {a["title"] for a in unread["items"]} == {"EC2 1", "EC2 2", "RDS 0"}


def test_group_set_enabled(client, data):
    client.patch(f"/api/feeds/{data['rds']}", json={"enabled": False})
    res = client.post(f"/api/feed-groups/{data['aws']}/enabled", json={"enabled": False})
    assert res.status_code == 200
    # すでに無効だった rds は含まない
    assert res.json() == {"count": 1, "feed_ids": [data["ec2"]]}
    feeds = {f["name"]: f for f in client.get("/api/feeds").json()}
    assert (feeds["ec2"]["enabled"], feeds["rds"]["enabled"], feeds["misc"]["enabled"]) == (
        False,
        False,
        True,
    )

    res = client.post(f"/api/feed-groups/{data['aws']}/enabled", json={"enabled": True})
    assert res.json()["count"] == 2


def test_ungrouped_set_enabled(client, data):
    res = client.post("/api/feed-groups/ungrouped/enabled", json={"enabled": False})
    assert res.json() == {"count": 1, "feed_ids": [data["misc"]]}
    feeds = {f["name"]: f for f in client.get("/api/feeds").json()}
    assert feeds["ec2"]["enabled"] is True


def test_assign_and_unassign_group(client, data):
    blog = client.post("/api/feed-groups", json={"name": "Blog"}).json()
    res = client.patch(f"/api/feeds/{data['misc']}", json={"group_id": blog["id"]})
    assert res.status_code == 200
    assert res.json()["group_id"] == blog["id"]
    # group_id を送らない更新では所属は変わらない
    assert (
        client.patch(f"/api/feeds/{data['misc']}", json={"name": "m"}).json()["group_id"]
        == (blog["id"])
    )
    res = client.patch(f"/api/feeds/{data['misc']}", json={"group_id": None})
    assert res.json()["group_id"] is None


def test_assign_unknown_group(client, data):
    res = client.patch(f"/api/feeds/{data['misc']}", json={"group_id": 999})
    assert res.status_code == 422
    assert res.json()["detail"]["code"] == "group_not_found"


def test_filter_articles_by_group(client, data):
    body = client.get("/api/articles", params={"group_id": data["aws"]}).json()
    assert body["total"] == 4
    assert {a["feed_id"] for a in body["items"]} == {data["ec2"], data["rds"]}

    # ほかの条件と併用できる
    params = {"group_id": data["aws"], "unread_only": True, "q": "EC2"}
    body = client.get("/api/articles", params=params).json()
    assert {a["title"] for a in body["items"]} == {"EC2 1", "EC2 2"}

    params = {"group_id": data["aws"], "feed_id": data["rds"]}
    assert client.get("/api/articles", params=params).json()["total"] == 1

    params = {"group_id": data["aws"], "since": (BASE + timedelta(days=2)).isoformat()}
    assert [a["title"] for a in client.get("/api/articles", params=params).json()["items"]] == [
        "EC2 2"
    ]


def test_bulk_mark_read_with_group_filter(client, data):
    res = client.post("/api/articles/mark-read", params={"group_id": data["aws"]})
    assert res.json()["count"] == 3


def test_migration_keeps_existing_feeds_ungrouped(tmp_path):
    db_path = tmp_path / "mig.db"
    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    cfg.attributes["db_path"] = db_path
    command.upgrade(cfg, "0004")
    eng = create_db_engine(db_path)
    try:
        with eng.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO feeds (id, name, url, enabled, created_at)"
                    " VALUES (1, 'f', 'https://e.example/rss', 1, '2026-01-01')"
                )
            )
        command.upgrade(cfg, "0005")
        with make_session_factory(eng)() as s:
            assert s.scalar(select(Feed.group_id).where(Feed.id == 1)) is None
            assert s.scalars(select(FeedGroup)).all() == []
        command.downgrade(cfg, "0004")
        assert "feed_groups" not in inspect(eng).get_table_names()
        assert "group_id" not in {c["name"] for c in inspect(eng).get_columns("feeds")}
        with eng.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM feeds")).scalar() == 1
    finally:
        eng.dispose()
