import logging

import httpx

from deep_tracker.config import load_settings
from deep_tracker.notify import SlackNotifier, build_message, gui_url

URL = "https://hooks.slack.com/services/T000/B000/SECRETTOKEN"


def make_settings(tmp_path, enabled=True, host="127.0.0.1"):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        f"frontend: {{host: {host}, port: 3701}}\nslack: {{enabled: {str(enabled).lower()}, "
        f"webhook_url: {URL}}}\n",
        encoding="utf-8",
    )
    return load_settings(cfg)


def make_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_sends_message_with_link(tmp_path):
    sent = []

    def handler(request):
        sent.append((str(request.url), request.read()))
        return httpx.Response(200, text="ok")

    n = SlackNotifier(make_settings(tmp_path), client=make_client(handler))
    assert n.notify("サマリ完了", "週次サマリを作成しました", path="/summaries")
    assert len(sent) == 1
    assert sent[0][0] == URL
    assert b"http://127.0.0.1:3701/summaries" in sent[0][1]


def test_disabled_sends_nothing(tmp_path):
    def handler(request):
        raise AssertionError("送信されてはいけない")

    n = SlackNotifier(make_settings(tmp_path, enabled=False), client=make_client(handler))
    assert not n.enabled
    assert n.notify("title") is False


def test_unset_webhook_sends_nothing(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("instance: default\n", encoding="utf-8")
    n = SlackNotifier(load_settings(cfg))
    assert n.notify("title") is False


def test_failure_does_not_raise_and_retries_once(tmp_path, caplog):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(500)

    n = SlackNotifier(make_settings(tmp_path), client=make_client(handler), sleep=lambda _: None)
    with caplog.at_level(logging.WARNING):
        assert n.notify("title") is False
    assert len(calls) == 2
    assert "HTTP 500" in caplog.text


def test_network_error_does_not_raise(tmp_path):
    def handler(request):
        raise httpx.ConnectError("boom", request=request)

    n = SlackNotifier(make_settings(tmp_path), client=make_client(handler), sleep=lambda _: None)
    assert n.notify("title") is False


def test_retry_succeeds(tmp_path):
    responses = iter([httpx.Response(502), httpx.Response(200)])
    n = SlackNotifier(
        make_settings(tmp_path),
        client=make_client(lambda request: next(responses)),
        sleep=lambda _: None,
    )
    assert n.notify("title") is True


def test_webhook_url_not_logged(tmp_path, caplog):
    def handler(request):
        raise httpx.ConnectError(f"cannot connect to {request.url}", request=request)

    n = SlackNotifier(make_settings(tmp_path), client=make_client(handler), sleep=lambda _: None)
    with caplog.at_level(logging.DEBUG):
        n.notify("title")
    assert "SECRETTOKEN" not in caplog.text
    assert "hooks.slack.com" not in caplog.text


def test_message_and_gui_url(tmp_path):
    assert build_message("t") == "*t*"
    assert build_message("t", "b", "http://x") == "*t*\nb\nhttp://x"
    assert gui_url(make_settings(tmp_path, host="0.0.0.0")) == "http://localhost:3701/"


def test_gui_url_uses_base_url(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("slack: {base_url: 'http://nas.local:3700/'}\n", encoding="utf-8")
    assert gui_url(load_settings(cfg), "/") == "http://nas.local:3700/"
