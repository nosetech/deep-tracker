# Deep Tracker アーキテクチャ・技術選定

[requirements.md](./requirements.md) の確定事項を前提に、フェーズ0で確定した実装技術を記録する。

## 1. 技術選定一覧

| 領域                     | 採用                                                           | 備考                                 |
| ------------------------ | -------------------------------------------------------------- | ------------------------------------ |
| DB                       | SQLite（WAL モード）                                           | マイグレーションは Alembic           |
| DBアクセス               | SQLAlchemy 2.x（同期API）                                      | Alembic と同一のモデル定義を使う     |
| Webフレームワーク        | FastAPI + uvicorn                                              |                                      |
| フィード解析             | feedparser（RSS 1.0/2.0・Atom）＋ JSON Feed は自前の薄いパーサ | HTTP取得は httpx                     |
| Python                   | 3.11 以上                                                      | producer-desk と同じ                 |
| Pythonパッケージ管理     | uv + `pyproject.toml`（`uv.lock` をコミット）                  | lint/format は ruff、テストは pytest |
| フロント                 | Next.js（App Router）/ TypeScript                              |                                      |
| フロントのパッケージ管理 | npm（`package-lock.json` をコミット）                          |                                      |
| frontend ⇔ backend       | Next.js の `rewrites` で `/api/*` をバックエンドへ中継         |                                      |

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

- ブラウザは常に Next.js のオリジンへ `/api/*` でアクセスし、Next.js の Route Handler（`frontend/app/api/[...path]/route.ts`）がバックエンドへ中継する。ブラウザから見て同一オリジンになるため、CORS 設定が不要になる。
- 中継先は環境変数 `BACKEND_URL`（既定 `http://127.0.0.1:<backend_port>`）で指定する。値は設定ファイルのポートと一致させる。ビルド時固定の `rewrites` ではなく実行時に読むため、変更してもビルドし直し不要。バックエンド停止時は 502 を返す。SSE などのストリーミング応答は使っていない。
- LAN公開時もブラウザが到達するのは Next.js のポートのみでよく、バックエンドは常に `127.0.0.1` に bind したままにできる。LAN公開は frontend の待ち受けにのみ適用し、環境変数 `LAN_IP` / `TAILSCALE_IP`（どちらか一方。両方指定はエラー）で指定したIPに bind する。未指定なら `127.0.0.1`。`0.0.0.0` では待ち受けない。
- RSS の取得は引き続きバックエンドからのみ行う。

### 2-6. タブへの未読表示

- `frontend/lib/tab-unread.ts` に件数の書式・ファビコンSVG・ポーリング制御を純粋関数として置き、`components/useUnreadCount.ts` のフックから使う。
- 未読件数は `GET /api/articles/unread-counts` を60秒間隔（`UNREAD_POLL_INTERVAL_MS`）でポーリングする。`hidden` でも継続し、`visibilitychange` で `visible` に戻ったときと `SHELL_REFRESH_EVENT` で即時再取得する。
- タイトルは `document.title` の先頭の件数をクライアント側で付け替え、`<title>` を `MutationObserver` で監視してページ遷移後も再適用する。
- ファビコンは未読があるとき、`app/icon.svg` と同じ図形に右上のドットを重ねたSVGを `data:` URL で `<link rel="icon">` に追加し、既存のiconは無効化する。0件で元に戻す。

### 2-7. PC表示の画面構成

- `components/AppShell.tsx` が `.app`（縦flex）の先頭に全幅の `.pc-header`（52px）を置き、その下の `.app-body`（横flex、`flex:1; min-height:0`）にサイドバーと `.main-col` を並べる。
- ヘッダーは `flex:none` で固定し、サイドバーと `.main` が独立してスクロールする。記事一覧の日付見出しの `sticky` の基準は `.main` のまま。
- サイドバーは `components/Sidebar.tsx`。外枠 `.sidebar-slot` の幅は折りたたみ状態（232px / 68px）だけで決まり、内側の `.sidebar` が絶対配置で、折りたたみ中のホバー・フォーカス（遅延 140ms / 220ms）では幅だけ広がって本文に重なる（一時展開、影付き）。`width` は `0.2s ease` で遷移し、`prefers-reduced-motion: reduce` では無効。
- 折りたたみ状態は `localStorage`（キー `deep-tracker.sidebar`、`{"collapsed":true}`）に保存する。ちらつき防止のため、テーマと同様に hydration 前のインラインスクリプト（`lib/sidebar-state.ts` の `sidebarInitScript`）が `<html data-sidebar="collapsed">` を付け、見た目は CSS が属性で決める。保存値は型を検証し、壊れていれば展開に戻す。
- 720px未満では `.pc-header` と `.sidebar` を非表示にし、`.mobile-header` / `.bottom-nav` を使う。

