# CONTRIBUTING

`deep-tracker` への変更の進め方をまとめる。設計上の前提は `CLAUDE.md` と `docs/requirements.md` を参照すること。

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

`master`・`develop` は、直接pushを禁止しPRを必須とする運用とする。リポジトリ設定（Branch protection / Rulesets）での強制は管理者権限が必要なため、設定内容はユーザーの確認後に実施する。
