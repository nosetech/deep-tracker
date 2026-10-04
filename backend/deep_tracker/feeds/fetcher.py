from dataclasses import dataclass
from enum import StrEnum

import httpx

USER_AGENT = "deep-tracker/0.1 (+https://github.com/nosetech/deep-tracker)"
TIMEOUT_SECONDS = 30.0
MAX_REDIRECTS = 5


class FetchStatus(StrEnum):
    OK = "ok"
    NOT_MODIFIED = "not_modified"


@dataclass(frozen=True)
class FetchResult:
    status: FetchStatus
    content: bytes = b""
    etag: str | None = None
    last_modified: str | None = None


def fetch_feed(
    url: str,
    *,
    etag: str | None = None,
    last_modified: str | None = None,
    client: httpx.Client | None = None,
) -> FetchResult:
    """フィードを取得する。接続失敗・HTTPエラーは httpx.HTTPError として送出する。

    etag / last_modified を渡すと条件付きGETを行い、304 なら NOT_MODIFIED を返す。
    """
    headers = {"User-Agent": USER_AGENT}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified

    owns_client = client is None
    if client is None:
        client = httpx.Client(
            timeout=TIMEOUT_SECONDS, follow_redirects=True, max_redirects=MAX_REDIRECTS
        )
    try:
        resp = client.get(url, headers=headers)
        if resp.status_code == 304:
            return FetchResult(FetchStatus.NOT_MODIFIED, etag=etag, last_modified=last_modified)
        resp.raise_for_status()
        return FetchResult(
            FetchStatus.OK,
            content=resp.content,
            etag=resp.headers.get("etag"),
            last_modified=resp.headers.get("last-modified"),
        )
    finally:
        if owns_client:
            client.close()
