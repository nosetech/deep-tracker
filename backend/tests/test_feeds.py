import json
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select

from deep_tracker.config import load_settings
from deep_tracker.db import Article, Feed, create_db_engine, make_session_factory, upgrade_db
from deep_tracker.feeds import (
    FeedParseError,
    FetchStatus,
    fetch_all_feeds,
    fetch_and_store,
    fetch_feed,
    parse_feed,
)

AWS_URL = "https://aws.amazon.com/jp/about-aws/whats-new/recent/feed/"
FIXTURES = Path(__file__).parent / "fixtures"
AWS_XML = (FIXTURES / "aws_whats_new.xml").read_bytes()

RSS_NO_GUID = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><title>With link</title><link>https://example.com/a</link><description>d1</description></item>
<item><title>No link</title><pubDate>Mon, 05 Oct 2026 01:00:00 GMT</pubDate></item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>t</title><id>urn:feed</id>
<entry><id>urn:e1</id><title>Atom entry</title><link href="https://example.com/e1"/>
<updated>2026-10-05T01:02:03Z</updated><summary>summary</summary>
<content type="html">&lt;p&gt;full&lt;/p&gt;</content></entry></feed>"""

JSON_FEED = json.dumps(
    {
        "version": "https://jsonfeed.org/version/1.1",
        "title": "t",
        "items": [
            {
                "id": "j1",
                "url": "https://example.com/j1",
                "title": "Json entry",
                "content_text": "body",
                "date_published": "2026-10-05T01:02:03Z",
            },
            {"title": "no id", "url": "https://example.com/j2"},
        ],
    }
).encode()


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


def mock_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def aws_client(**headers) -> httpx.Client:
    return mock_client(lambda req: httpx.Response(200, content=AWS_XML, headers=headers))


def add_feed(session, url=AWS_URL, name="feed") -> Feed:
    feed = Feed(name=name, url=url)
    session.add(feed)
    session.commit()
    return feed


def count_articles(session) -> int:
    return session.scalar(select(func.count()).select_from(Article))


# --- 解析 ---


def test_parse_aws_rss():
    entries = parse_feed(AWS_XML)
    assert len(entries) > 10
    e = entries[0]
    assert e.guid and e.title and e.url and e.published_at is not None
    assert e.published_at.tzinfo is not None
    assert e.content  # description を要約として保持
    assert len({x.guid for x in entries}) == len(entries)


def test_parse_rss_without_guid_falls_back():
    entries = parse_feed(RSS_NO_GUID)
    assert entries[0].guid.startswith("url:")
    assert entries[1].guid.startswith("title:")
    assert entries[0].content == "d1"
    assert entries[1].content is None


def test_parse_atom_prefers_content():
    (e,) = parse_feed(ATOM)
    assert e.guid == "urn:e1"
    assert e.content == "<p>full</p>"
    assert e.url == "https://example.com/e1"
    assert e.published_at.year == 2026 and e.published_at.second == 3


def test_parse_json_feed():
    entries = parse_feed(JSON_FEED)
    assert entries[0].guid == "j1"
    assert entries[0].content == "body"
    assert entries[0].published_at.isoformat() == "2026-10-05T01:02:03+00:00"
    assert entries[1].guid.startswith("url:")


@pytest.mark.parametrize("bad", [b"<rss><channel><item>", b"not a feed at all", b"{broken", b"{}"])
def test_parse_broken_raises(bad):
    with pytest.raises(FeedParseError):
        parse_feed(bad)


# --- 取得 ---


def test_fetch_sends_conditional_headers_and_handles_304():
    seen = {}

    def handler(req):
        seen.update(req.headers)
        return httpx.Response(304)

    result = fetch_feed(
        AWS_URL,
        etag='"abc"',
        last_modified="Sun, 04 Oct 2026 00:00:00 GMT",
        client=mock_client(handler),
    )
    assert result.status is FetchStatus.NOT_MODIFIED
    assert seen["if-none-match"] == '"abc"'
    assert seen["if-modified-since"] == "Sun, 04 Oct 2026 00:00:00 GMT"
    assert "deep-tracker" in seen["user-agent"]


def test_fetch_follows_redirect():
    def handler(req):
        if req.url.path == "/old":
            return httpx.Response(301, headers={"location": "https://example.com/new"})
        return httpx.Response(200, content=b"ok")

    assert fetch_feed("https://example.com/old", client=mock_client(handler)).content == b"ok"


# --- 保存 ---


def test_fetch_and_store_saves_aws_articles(session):
    feed = add_feed(session)
    added = fetch_and_store(session, feed, client=aws_client(etag='"v1"'))
    assert added > 10
    assert count_articles(session) == added
    assert feed.last_fetch_ok is True
    assert feed.last_fetch_error is None
    assert feed.last_fetched_at is not None
    assert feed.etag == '"v1"'


def test_refetch_does_not_duplicate(session):
    feed = add_feed(session)
    first = fetch_and_store(session, feed, client=aws_client())
    assert fetch_and_store(session, feed, client=aws_client()) == 0
    assert count_articles(session) == first


def test_not_modified_keeps_articles_and_succeeds(session):
    feed = add_feed(session)
    fetch_and_store(session, feed, client=aws_client(etag='"v1"'))
    n = count_articles(session)
    assert fetch_and_store(session, feed, client=mock_client(lambda r: httpx.Response(304))) == 0
    assert count_articles(session) == n
    assert feed.last_fetch_ok is True
    assert feed.etag == '"v1"'


def test_duplicate_guid_within_feed_saved_once(session):
    xml = b"""<rss version="2.0"><channel><title>t</title>
    <item><guid>x</guid><title>a</title></item><item><guid>x</guid><title>b</title></item>
    </channel></rss>"""
    feed = add_feed(session)
    client = mock_client(lambda r: httpx.Response(200, content=xml))
    assert fetch_and_store(session, feed, client=client) == 1


@pytest.mark.parametrize(
    ("handler", "expected"),
    [
        (lambda r: httpx.Response(500), "HTTPエラー: 500"),
        (lambda r: httpx.Response(404), "HTTPエラー: 404"),
        (lambda r: httpx.Response(200, content=b"not a feed"), "解析"),
    ],
)
def test_error_recorded_on_feed(session, handler, expected):
    feed = add_feed(session)
    assert fetch_and_store(session, feed, client=mock_client(handler)) == 0
    assert feed.last_fetch_ok is False
    assert expected in feed.last_fetch_error
    assert feed.last_fetched_at is not None


def test_connection_error_recorded(session):
    def handler(req):
        raise httpx.ConnectError("refused")

    feed = add_feed(session)
    fetch_and_store(session, feed, client=mock_client(handler))
    assert feed.last_fetch_ok is False
    assert "接続に失敗" in feed.last_fetch_error


def test_failure_then_success_clears_error(session):
    feed = add_feed(session)
    fetch_and_store(session, feed, client=mock_client(lambda r: httpx.Response(500)))
    fetch_and_store(session, feed, client=aws_client())
    assert feed.last_fetch_ok is True
    assert feed.last_fetch_error is None


def test_one_failing_feed_does_not_stop_others(session):
    bad = add_feed(session, "https://bad.example.com/feed", "bad")
    good = add_feed(session, AWS_URL, "good")
    disabled = add_feed(session, "https://off.example.com/feed", "off")
    disabled.enabled = False
    session.commit()

    def handler(req):
        if req.url.host == "bad.example.com":
            return httpx.Response(500)
        return httpx.Response(200, content=AWS_XML)

    result = fetch_all_feeds(session, client=mock_client(handler))
    assert result[bad.id] == 0
    assert result[good.id] > 10
    assert disabled.id not in result
    assert bad.last_fetch_ok is False
    assert good.last_fetch_ok is True


# --- 実URL（手動/任意実行: pytest -m network） ---


@pytest.mark.network
def test_live_aws_feed(session):
    feed = add_feed(session)
    assert fetch_and_store(session, feed) > 0
    assert feed.last_fetch_ok is True