### 2-7-1. ページの横幅

- サマリ・記事一覧・購読フィード・記事詳細・読み込み中（スケルトン）は、固定の `max-width` を持たず、サイドバーを除いた領域の幅に合わせて広がる。
- 超ワイド画面での間延びを避けるため、ページ全体の上限は1600px（左右padding 44pxずつを含むため、内容は `.main` の `--page-max: 1512px`）。上限を超えても中央寄せにせず、左寄せのまま。
- サマリは左（サマリ本文、`flex: 1 1 560px`）を伸縮させ、右のサイド（一覧・元記事プレビュー）は現状の幅（1180px以上で280px）を維持する。
- 記事本文（`.det-body`）の行長は `38em` のまま（左寄せ）。記事詳細のタイトル・メタ情報・操作ボタンは上限まで広がる。
- 999px以下・719px以下の既存の切り替えは変えない。
- 指示プロンプトは [design-prompt-ui-diff-fluid-width.md](./design-prompt-ui-diff-fluid-width.md)。

### 2-8. モバイルの画面高さ

- `.app` の高さは `100dvh`（非対応ブラウザ向けに `100vh` をフォールバックとして先に記述）。アドレスバーの出入りに追従し、ヘッダー・フッターが常に画面内に収まる。
- `html` / `body` は `overflow: hidden` とし、ページ自体はスクロールさせない。スクロールは `.main` のみ。
- `viewportFit: "cover"` を指定し、ヘッダー・フッターは `env(safe-area-inset-top/bottom)` 分を足してノッチ・ホームバーと重ならないようにする。

### 2-9. フィード登録時のエラー

`POST /api/feeds` と `PATCH /api/feeds/{id}`（URL変更）は、失敗時に `detail.code` で原因を区別する。

| ステータス | code | 意味 |
| --- | --- | --- |
| 422 | `invalid_url` | URLの形式が不正（http / https 以外など） |
| 409 | `duplicate_url` | 登録済みのURL |
| 422 | `fetch_failed` | 取得に失敗（接続失敗・タイムアウト・HTTPエラー）。`detail.reason`（`http_status` / `timeout` / `connect`）と、HTTPエラーのときは `detail.http_status` を含む |
| 422 | `not_a_feed` | 取得できたが RSS / Atom / JSON Feed として解析できない |

- 画面は code ごとに文言を出し分ける。`not_a_feed` は「RSS / Atom として解析できませんでした。」、`fetch_failed` は「フィードを取得できませんでした。」を前置する。解析エラーの前置きを取得エラーに付けない。
- `fetch_failed` には本文の下に `fetch_failed · 429` 形式のコード行を等幅で出し、ステータス別の補足を付ける（429・403: 配信元がアクセスを制限している可能性があり別のフィード URL を試す／404: URL を確認する／5xx: 時間をおいて再試行／タイムアウト・接続失敗: URL とネットワークを確認する）。文言は `frontend/lib/feed-error.ts`。
- 429・403 は配信元のボット対策であることが多い。User-Agent の偽装などでの回避は行わず、別のURLを案内するだけにする。
- 登録後の定期取得の失敗（`feeds.last_fetch_error`）は、従来どおり `describe_error()` の文字列を保存して表示する（画面側の補足は付けない）。

## 3. 複数バージョン並行稼働

バージョン（例: `0.1.0` と `0.2.0`）ごとに展開先ディレクトリを分け、設定ファイルも各展開先に同梱する。バージョン間で衝突する資源は、すべて設定ファイルの値から導出する。

| 資源            | 割り当て方針                                                                                                                                                                                             |
| --------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| ポート          | バージョンごとに設定ファイルで指定する。`backend.port` と `frontend.port` を別々に持ち、既定は backend 8700 / frontend 3700。並行稼働する際は、バージョンごとに +10 ずつずらす（例: 8710 / 3710）        |
| DBパス          | `db.path` で指定する。既定は展開先配下の `data/deep-tracker.db`。展開先ごとに別ファイルになるため衝突しない                                                                                              |
| launchdジョブ名 | `com.nosetech.deep-tracker.<instance>.<job>` とする。`<instance>` は設定ファイルの `instance`（既定 `default`、並行稼働時はバージョン番号など）、`<job>` は `backend` / `frontend` / `fetch` / `summary` / `backup` |
| plist・ログ     | 展開先配下の `logs/` に出力する。plist は展開時に `instance` を埋め込んで生成する                                                                                                                        |

