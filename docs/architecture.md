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
  migrations/     # Alembic（env.py / versions/）
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

## 5. DBスキーマ

定義は `backend/deep_tracker/db/models.py`（SQLAlchemy）、マイグレーションは `backend/migrations/versions/`（Alembic）。

### 5-1. 共通方針

- DBパスは設定 `db.path` から取得する。`upgrade_db()` が最新まで適用し、DBファイルが無ければ（親ディレクトリごと）作成する。アプリ起動時に呼ぶ想定。CLI からは `DEEP_TRACKER_CONFIG` を設定して `uv run alembic upgrade head` でも実行できる。
- 接続ごとに `journal_mode=WAL`・`foreign_keys=ON`・`busy_timeout=5000` を設定する（`create_db_engine()`）。
- 日時は UTC で保存する。SQLite はタイムゾーンを保持しないため、`UtcDateTime` 型が書き込み時に UTC の naive 値へ変換し、読み出し時に UTC を付ける。naive な datetime の書き込みはエラーにする。
- 制約・索引の名前は命名規則（`naming_convention`）で固定する。SQLite の batch mode でのスキーマ変更に必要。
- モデルとマイグレーションの乖離はテスト（`test_migration_matches_models`）で検出する。

### 5-2. テーブル

**feeds**（購読フィード）

| カラム | 型 | 説明 |
|---|---|---|
| id | integer PK | |
| name | text | 表示名 |
| url | text UNIQUE | フィードURL（同一URLの二重購読を防ぐ） |
| fetch_interval_minutes | integer NULL | 取得間隔。NULL は設定 `feed.fetch_interval_minutes` を使う |
| enabled | boolean | 有効/無効（既定 true） |
| created_at | datetime | |
| last_fetched_at | datetime NULL | 最終取得日時 |
| last_fetch_ok | boolean NULL | 最終取得の成否。未取得は NULL |
| last_fetch_error | text NULL | 最終取得の失敗理由 |

**articles**（記事）

| カラム | 型 | 説明 |
|---|---|---|
| id | integer PK | |
| feed_id | integer FK → feeds.id | フィード削除時は記事も削除（ON DELETE CASCADE） |
| guid | text | 記事の同一性キー（5-3 参照） |
| title | text | |
| url | text NULL | 記事URL |
| content | text NULL | フィードが提供する本文または要約 |
| published_at | datetime NULL | 公開日時 |
| fetched_at | datetime | 取得日時 |
| is_read | boolean | 既読フラグ（既定 false） |
| read_at | datetime NULL | 既読日時 |

**summaries**（サマリ）

| カラム | 型 | 説明 |
|---|---|---|
| id | integer PK | |
| period_start / period_end | datetime | 対象期間 |
| created_at | datetime | 生成日時 |
| body | text NULL | 本文。生成前・失敗時は NULL |
| status | text | `pending` / `running` / `succeeded` / `failed` |

**summary_articles**（サマリと元記事の関連。PK は `(summary_id, article_id)`）

どちらの親が削除されても関連行のみ連鎖削除される。記事が保存期間で削除されてもサマリ本体は残る。

**ai_jobs**（AIジョブ）

| カラム | 型 | 説明 |
|---|---|---|
| id | integer PK | |
| kind | text | ジョブ種別（例: `summary`） |
| status | text | `pending` / `running` / `succeeded` / `failed` |
| input / result | JSON NULL | 入力・結果 |
| error | text NULL | 失敗理由 |
| created_at / started_at / finished_at | datetime | started_at・finished_at は NULL 可 |

`status` は文字列で保持し、取りうる値はアプリ側で検証する（値の追加でマイグレーションを要さないため）。

### 5-3. 記事の重複排除

- `articles` に `UNIQUE (feed_id, guid)` を張り、同一フィード内の二重登録をDBで防ぐ。フィードをまたぐ同一記事は別記事として扱う。
- `guid` はフィードが GUID を持てばその値、無ければ `make_guid()` でフォールバックする。
  1. GUID（JSON Feed の `id`、Atom の `id`、RSS の `guid`）
  2. 記事URLの SHA-256（`url:` 接頭辞）
  3. タイトル+公開日時の SHA-256（`title:` 接頭辞）
- 取り込み側は、既存記事と衝突した場合に無視（`INSERT ... ON CONFLICT DO NOTHING`）する。

### 5-4. 索引

| 索引 | 用途 |
|---|---|
| `articles(published_at)` | 新着順の一覧、保存期間による削除 |
| `articles(feed_id, published_at)` | フィード別の一覧。`(feed_id, guid)` の一意索引はフィード単位の絞り込みにも効く |
| `articles(is_read, published_at)` | 未読のみの一覧 |
| `summary_articles(article_id)` | 記事からサマリへの逆引き |
| `summaries(period_start)` | サマリ一覧 |
| `ai_jobs(status, created_at)` | 未処理ジョブの取得 |
