# Deep Tracker

RSSリーダー + AIによる要約システム。購読しているフィードの記事をまとめて読み、AI（Claude Code CLI）が期間ごとのサマリを作る。

利用者は1名、同一LAN内（外出時はVPN）での利用を想定している。認証はない。

## 主な機能

- **購読フィードの管理**: RSSフィードの登録・削除、取得間隔の個別設定、有効/無効の切り替え
- **記事の閲覧**: 記事一覧、キーワード検索（タイトル・本文）、記事単位の既読/未読管理
- **サマリ**: 一定期間の記事をAIが要約する。既定は週次で、周期は設定で変えられる。定期実行のほか、画面から今すぐ生成もできる
- **Slack通知**: サマリの生成完了（失敗も）をSlackに通知する（任意）

要件と開発計画は [docs/requirements.md](docs/requirements.md)、技術選定は [docs/architecture.md](docs/architecture.md) を参照。

## 前提

- macOS（定期実行にlaunchdを使う）
- Python 3.11 以上、[uv](https://docs.astral.sh/uv/)
- Node.js（npm 同梱）
- [Claude Code CLI](https://docs.claude.com/en/docs/claude-code)（サブスクリプションでログイン済みであること。サマリの生成に使う）

## インストールと初期設定

```sh
cp config/config.yaml.example config/config.yaml
(cd backend && uv sync)
(cd frontend && npm install && env -u NODE_ENV npm run build)
```

設定は `config/config.yaml` を編集して行う。**画面に設定画面はない**。変更を反映するにはアプリを再起動する（定期実行のバッチは次回の起動から反映される）。
各項目の意味は `config/config.yaml.example` のコメントを参照。主な項目は次のとおり。

| 項目 | 内容 |
|---|---|
| `summary.interval` | サマリの周期（`daily` / `weekly` / `monthly`） |
| `feed.fetch_interval_minutes` | フィード取得の既定間隔（分） |
| `retention.days` | 記事の保存期間（日） |
| `slack.enabled` / `slack.webhook_url` | Slack通知の有効化とWebhook URL |
| `frontend.host` / `frontend.port` | 画面の待ち受け。既定は `127.0.0.1:3700` |

## 起動

ターミナルを2つ使う。

```sh
# backend（127.0.0.1:8700）
cd backend && uv run python -m deep_tracker.main

# frontend（config.yaml の frontend.host / frontend.port で待ち受ける）
scripts/frontend.sh start
```

ブラウザで <http://localhost:3700> を開く（`frontend.port` を変えた場合はそのポート）。

LAN内の別デバイスから開く場合は `frontend.host` を `0.0.0.0` にする。認証がないため、リスクと手順を [docs/setup.md](docs/setup.md) で確認すること。

## 使い方

1. **フィードを登録する**: 左のメニューの「購読フィード」でRSSのURLを追加する。登録後すぐ取得され、以降は設定した間隔で取得される
2. **記事を読む**: 「記事一覧」で記事を閲覧する。フィードや未読のみで絞り込め、キーワードで検索できる。記事ごとに既読/未読を切り替えられ、フィード単位でまとめて既読にもできる
3. **サマリを見る**: 「サマリ」で最新のサマリと過去のサマリを確認する。「今すぐサマリを生成」で任意のタイミングで生成もできる
4. **Slackに通知する**: `slack.enabled: true` と `slack.webhook_url` を設定すると、サマリの生成結果が通知される。通知内のリンクは `slack.base_url`（未指定なら `frontend.host` / `frontend.port`）から作られる

### 定期実行

フィード取得とサマリ生成は、launchdに登録すると自動で実行される。

```sh
scripts/fetch-job.sh install     # フィードの定期取得
scripts/summary-job.sh install   # サマリの定期生成
```

登録・操作・ログの詳細は [docs/setup.md](docs/setup.md) を参照。

## 開発に参加する

開発環境、コマンド、ブランチ運用などは [CONTRIBUTING.md](CONTRIBUTING.md) を参照。
