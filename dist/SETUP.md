# Deep Tracker セットアップ手順

このtarballには、Deep Tracker をビルド済みの状態で動かすために必要なファイル一式が含まれています（frontend は Next.js のビルド済み出力のため、npm やビルドは不要です）。開発者向けの情報（ソースの全体・テスト・設計ドキュメント等）は含まれていません。開発に参加する場合は [GitHubリポジトリ](https://github.com/nosetech/deep-tracker) を参照してください。

## 前提

以下はOS側にあらかじめインストールしておきます（このtarballには含まれません）。

- macOS（定期実行・常時起動に launchd を使います。動作確認は macOS のみ）
- Python 3.11 以上、[uv](https://docs.astral.sh/uv/)
- Node.js 20 以降
- [Claude Code CLI](https://docs.claude.com/en/docs/claude-code)（サブスクリプションでログイン済みであること。サマリの生成に使います）

## 1. 展開

```bash
tar xzf deep-tracker-<version>.tar.gz
cd deep-tracker-<version>
shasum -a 256 -c ../deep-tracker-<version>.tar.gz.sha256   # 任意: 展開前に tarball と同じ場所で確認
(cd backend && uv sync --frozen)                            # backend の依存をインストール
```

## 2. 設定

```bash
cp config/config.yaml.example config/config.yaml
```

`config/config.yaml` を編集します。**画面に設定画面はありません**。変更の反映にはアプリの再起動が必要です。各項目の意味は `config.yaml.example` のコメントを参照してください。

| 項目 | 内容 |
|---|---|
| `instance` | launchd ジョブ名・PIDファイル名に使われる識別子。複数バージョンを並行稼働する場合は展開先ごとに別の値にする |
| `backend.port` / `frontend.port` | 待ち受けポート。並行稼働では展開先ごとに分ける |
| `db.path` | SQLite DB のパス（相対パスは展開先ルート基準）。並行稼働では展開先ごとに分ける |
| `summary.interval` | サマリの周期（`daily` / `weekly` / `monthly`） |
| `slack.enabled` / `slack.webhook_url` | Slack通知（無効でも動作します） |
| `ai.command` | Claude Code CLI の絶対パス（`which claude`）。launchd 経由では PATH が限られるため推奨 |

### 画面の公開先IP（`.env`）

既定では画面は `127.0.0.1`（このマシンからのみ）で待ち受けます。別の端末から見る場合は `.env` を作成します。

```bash
cp .env.example .env
```

| 変数 | 用途 |
|---|---|
| `LAN_IP` | 同一LAN内の別端末からアクセスする場合に、自機のLAN IPを指定する |
| `TAILSCALE_IP` | Tailscale 経由でアクセスする場合に、自機の Tailscale IP（`tailscale ip -4`）を指定する |

- `LAN_IP` と `TAILSCALE_IP` は同時に指定できません（起動時にエラーになります）。どちらも未指定なら `127.0.0.1` です。`0.0.0.0` では待ち受けません
- シェルで同名の環境変数を指定した場合は、そちらが優先されます
- backend は常に `127.0.0.1` で待ち受けます（ブラウザは frontend の `/api/*` 経由でアクセスします）

> **リスク**: 本アプリに認証はありません。`LAN_IP` / `TAILSCALE_IP` を指定すると、そのネットワーク（LAN / tailnet）に接続できる全員が購読フィードの閲覧・追加・削除などを行えます。信頼できるネットワーク内に限り、インターネットへ直接公開（ポート開放など）しないでください。

## 3. 起動

手動で起動する場合:

```bash
scripts/start.sh   # backend と frontend をバックグラウンドで起動
scripts/stop.sh    # 停止
```

ブラウザで `http://127.0.0.1:3700`（`LAN_IP` / `TAILSCALE_IP` を指定した場合はそのIP、ポートは `frontend.port`）を開きます。ログは `logs/{backend,backend.stderr,frontend}.log` です（JST 0時に日次ローテーションし、`config.yaml` の `logging.retention_days`（既定7日）を超えた世代は自動削除されます）。

Mac の再起動やクラッシュで止まらないようにする場合は、launchd の LaunchAgent に登録します（ログイン時に起動し、落ちたら再起動します）。

```bash
scripts/service.sh install   # 登録して起動（再実行で更新）
scripts/service.sh status    # 状態
scripts/service.sh restart   # config.yaml / .env の変更を反映
scripts/service.sh stop      # 停止（plist は残る）
scripts/service.sh uninstall # 登録を解除
```

- `LAN_IP` / `TAILSCALE_IP` は `install` 時の値が plist に固定されます。変えるときは `.env` を直して `install` を再実行してください
- `scripts/start.sh` と `service.sh` は同時には使えません（二重起動を防ぐため、片方が動いていると拒否されます）

## 4. 定期実行ジョブの登録

フィードの定期取得とサマリの定期生成は、launchd のジョブとして登録します。

```bash
scripts/fetch-job.sh install     # フィード取得（既定: 300秒ごとに、取得間隔を過ぎたフィードのみ取得）
scripts/summary-job.sh install   # サマリ生成（既定: 3600秒ごとに起動し、期間が終わっていれば生成）
```

操作は `status` / `start`（今すぐ1回）/ `stop` / `run`（ターミナルで1回実行）/ `uninstall`。ログは `logs/fetch.log` と `logs/summary.log` です（同じく日次ローテーションします）。Slack通知を有効にしている場合、サマリの生成完了（失敗も）が通知されます。

## 5. 旧バージョンからの更新（マイグレーション）

新バージョンのtarballを**別のディレクトリ**に展開し、旧バージョンの状態を引き継ぎます。

```bash
cd deep-tracker-<新version>
(cd backend && uv sync --frozen)
./scripts/migrate.sh <旧バージョンの展開先> [--with-logs] [--force]
```

| 引き継ぐもの | 扱い |
|---|---|
| `config/config.yaml` | YAMLとして検証してコピーする。新しい版で追加・削除された設定キーがあればヒントとして表示する |
| DB（`db.path`） | SQLite のオンラインバックアップでコピーする（旧バージョンの稼働中でも安全）。新バージョンが対応しない新しいスキーマなら停止する。古いスキーマは新バージョンの起動時に自動で引き上げられる |
| `.env` | `LAN_IP` / `TAILSCALE_IP` を引き継ぐ。ネットワークに依存するため、移行後に値を確認する |
| `logs/` | `--with-logs` 指定時のみ |

- 新バージョン側に同名のファイルがあるときは既定でスキップします。`--force` で `<file>.bak-<日時>` に退避して上書きします。何度実行しても安全です
- 旧バージョンの展開先は変更・削除しません。動作確認が済むまで残しておけます
- **並行稼働する場合**は、移行した `config/config.yaml` の `instance` / `backend.port` / `frontend.port` / `db.path` を新バージョン側で変更してください（自動では書き換えません）。変更しないと旧バージョンとポート・DB・launchd ジョブ名が衝突します
- 移行後、新バージョンで `scripts/fetch-job.sh install` / `scripts/summary-job.sh install` / `scripts/service.sh install` を実行します。ジョブ名に `instance` が含まれるため、`instance` が旧バージョンと同じ場合は旧バージョンのジョブを上書きします。旧バージョンを止める場合は、旧展開先で `scripts/service.sh uninstall` / `scripts/fetch-job.sh uninstall` / `scripts/summary-job.sh uninstall` を実行します

## ディレクトリ構成

| パス | 内容 |
|---|---|
| `backend/` | Python（FastAPI）のソース、`uv.lock`、DBマイグレーション |
| `frontend/` | Next.js のビルド済み出力（`node server.js` で起動） |
| `config/` | `config.yaml.example`（実ファイル `config.yaml` は利用者が作成） |
| `scripts/` | 起動・停止、常時起動、定期ジョブ、マイグレーションのスクリプト |
| `.env.example` | 画面の公開先IPのサンプル |
| `VERSION` | このtarballのバージョン |
