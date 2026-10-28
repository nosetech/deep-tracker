"""Slack Incoming Webhook（一方向）による通知。

無効・未設定なら何もしない。送信失敗は呼び出し元へ伝播させずログに残す。
Webhook URL は秘匿情報のため、ログや例外メッセージに含めない。
"""

import logging
import time
from collections.abc import Callable

import httpx

from deep_tracker.config import Settings
from deep_tracker.config.bind import BindError, resolve_bind_ip
from deep_tracker.config.dev import is_dev_mode

logger = logging.getLogger("deep_tracker.notify.slack")

TIMEOUT_SECONDS = 10.0
MAX_ATTEMPTS = 2  # 初回 + リトライ1回（限定的）
RETRY_WAIT_SECONDS = 1.0


def gui_url(settings: Settings, path: str = "/") -> str:
    if settings.slack.base_url is not None:
        return f"{str(settings.slack.base_url).rstrip('/')}{path}"
    try:
        host = resolve_bind_ip() or "localhost"
    except BindError:
        host = "localhost"
    return f"http://{host}:{settings.frontend.port}{path}"


def build_message(title: str, body: str | None = None, link: str | None = None) -> str:
    lines = [f"*{title}*"]
    if body:
        lines.append(body)
    if link:
        lines.append(link)
    return "\n".join(lines)


class SlackNotifier:
    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._settings = settings
        self._client = client
        self._sleep = sleep

    @property
    def enabled(self) -> bool:
        slack = self._settings.slack
        return slack.enabled and slack.webhook_url is not None

    def notify(self, title: str, body: str | None = None, path: str | None = None) -> bool:
        """通知を送る。送信できたら True。無効時・失敗時は False（例外は出さない）。"""
        if is_dev_mode():
            logger.info("動作確認用インスタンスのため、Slack通知は送信しません: %s", title)
            return False
        if not self.enabled:
            return False
        link = gui_url(self._settings, path) if path is not None else None
        payload = {"text": build_message(title, body, link)}
        url = str(self._settings.slack.webhook_url)
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                self._post(url, payload)
                return True
            except httpx.HTTPStatusError as e:
                # str(e) には URL が含まれるため、ステータスのみ記録する
                reason = f"HTTP {e.response.status_code}"
            except httpx.HTTPError as e:
                reason = type(e).__name__
            logger.warning("Slack通知に失敗しました (%d/%d): %s", attempt, MAX_ATTEMPTS, reason)
            if attempt < MAX_ATTEMPTS:
                self._sleep(RETRY_WAIT_SECONDS)
        return False

    def _post(self, url: str, payload: dict) -> None:
        if self._client is not None:
            self._client.post(url, json=payload).raise_for_status()
            return
        with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
            client.post(url, json=payload).raise_for_status()
