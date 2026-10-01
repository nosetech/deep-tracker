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
- 起動: `npm run dev`（`:3700`。`/api/*` は `BACKEND_URL` へ中継）
- lint: `npm run lint` / `npm run format:check`（整形は `npm run format`）
- 型チェック: `npm run typecheck`
- ビルド: `npm run build`（`NODE_ENV` が `development` だと失敗する場合は `env -u NODE_ENV npm run build`）

## 画面デザインの実装ルール

画面実装は、Claude Designで作成された以下のデザインを**正**として忠実に実装すること。レイアウト・配色・コンポーネント構成・インタラクションを独自解釈で変更しない。

- デザイン: https://claude.ai/design/p/122eb4f8-8479-49f5-8e1d-2a1d9d5ed71e?file=Deep+Tracker.dc.html

このデザインは `docs/design-prompt-ui.md` と `docs/design-prompt-ui-diff-remove-settings.md` のプロンプトを元に作成されたもの。デザインと `docs/` 側の仕様に齟齬がある場合は、実装前にどちらを正とするか確認すること。デザインが更新された場合は、この節のURLも合わせて更新する。

**重要**: 上記URLは `claude.ai` の認証が必要なページであり、`WebFetch` 等では中身を見られない。配色・フォントなどの指定は、このURLの実ソースにしかない。

**実装・レビュー時は必ず `DesignSync` MCPツールでデザインの実ソース（`Deep Tracker.dc.html`）を直接取得し、実際のCSS/JS値（色・余白・border-radius・フォント・アニメーション等）を確認してから実装すること。** `projectId` はURLの `/p/<uuid>` 部分（`122eb4f8-8479-49f5-8e1d-2a1d9d5ed71e`）。

1. `get_project` で `projectId` が読めることを確認する（このプロジェクトは `type: PROJECT_TYPE_PROJECT` で、`list_projects` には出てこない。`get_project`/`list_files`/`get_file` は `projectId` を直接渡せば使える）
2. `list_files` で対象ファイルを確認する（`Deep Tracker.dc.html`、`support.js`）
3. `get_file` で `Deep Tracker.dc.html` を取得する。約88KBあり、出力が大きい場合はファイルに保存されるので、そのファイルから対象コンポーネントの値を検索して読み取る

**ブラウザ操作ツール（`mcp__claude-in-chrome__*`）で上記URLを開き、キャンバス上の要素のクリックや、スクリーンショットの目視でCSS値を推測して実装しないこと。** 数値の取得手段は `DesignSync` のみ。

**`DesignSync` が権限不足等で使えない場合はフォールバックせず、その旨を明記して作業を停止し、人間の確認を仰ぐこと。**

実装後は、ブラウザ操作ツールで完成品とデザインのプレビューを並べて最終的な見た目の一致を確認する（これは値の取得手段ではなく、完成後のセルフレビュー用途）。

### デザインの作成・変更

デザインを新規に作る、または変更する場合は、ブラウザ操作ツール（`mcp__claude-in-chrome__*`）でClaude Designのチャットに指示する。変更した指示プロンプトは `docs/design-prompt-ui-diff-*.md` に記録する。

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
- LAN公開はデフォルトで `127.0.0.1`。LAN公開は設定で有効化する。
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
