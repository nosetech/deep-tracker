import json
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import feedparser

from deep_tracker.db.models import make_guid


class FeedParseError(Exception):
    """フィードとして解析できなかった。"""


@dataclass(frozen=True)
class ParsedEntry:
    """RSS/Atom/JSON Feed の差異を吸収した共通の記事構造（Unified Feed Object）。"""

    guid: str
    title: str
    url: str | None
    content: str | None
    published_at: datetime | None


def parse_feed(content: bytes) -> list[ParsedEntry]:
    if content.lstrip()[:1] == b"{":
        return _parse_json_feed(content)
    return _parse_xml_feed(content)


def parse_feed_title(content: bytes) -> str | None:
    """フィード自体のタイトルを返す。無ければ None。"""
    if content.lstrip()[:1] == b"{":
        try:
            data = json.loads(content)
        except ValueError:
            return None
        title = data.get("title") if isinstance(data, dict) else None
        return title.strip() or None if isinstance(title, str) else None
    title = feedparser.parse(content).feed.get("title")
    return title.strip() or None if title else None


def _parse_xml_feed(content: bytes) -> list[ParsedEntry]:
    parsed = feedparser.parse(content)
    # タイトルもリンクも無い記事は解析失敗（壊れたXMLの残骸）とみなして除外する
    items = [e for e in parsed.entries if e.get("title") or e.get("link")]
    # 壊れたXMLでも読めた記事は採用し、1件も取れず壊れている場合のみ失敗とする。
    # HTML等は version（RSS/Atomの判定結果）が空になるので、フィードではないとみなす
    if not items and (parsed.bozo or not parsed.version):
        reason = parsed.get("bozo_exception")
        raise FeedParseError(f"フィードを解析できません: {reason or '不明な形式'}")

    entries = []
    for e in items:
        title = (e.get("title") or "").strip()
        url = e.get("link") or None
        # 本文（content）を優先し、無ければ要約を使う
        body = None
        if e.get("content"):
            body = e.content[0].get("value")
        body = body or e.get("summary") or None
        published = None
        ts = e.get("published_parsed") or e.get("updated_parsed")
        if ts:
            published = datetime(*ts[:6], tzinfo=UTC)
        entries.append(
            ParsedEntry(
                guid=make_guid(e.get("id"), url, title, published),
                title=title,
                url=url,
                content=body,
                published_at=published,
            )
        )
    return entries


def _parse_json_feed(content: bytes) -> list[ParsedEntry]:
    try:
        data = json.loads(content)
    except ValueError as exc:
        raise FeedParseError(f"JSON Feed を解析できません: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise FeedParseError("JSON Feed ではありません（items がありません）")

    entries = []
    for item in data["items"]:
        if not isinstance(item, dict):
            continue
        title = (item.get("title") or "").strip()
        url = item.get("url") or item.get("external_url") or None
        body = item.get("content_html") or item.get("content_text") or item.get("summary") or None
        published = _parse_date(item.get("date_published"))
        guid = item.get("id")
        entries.append(
            ParsedEntry(
                guid=make_guid(str(guid) if guid else None, url, title, published),
                title=title,
                url=url,
                content=body,
                published_at=published,
            )
        )
    return entries


def _parse_date(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt
