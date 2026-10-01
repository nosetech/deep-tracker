# Deep Tracker アーキテクチャ・技術選定

[requirements.md](./requirements.md) の確定事項を前提に、フェーズ0で確定した実装技術を記録する。

## 1. 技術選定一覧

| 領域 | 採用 | 備考 |
|---|---|---|
| DB | SQLite（WAL モード） | マイグレーションは Alembic |
| DBアクセス | SQLAlchemy 2.x（同期API） | Alembic と同一のモデル定義を使う |
| Webフレームワーク | FastAPI + uvicorn | |
| フィード解析 | feedparser（RSS 1.0/2.0・Atom）＋ JSON Feed は自前の薄いパーサ | HTTP取得は httpx |
| Python | 3.11 以上 | producer-desk と同じ |
| Pythonパッケージ管理 | uv + `pyproject.toml`（`uv.lock` をコミット） | lint/format は ruff、テストは pytest |
| フロント | Next.js（App Router）/ TypeScript | |
| フロントのパッケージ管理 | npm（`package-lock.json` をコミット） | |
| frontend ⇔ backend | Next.js の `rewrites` で `/api/*` をバックエンドへ中継 | |

## 2. 選定理由

### 2-1. DB: SQLite

- 利用者は1名で、想定規模は数十万記事程度。SQLite で性能上の問題はない（全文検索が必要になれば FTS5 で対応できる）。
- サーバプロセスが不要で、ローカルPC・launchd 運用と相性が良い。DBファイル単体のコピーでバックアップでき、バージョン別のDB分離（後述）も容易。
- 書き込みは「定期バッチ」と「API」の2系統が並行しうるため、WAL モードと `busy_timeout` を有効にする。
- スキーマ変更は Alembic で管理する。SQLite の `ALTER TABLE` 制約には batch mode（`render_as_batch=True`）で対応する。
- 将来 PostgreSQL 等へ移す場合に備え、SQLAlchemy を介して SQLite 固有機能への依存を最小限にする。

### 2-2. Webフレームワーク: FastAPI

- 型ヒントからリクエスト/レスポンス検証と OpenAPI を自動生成でき、TypeScript 側の型生成にも使える。
- producer-desk の orchestrator は Web API を持たない（ポーリング型の常駐プロセス）ため直接の比較対象にならない。ただし `pyproject.toml`（setuptools、ruff、pytest）の構成は踏襲する。
- Claude Code CLI 呼び出しなどの長時間処理は、API リクエスト内で行わずジョブとして切り出す（フェーズ3）。FastAPI の `BackgroundTasks` ではなく、別プロセス（launchd ジョブ）で実行する前提とする。
- API サーバは同期の SQLAlchemy を使うため、エンドポイントは基本的に `def`（スレッドプール実行）で書く。

### 2-3. フィード解析: feedparser

- RSS 0.9x/1.0/2.0 と Atom を同一の構造に正規化できる。要件の「差異はパース層で統一する」に合致する。
- **feedparser は JSON Feed を解釈しない。** `application/feed+json` / `application/json` の場合は JSON を直接読み、同じ共通構造（タイトル・URL・公開日時・本文・GUID）へ変換する薄いパーサを自前で書く。
- ネットワーク取得は feedparser に任せず httpx で行う（タイムアウト、リダイレクト、ETag/Last-Modified による条件付きGET、User-Agent を制御するため）。取得したバイト列を feedparser に渡す。
- 記事の同一性判定は GUID（なければリンク、さらに無ければタイトル+公開日時のハッシュ）で行う。
- テストでは最低限 `https://aws.amazon.com/jp/about-aws/whats-new/recent/feed/` を使う（CLAUDE.md 参照）。

### 2-4. パッケージ管理

- Python: uv。ロックファイルによる再現性と高速な環境構築が得られる。ビルドバックエンドは setuptools（producer-desk と同じ）。
- Next.js: npm。追加のツール導入が不要で、macOS 環境に既にある。pnpm は導入しない。

### 2-5. frontend と backend の通信

- ブラウザは常に Next.js のオリジンへ `/api/*` でアクセスし、Next.js の `rewrites` がバックエンドへ中継する。ブラウザから見て同一オリジンになるため、CORS 設定が不要になる。
- 中継先は環境変数 `BACKEND_URL`（既定 `http://127.0.0.1:<backend_port>`）で指定する。値は設定ファイルのポートと一致させる。
- LAN公開時もブラウザが到達するのは Next.js のポートのみでよく、バックエンドは常に `127.0.0.1` に bind したままにできる。LAN公開の設定（`0.0.0.0` への切替）は frontend の待ち受けにのみ適用する。
- RSS の取得は引き続きバックエンドからのみ行う。

## 3. 複数バージョン並行稼働

バージョン（例: `0.1.0` と `0.2.0`）ごとに展開先ディレクトリを分け、設定ファイルも各展開先に同梱する。バージョン間で衝突する資源は、すべて設定ファイルの値から導出する。

| 資源 | 割り当て方針 |
|---|---|
| ポート | バージョンごとに設定ファイルで指定する。`backend.port` と `frontend.port` を別々に持ち、既定は backend 8700 / frontend 3700。並行稼働する際は、バージョンごとに +10 ずつずらす（例: 8710 / 3710） |
| DBパス | `db.path` で指定する。既定は展開先配下の `data/deep-tracker.db`。展開先ごとに別ファイルになるため衝突しない |
| launchdジョブ名 | `com.nosetech.deep-tracker.<instance>.<job>` とする。`<instance>` は設定ファイルの `instance`（既定 `default`、並行稼働時はバージョン番号など）、`<job>` は `backend` / `frontend` / `fetch` / `summary` |
| plist・ログ | 展開先配下の `logs/` に出力する。plist は展開時に `instance` を埋め込んで生成する |

- 同じ DB ファイルを複数バージョンが同時に開かないこと。スキーマの異なるバージョンが同一DBを触るとマイグレーションが衝突するため、DBパスは必ずバージョンごとに分ける。
- ポートが使用中の場合、起動時にエラーで終了する（自動で別ポートへ退避しない）。

## 4. 想定ディレクトリ構成

```
backend/
  pyproject.toml
  uv.lock
  alembic.ini
  deep_tracker/   # api / db / feeds / ai / jobs / config
  tests/
frontend/
  package.json
  package-lock.json
  next.config.ts  # rewrites
config/
  config.yaml.example
```

実ファイルの `config.yaml` は `.gitignore` に入れる。