- 同じ DB ファイルを複数バージョンが同時に開かないこと。スキーマの異なるバージョンが同一DBを触るとマイグレーションが衝突するため、DBパスは必ずバージョンごとに分ける。
- ポートが使用中の場合、起動時にエラーで終了する（自動で別ポートへ退避しない）。

### DBバックアップ

- `backend/deep_tracker/jobs/backup.py`（`python -m deep_tracker.jobs.backup`）を、launchd のジョブ `backup`（`scripts/backup-job.sh`）が毎日3:00（`StartCalendarInterval`）に実行する。
- 方式は SQLite のオンラインバックアップAPI（標準ライブラリの `sqlite3.Connection.backup()`）。DBは WAL モードだが、このAPIは稼働中でも整合したスナップショットを作る。`cp` は `-wal` / `-shm` の取りこぼしや書き込みとの競合で不整合になりうるため使わない。外部の `sqlite3` コマンドにも依存しない。
- 一時ファイル（`*.db.tmp`）に書き、`PRAGMA integrity_check` で検証してから rename する。失敗時は一時ファイルを消し、不完全なバックアップを残さない。バックアップは `journal_mode=DELETE` の単一ファイルにする。
- 保存先は `<backup.dir>/<instance>/deep-tracker-<instance>-YYYYmmdd-HHMMSS.db`（JST）。`instance` ごとにディレクトリとファイル名を分けて、並行稼働するバージョン間の衝突を防ぐ。
- 世代管理は `backup.retention_days`（既定30）を超えた mtime のファイルの削除で、対象は自分の `instance` のファイル名パターンのみ。
- DBが無ければスキップして正常終了。失敗は `logs/backup.log` に記録し、`slack.notify_on_failure` が true ならSlack通知する。
- リストアは手順書のみ（`dist/SETUP.md` / `docs/setup.md`）。スクリプトは持たない。

### ログのローテーション

- `backend.log` / `frontend.log` / `fetch.log` / `summary.log` / `backup.log` を、JST 0時に日次ローテーションする（`TimedRotatingFileHandler` のサブクラス `JstMidnightRotatingFileHandler`。0時の判定・世代ファイル名 `*.log.YYYY-MM-DD`・ログ内の時刻をOSのタイムゾーンに依存させずJSTに固定する。`backend/deep_tracker/logging_config.py`）。
- 保持日数は設定 `logging.retention_days`（既定7、1以上の整数）。超えた世代はハンドラが自動削除する。
- logging を経由しない出力は、`python -m deep_tracker.log_rotator --path <file>`（標準入力を加工せず書き出すローテータ）へパイプして書き出す。対象は frontend（Next.js）の出力と、backend 本体の標準出力・標準エラー（起動前のクラッシュ・未捕捉例外。`backend.log` と同じパスを2プロセスが開くとローテーションが競合するため `backend.stderr.log` に分ける）。`scripts/start.sh` は `>>` リダイレクトではなくプロセス置換でパイプし、launchd の plist も `StandardOutPath` を使わず `bash -c` で同じパイプを組む。ローテータは書き込みエラー・設定読み込み失敗・不正なUTF-8でも落ちない（落ちると本体が SIGPIPE を受けるため）。
- `*.launchd.log`（fetch / summary / backup の起動直後のクラッシュ専用）は plist のまま。通常ログは logging 経由で、端末から手動実行したときだけ標準出力にも出す。
- 動作確認用インスタンス（`scripts/dev-instance.sh`）は `.dev-run/` に出すだけでローテーションしない。

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

| カラム                 | 型            | 説明                                                       |
| ---------------------- | ------------- | ---------------------------------------------------------- |
| id                     | integer PK    |                                                            |
| name                   | text          | 表示名                                                     |
| url                    | text UNIQUE   | フィードURL（同一URLの二重購読を防ぐ）                     |
| fetch_interval_minutes | integer NULL  | 取得間隔。NULL は設定 `feed.fetch_interval_minutes` を使う |
| enabled                | boolean       | 有効/無効（既定 true）                                     |
| created_at             | datetime      |                                                            |
| last_fetched_at        | datetime NULL | 最終取得日時                                               |
| last_fetch_ok          | boolean NULL  | 最終取得の成否。未取得は NULL                              |
| last_fetch_error       | text NULL     | 最終取得の失敗理由                                         |

**articles**（記事）

