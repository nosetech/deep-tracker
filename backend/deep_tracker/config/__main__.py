import shlex
import sys

from deep_tracker.config import ConfigError, get_settings
from deep_tracker.config.loader import LOG_DIR


def main() -> int:
    """起動スクリプト向けに、待ち受け設定を `eval` できる形で表示する。"""
    try:
        settings = get_settings()
    except ConfigError as e:
        print(f"設定エラー: {e}", file=sys.stderr)
        return 1
    print(f"INSTANCE={shlex.quote(settings.instance)}")
    print(f"LOG_DIR={shlex.quote(str(LOG_DIR))}")
    print(f"FRONTEND_HOST={shlex.quote(settings.frontend.host)}")
    print(f"FRONTEND_PORT={settings.frontend.port}")
    print(f"BACKEND_PORT={settings.backend.port}")
    # next dev が LAN 内の別ホストからのアクセスを許可するための接続元ホスト
    base_host = settings.slack.base_url.host if settings.slack.base_url else ""
    print(f"BASE_URL_HOST={shlex.quote(base_host or '')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
