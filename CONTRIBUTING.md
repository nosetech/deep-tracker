# CONTRIBUTING

`deep-tracker` への変更の進め方をまとめる。設計上の前提は `CLAUDE.md` と `docs/requirements.md` を参照すること。

## 開発環境

- Python 3.11 以上、[uv](https://docs.astral.sh/uv/)
- Node.js（npm 同梱）

```sh
cp config/config.yaml.example config/config.yaml   # 実ファイルは .gitignore 対象
(cd backend && uv sync)
(cd frontend && npm install)
```

## ディレクトリ構成

| パス | 内容 |
|---|---|
| `backend/` | Python（FastAPI）のバックエンド |
| `frontend/` | Next.js / TypeScript のフロントエンド |
| `config/` | 設定ファイル（`config.yaml.example` のみコミット） |
| `scripts/` | backend・frontendの起動/停止、常時起動（`service.sh`）、launchdジョブ（フィード取得・サマリ生成）の管理スクリプト |
| `dist/` | 配布tarball専用のファイル（下記「配布物（dist/）とリリース」） |
| `docs/` | 要件・技術選定・セットアップ手順・デザインプロンプト |

## 開発時の起動

ターミナルを2つ使う。

```sh
# backend（http://127.0.0.1:8700）
cd backend && uv run python -m deep_tracker.main

# frontend（http://localhost:3700。/api/* は backend へ中継される）
cd frontend && npm run dev
```

動作確認: `curl http://localhost:3700/api/health` が `{"status":"ok"}` を返せば、frontend から backend への中継まで通っている。
バックエンドの接続先を変える場合は、frontend の環境変数 `BACKEND_URL`（既定 `http://127.0.0.1:8700`。実行時に読まれる）を指定する。
backend と frontend をまとめてバックグラウンドで起動・停止するには `scripts/start.sh` / `scripts/stop.sh`（開発サーバで起動するには `FRONTEND_MODE=dev scripts/start.sh`。LAN公開は `LAN_IP` / `TAILSCALE_IP` で行う。`docs/setup.md`）。

## 動作確認用インスタンス

画面・APIの動作確認は、運用インスタンスと分離した動作確認用インスタンスで行う。

```sh
scripts/dev-instance.sh start   # 起動（/api/health が ok になるまで待つ）
scripts/dev-instance.sh status  # 状態・URL・ログの場所
scripts/dev-instance.sh stop    # 停止
```

- ポートは 18000 番台の空きから自動採番する（`DEV_BACKEND_PORT` / `DEV_FRONTEND_PORT` で指定も可。運用の既定ポート 8700/3700 や使用中のポートは拒否）。
- 設定・DB・ログ・PID記録は `.dev-run/` に生成する（`config/config.yaml` と運用DBは使わない）。
- `DEEP_TRACKER_DEV_MODE=1` で起動するため、Slack通知とClaude Code CLI呼び出し（AIジョブ）は実行されない。RSS取得と一覧表示は動く。
- `stop` は記録（PID・プロセスグループ・起動時の目印）と一致する場合だけ止める。不一致なら何もせずエラーにする。
- 前提: `backend` で `uv sync`、`frontend` で `npm install` を済ませておく。
- `pkill` / `killall` やポート検索による kill はしない（運用インスタンスや他のworktreeを巻き込むため）。

## Lint・テスト・ビルド

```sh
# backend
cd backend
uv run ruff check . && uv run ruff format --check .   # 整形は uv run ruff format .
uv run pytest

# frontend
cd frontend
npm run lint
npm run format:check                                  # 整形は npm run format
npm run typecheck
npm run build
```

> `NODE_ENV` を `development` 以外にしたシェルで `npm run build` を行うと失敗することがある。その場合は `env -u NODE_ENV npm run build` で実行する。

## 画面実装のルール

画面は Claude Design のデザインを**正**として実装し、独自解釈でレイアウト・配色・インタラクションを変えない。デザインの参照方法と注意点は `CLAUDE.md` の「画面デザインの実装ルール」に従うこと。

## バージョンの更新

画面に表示されるバージョンは `backend/pyproject.toml` の `version` が正。リリース時はここを更新し、`frontend/package.json` の `version` も同じ値に揃える（画面表示には使わない）。設定ファイルの `instance` は並行稼働の識別子で、表示されるバージョンとは別物。

## 配布物（dist/）とリリース

リリースは GitHub Releases の tarball（`deep-tracker-<version>.tar.gz` と `.sha256`）で配布する。`v*.*.*` タグの push で `.github/workflows/release.yml` が、バージョン一致の検証 → backend / frontend の lint・テスト・ビルド → tarball 作成 → Release 公開まで行う。frontend は Next.js の standalone 出力をビルド済みで同梱し、利用者側の npm / ビルドは不要。

### dist/ と開発用ファイルの対応

開発用と配布用で内容が異なるものだけを `dist/` に置く。共通実体のものは `dist/` に複製せず、ワークフローが組み立て時に直接コピーする（二重管理を避ける）。

| 配布物の中 | 元 | 備考 |
|---|---|---|
| `SETUP.md` | `dist/SETUP.md` | 配布専用。`docs/setup.md` / `README.md` の手順と乖離させない |
| `.env.example` | `dist/.env.example` | frontend の公開先IP（`LAN_IP` / `TAILSCALE_IP`）。読み込みは `scripts/lib.sh` の `load_env` |
| `config/config.yaml.example` | `dist/config/config.yaml.example` | `config/config.yaml.example` と冒頭コメント・参照先以外は同じにする |
| `scripts/migrate.sh`, `scripts/_migrate_helper.py` | `dist/scripts/` | 旧展開先からの引き継ぎ。テストは `backend/tests/test_migrate.py` |
| `scripts/*.sh`, `scripts/*.plist.example` | `scripts/` | 共通実体。`dev-instance.sh` は含めない。`lib.sh` の `is_standalone`（`frontend/server.js` の有無）で配布版の起動方法に切り替わる |
| `backend/` | `backend/` | ソース + `pyproject.toml` / `uv.lock` / `alembic.ini` / `migrations`（テストは含めない） |
| `frontend/` | `frontend/` | `next build` の standalone 出力に `.next/static` と `public/` を加えたもの |

### リリース手順

1. `/release-prepare <version>`（`.claude/skills/release-prepare`）で、バージョン更新・`dist/` の最新化確認・`v<version> リリース` コミットの作成・`master` 宛PRの作成までを行う
2. PRをレビューし、`master` にマージする（squash merge。コミット本文がリリースノートになる）
3. `master` 上で `git tag v<version>` → `git push origin v<version>`（リリースワークフローが起動する）
4. `master` を `develop` にマージして履歴を統合する（`develop` は直接pushできないためPR経由）

バージョンの正は `backend/pyproject.toml`。`frontend/package.json` と一致していないと `release.yml` が失敗する。

## ブランチ運用

```
master（安定版） ← develop（結合） ← feature/*（作業ブランチ）
```

- `master` と `develop` には**直接コミット・pushしない**。変更は必ずPRで取り込む。
- 作業ブランチは `develop` から `feature/<内容>` の名前で切る。
- PRの向き先は `develop`。`master` への反映は、`develop` から `master` へのPRで行う。

```bash
git switch develop
git pull
git switch -c feature/<内容>
```

## コミットメッセージ

`<type>: <変更内容の要約>` の形式で、日本語で書く。

| type | 用途 |
| --- | --- |
| `feat` | 機能の追加 |
| `fix` | バグ修正 |
| `docs` | ドキュメントのみの変更 |
| `refactor` | 挙動を変えないコードの整理 |
| `test` | テストの追加・修正 |
| `chore` | ビルド・設定・依存関係などの雑務 |

例: `docs: CONTRIBUTINGとPRテンプレートを追加`

## プルリクエスト

- `.github/pull_request_template.md` のテンプレートに沿って記載する。
- 対応するissueがある場合、本文に `Closes #<issue番号>` を**独立した1行**として書く（前後は空行で区切る）。
  - 正: `Closes #12`
  - 誤: `Closes #12で対応` のように、番号の直後に日本語などを続けると、GitHubがissue参照として認識せず自動クローズされない。
  - 誤: 「issue #12 で報告された…」のような書き方。
- RSSに関するテストでは、最低限 `https://aws.amazon.com/jp/about-aws/whats-new/recent/feed/` を使う。

## ブランチ保護

`master`・`develop` には、GitHubのブランチ保護で次を設定している。

- PR必須（直接push禁止）
- 管理者にも適用（例外なし）
- レビュー承認は必須にしない（利用者が1名のため）
- force pushとブランチ削除を禁止
