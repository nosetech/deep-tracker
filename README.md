# Deep Tracker

RSSリーダー + AIによる要約システム。要件は [docs/requirements.md](docs/requirements.md)、技術選定は [docs/architecture.md](docs/architecture.md) を参照。

## 前提

- Python 3.11 以上、[uv](https://docs.astral.sh/uv/)
- Node.js（npm 同梱）

## セットアップ

```sh
cp config/config.yaml.example config/config.yaml   # 現時点では読み込まれない（設定読み込みは今後実装）
(cd backend && uv sync)
(cd frontend && npm install)
```

## 起動

ターミナルを2つ使う。

```sh
# backend（http://127.0.0.1:8700）
cd backend && uv run python -m deep_tracker.main

# frontend（http://localhost:3700）
cd frontend && npm run dev
```

動作確認: `curl http://localhost:3700/api/health` が `{"status":"ok"}` を返せば、frontend から backend への中継まで通っている。
バックエンドの接続先を変える場合は、frontend の環境変数 `BACKEND_URL`（既定 `http://127.0.0.1:8700`）を指定する。

> `NODE_ENV` を `development` 以外にしたシェルで `npm run build` を行うと失敗することがある場合は、`env -u NODE_ENV npm run build` で実行する。

## Lint・テスト・ビルド

```sh
# backend
cd backend
uv run ruff check . && uv run ruff format --check .
uv run pytest

# frontend
cd frontend
npm run lint
npm run format:check
npm run typecheck
npm run build
```