| カラム       | 型                    | 説明                                            |
| ------------ | --------------------- | ----------------------------------------------- |
| id           | integer PK            |                                                 |
| feed_id      | integer FK → feeds.id | フィード削除時は記事も削除（ON DELETE CASCADE） |
| guid         | text                  | 記事の同一性キー（5-3 参照）                    |
| title        | text                  |                                                 |
| url          | text NULL             | 記事URL                                         |
| content      | text NULL             | フィードが提供する本文または要約                |
| published_at | datetime NULL         | 公開日時                                        |
| fetched_at   | datetime              | 取得日時                                        |
| is_read      | boolean               | 既読フラグ（既定 false）                        |
| read_at      | datetime NULL         | 既読日時                                        |

**summaries**（サマリ）

| カラム                    | 型         | 説明                                           |
| ------------------------- | ---------- | ---------------------------------------------- |
| id                        | integer PK |                                                |
| period_start / period_end | datetime   | 対象期間                                       |
| created_at                | datetime   | 生成日時                                       |
| body                      | text NULL  | 本文。生成前・失敗時は NULL                    |
| status                    | text       | `pending` / `running` / `succeeded` / `failed` |

`body` には `{"overview": 総評, "topics": [{"title", "summary", "article_ids"}]}` のJSONを保存する（トピックごとの元記事は `article_ids`）。対象期間に記事が0件の場合はサマリを生成しない。AIの出力が不正な場合は `status=failed` で記録する。プロンプトは `backend/deep_tracker/summary/prompts/summary.md`。

**summary_articles**（サマリと元記事の関連。PK は `(summary_id, article_id)`）

どちらの親が削除されても関連行のみ連鎖削除される。記事が保存期間で削除されてもサマリ本体は残る（関連行のみ消え、サマリ上の元記事リンクは無効として扱う）。保存期間の起点は取得日時（`fetched_at`）。公開日時だと、フィードに残る古い記事が削除後に再取得されて未読として復活するため。削除は定期取得バッチの末尾で実行し、削除件数をログに出す。

**ai_jobs**（AIジョブ）

| カラム                                | 型         | 説明                                           |
| ------------------------------------- | ---------- | ---------------------------------------------- |
| id                                    | integer PK |                                                |
| kind                                  | text       | ジョブ種別（例: `summary`）                    |
| status                                | text       | `pending` / `running` / `succeeded` / `failed` |
| input / result                        | JSON NULL  | 入力・結果                                     |
| error                                 | text NULL  | 失敗理由                                       |
| created_at / started_at / finished_at | datetime   | started_at・finished_at は NULL 可             |

`status` は文字列で保持し、取りうる値はアプリ側で検証する（値の追加でマイグレーションを要さないため）。

ジョブの実行管理（`deep_tracker/jobs/ai_jobs.py`）:

- バックエンド起動時にワーカーを `ai.max_concurrent_jobs`（既定1＝逐次）本起動し、`pending` を作成順に処理する。取得は `UPDATE ... WHERE status='pending'` で行い、二重実行しない。
- 失敗時は `error` に理由を保存し、自動リトライはしない。利用制限エラーは `error` が「利用制限に達しました」で始まり、API の `rate_limited` が true になる（GUIは再試行を促す）。
- 起動時に `running` のまま残ったジョブは `failed`（再起動により中断）として整理する。
- 状態取得API: `GET /api/ai-jobs`（`status` / `kind` / `limit`）、`GET /api/ai-jobs/{id}`。

### 5-3. 記事の重複排除

- `articles` に `UNIQUE (feed_id, guid)` を張り、同一フィード内の二重登録をDBで防ぐ。フィードをまたぐ同一記事は別記事として扱う。
- `guid` はフィードが GUID を持てばその値、無ければ `make_guid()` でフォールバックする。
  1. GUID（JSON Feed の `id`、Atom の `id`、RSS の `guid`）
  2. 記事URLの SHA-256（`url:` 接頭辞）
  3. タイトル+公開日時の SHA-256（`title:` 接頭辞）
- 取り込み側は、既存記事と衝突した場合に無視（`INSERT ... ON CONFLICT DO NOTHING`）する。

### 5-4. 索引

| 索引                              | 用途                                                                           |
| --------------------------------- | ------------------------------------------------------------------------------ |
| `articles(published_at)`          | 新着順の一覧、保存期間による削除                                               |
| `articles(feed_id, published_at)` | フィード別の一覧。`(feed_id, guid)` の一意索引はフィード単位の絞り込みにも効く |
| `articles(is_read, published_at)` | 未読のみの一覧                                                                 |
| `summary_articles(article_id)`    | 記事からサマリへの逆引き                                                       |
| `summaries(period_start)`         | サマリ一覧                                                                     |
| `ai_jobs(status, created_at)`     | 未処理ジョブの取得                                                             |
