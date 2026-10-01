import sys

import uvicorn
from fastapi import FastAPI

from deep_tracker.api import config, health

# フロントは Next.js の rewrites で /api/* を中継するため、ここでは /api 配下に公開する
app = FastAPI(title="Deep Tracker")
app.include_router(health.router, prefix="/api")
app.include_router(config.router, prefix="/api")


def main() -> None:
    from deep_tracker.config import ConfigError, get_settings

    try:
        settings = get_settings()
    except ConfigError as e:
        # 不正な設定では起動しない
        print(f"設定エラー: {e}", file=sys.stderr)
        sys.exit(1)
    # バックエンドは常に 127.0.0.1 に bind する（LAN公開はフロントのみ）
    uvicorn.run("deep_tracker.main:app", host="127.0.0.1", port=settings.backend.port)


if __name__ == "__main__":
    main()
