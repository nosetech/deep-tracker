# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## リポジトリの現状

`deep-tracker` は、RSSリーダー + AIによる要約システム。現在フェーズ0（基盤）で、`backend/` と `frontend/` の雛形がある。要件と開発計画は `docs/requirements.md`、技術選定は `docs/architecture.md` を読むこと。

## ビルド・lint・テストのコマンド

backend（`backend/` で実行。uv + ruff + pytest）:

- セットアップ: `uv sync`
- 起動: `uv run python -m deep_tracker.main`（`127.0.0.1:8700`）
- lint: `uv run ruff check .` / `uv run ruff format --check .`（整形は `uv run ruff format .`）
- テスト: `uv run pytest`

frontend（`frontend/` で実行。npm）:

- セットアップ: `npm install`
- 起動: `npm run dev`（`:3700`。`/api/*` は実行時の `BACKEND_URL` へ中継）。待ち受けIPは環境変数 `LAN_IP` / `TAILSCALE_IP`（どちらか一方、未指定は `127.0.0.1`）
- テスト: `npm test`（Route Handler の中継）
- lint: `npm run lint` / `npm run format:check`（整形は `npm run format`）
- 型チェック: `npm run typecheck`
- ビルド: `npm run build`（`NODE_ENV` が `development` だと失敗する場合は `env -u NODE_ENV npm run build`）

## 動作確認用インスタンス

画面・APIの動作確認は `scripts/dev-instance.sh start|stop|status` で行う（使い方は `CONTRIBUTING.md`）。運用インスタンスとポート・DB・設定が分離され、Slack通知とClaude Code CLI呼び出しは無効になる。**`pkill` / `killall` やポート検索によるプロセスの kill はしない。** 停止は `scripts/dev-instance.sh stop` のみ。

## 画面デザインの実装ルール

画面実装は、Claudeの Artifacts にあるデザインを**正**として忠実に実装すること（以前の Claude Design からは Artifacts へ移管済み）。レイアウト・配色・コンポーネント構成・インタラクションを独自解釈で変更しない。

- デザイン: https://claude.ai/artifact/7sJw2gTFGjsyT61s99Azzy（一覧は https://claude.ai/artifacts）
- 主なファイル（`project/` 配下。`Artifact` の `list` で実在を確認すること）:
  - `project/Deep Tracker.dc.html`: マスターのデザイン（約129KB。スタイル・状態ロジックもこの1ファイルに含まれる。`.logic.js` に分割された場合は**両方**を読むこと）
  - `project/feature/issue-126-translation.dc.html`: 記事の翻訳表示（#126）の作業用デザイン。マスターを複製して翻訳UIを追加したもの（マスターへのマージは未実施）
  - `project/Deep Tracker Icons.dc.html`: アイコン
  - `project/support.js` / `project/compat.json`: 共通スクリプト・互換設定
  - `index.html`、`artifact-type/` と `SKILL.md` は Artifact の仕組み側のファイルでデザインではない。読まない。

このデザインは `docs/design-prompt-ui.md` と `docs/design-prompt-ui-diff-remove-settings.md` のプロンプトを元に作成されたもの。デザインと `docs/` 側の仕様に齟齬がある場合は、実装前にどちらを正とするか確認すること。デザインが更新された場合は、この節のURL・ファイル一覧も合わせて更新する。デザインを修正する場合は、Claudeのチャットから指示して行う（Artifactのファイルを直接編集しない）。

**重要**: 上記URLは `claude.ai` の認証が必要なページであり、`WebFetch` 等では取得できない。配色・フォントなどの指定は、デザインの実ソースにしかない。

**実装・レビュー時は必ず `Artifact` ツールでデザインの実ソースを直接取得し、実際のCSS/JS値（色・余白・border-radius・フォント・アニメーション等）を確認してから実装すること。** 手順は以下の通り（ブラウザ操作は不要）。

