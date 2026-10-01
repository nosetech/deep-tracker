import uvicorn
from fastapi import FastAPI

from deep_tracker.api import health

# フロントは Next.js の rewrites で /api/* を中継するため、ここでは /api 配下に公開する
app = FastAPI(title="Deep Tracker")
app.include_router(health.router, prefix="/api")


def main() -> None:
    # バックエンドは常に 127.0.0.1 に bind する（LAN公開はフロントのみ）
    uvicorn.run("deep_tracker.main:app", host="127.0.0.1", port=8700)


if __name__ == "__main__":
    main()