1. `Artifact` の `action: "list"`、`scope: "files"`、`url` に上記URLを指定してファイル一覧を取得し、対象ファイルを確認する
2. `action: "read"`、`url`、`path`（例: `project/Deep Tracker.dc.html`）でファイルを取得する（複数ファイルは `paths` でまとめて取得できる）。取得したファイルはスクラッチパッド配下にローカル保存されるので、そのファイルから対象コンポーネントの値を検索して読み取る
3. **取得結果が途中で欠けていないか必ず確認する。** 欠けていて対象のスタイル定義を取りこぼしている可能性がある場合は、取得できた範囲だけで実装を進めず、その旨を明記して作業を停止し、Claudeのチャットでのファイル分割を人間に依頼すること

`Artifact` ツールの利用には、Claude Code が `claude.ai` アカウントで `/login` 済みであることが必要。`claude -p`（ヘッドレス）では `Artifact` ツールが既定で無効なため、ヘッドレスで画面実装を行う場合は環境変数 `CLAUDE_CODE_ARTIFACT=1` で有効化する。

**ブラウザ操作ツール（`mcp__claude-in-chrome__*`）で上記URLを開き、キャンバス上の要素のクリックや、スクリーンショットの目視でCSS値を推測して実装しないこと。** 数値の取得手段は `Artifact` ツールのみ。

**`Artifact` ツールが使えない場合（未ログイン・ツール無効等）はフォールバックせず、その旨を明記して作業を停止し、人間の確認を仰ぐこと。**

実装後は、ブラウザ操作ツールで完成品とデザインのプレビューを並べて最終的な見た目の一致を確認する（これは値の取得手段ではなく、完成後のセルフレビュー用途）。

### デザインの作成・変更

デザインを新規に作る、または変更する場合は、Claudeのチャットから指示する（Artifactのファイルを直接編集しない）。変更した指示プロンプトは `docs/design-prompt-ui-diff-*.md` に記録する。

## 確定済みの設計判断（変更時は要注意）

以下はユーザーとの対話で確定した前提。ドキュメントやコードを更新する際、矛盾させないこと。

- 利用者は1名のみ。認証は設けない（同一LAN内、外出時はVPN）。
- フロントは Next.js / TypeScript（`frontend/`）、バックは Python（`backend/`）。
- AIは `AIProvider` インターフェースの裏に置き、当面は Claude Code CLI（サブスクリプション）のみ実装する。Codex・APIは将来拡張。実装は `producer-desk`（`/Users/hiroyuki/repo/github.com/nosetech/producer-desk`）の `orchestrator/orchestrator/agent_runner.py` を参考にする。
- Claude Code の利用上限はアプリ側で設けない。制限に達したらエラーを返す。
- 「学習」は、興味情報とフィードバック履歴をプロンプトに含める方式。
- サマリは週次がデフォルトで、周期は設定で変更可能。GUI表示とSlack通知を行う。
- **設定はGUIから変更しない。YAML設定ファイルの編集のみ**で、反映はアプリの再起動。設定画面は設けない。
- 設定ファイルはアプリケーションの展開先に同梱する（producer-desk と同様）。複数バージョンを並行して動かせるようにするため、DBのパスとポートは設定で分ける。`*.yaml.example` をコミットし、実ファイルは `.gitignore` に入れる。
- Slack Webhook URL は設定ファイルから読む。
- 記事の保存期間はデフォルト1年で、設定で変更可能。
- LAN公開はデフォルトで `127.0.0.1`。LAN公開は環境変数 `LAN_IP` / `TAILSCALE_IP`（どちらか一方）で待ち受けIPを指定して有効化する（`0.0.0.0` は使わない）。
- 既読/未読を記事単位で管理する。
- RSSの取得は必ずバックエンド経由（CORS回避）。
- 更新検知（RSSのないサイト）はMVPに含めない。別途開発する。

## テストのルール

RSSのテストでは、最低限 `https://aws.amazon.com/jp/about-aws/whats-new/recent/feed/` を使うこと。

## 開発ワークフロー

- ブランチ運用: `master`（安定版） → `develop`（結合） → `feature/*`（作業ブランチ、`develop` から切る）
- `master` と `develop` には直接コミットしない。変更は必ずPRで `develop` に取り込む。
- GitHub issueに対応する変更は、PR本文に `Closes #<issue番号>` を記載する。
- 回答・ドキュメントは、指定がない限り日本語で書く。
