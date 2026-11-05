---
name: release-prepare
description: リリースに向けてバージョン番号を更新し、developからmasterへのプルリクエストを作成する
disable-model-invocation: true
---

deep-tracker のリリース準備を行ってください: 新バージョン番号 $ARGUMENTS

このSKILLは、GitHub Releases への tarball 配布（`.github/workflows/release.yml`）の前段作業を補助する。**バージョン番号の更新と develop から master へのプルリクエスト作成までを行い、master へのマージ・タグ付け（`git tag vX.Y.Z` → push）は行わない。** マージ・タグ付けは人間が最終承認した上で別途行う。

以下の手順で進めてください。

1. **バージョン番号の確認**
   - `$ARGUMENTS` がセマンティックバージョン形式（例: `0.2.0`）であることを確認する。`v` プレフィックスは付けない（タグ名に付与する `v` とは別物）
   - `backend/pyproject.toml` の `[project].version`・`frontend/package.json` の `version` の現在値を確認し、指定バージョンが現在値より新しいことを確認する

2. **作業ブランチの作成**
   - `develop` を最新化する（`git fetch origin && git checkout develop && git pull`）
   - `develop` から `release/v$ARGUMENTS` ブランチを作成する（通常の `feature/*` とは異なる、`master` への取り込み専用ブランチ）

3. **バージョン番号の更新**
   - `backend/pyproject.toml` の `[project].version` を `$ARGUMENTS` に更新し、`backend/uv.lock` の `deep-tracker` のバージョンも追従させる（`cd backend && uv lock`）
   - `frontend/package.json` の `version` を更新し、`package-lock.json` のルートバージョンも追従させる（`cd frontend && npm install --package-lock-only`）
   - 他にバージョン番号を参照している箇所がないか確認する（`grep -rn "<旧バージョン>"`。想定はこの2箇所とそのロックファイル）

   **配布物（`dist/` 配下）の最新化確認**（コミット前に行う）
   - 前バージョンタグ以降の変更を洗い出す: `git diff <前バージョンタグ>..HEAD --stat`（タグが無い初回リリースの場合は `dist/` 全体を現行の開発用ファイルと突き合わせる）
   - 対応関係（`CONTRIBUTING.md` の「配布物（dist/）」にも記載）に沿って、`dist/` 側に未反映の変更がないか比較する
     - `config/config.yaml.example` ↔ `dist/config/config.yaml.example`（冒頭コメントと `docs/setup.md` 参照のみ配布用に別記。それ以外の差分は未反映とみなす）
     - `docs/setup.md`・`README.md` ↔ `dist/SETUP.md`（手順・設定項目・前提の乖離がないか）
     - `dist/.env.example` ↔ `scripts/lib.sh` の `load_env`（読み込む変数 `LAN_IP` / `TAILSCALE_IP` と一致しているか）
     - `dist/scripts/migrate.sh`・`_migrate_helper.py` ↔ `backend/migrations/`・`backend/deep_tracker/config/`（スキーマや設定キーの変更に追従できているか。`backend/tests/test_migrate.py` が通ること）
     - `scripts/*.sh`・`scripts/*.plist.example`・`backend/`・`frontend/` は `dist/` に複製を持たず、`release.yml` が組み立て時に直接コピーする（確認不要）
   - `release.yml` の `assemble tarball` が含めるファイルと、`dist/SETUP.md` が案内するパスが実在するかを確認する
   - 未反映の差分は `dist/` 側を修正し、同じ `release/v$ARGUMENTS` ブランチ上でバージョン更新と同一コミットに含める。ステップ4の変更点サマリにも「配布物の更新」を含める
   - 意図的な差分か判断に迷うものは自動修正せず、人間に報告して確認する

4. **コミット**
   - 前バージョンの特定: `git describe --tags --abbrev=0`（タグが1つも無ければ初回リリース扱い）
   - 変更点一覧の取得: `git log --oneline <前バージョンタグ>..HEAD`（初回リリースは省略）。`develop` へのマージは通常 squash merge のため、1コミットがおおむね1PRに対応する
   - 一覧を読み、変更点を短い箇条書きに要約する（一覧をそのまま貼らない）
   - 変更を1つのコミットにする。このメッセージが squash merge で `master` にそのまま刻まれ、`release.yml` がリリースノート本文として本文を再利用する
     - タイトル: `v$ARGUMENTS リリース`
     - 本文: 前バージョンからの変更点サマリ。例:
       ```
       v0.1.1 からの変更点:

       - 設定ファイルの移行スクリプトを追加
       - サマリ画面の表示崩れを修正
       ```
       初回リリースの場合は本文に「初回リリース」とだけ記載する
   - コミットは1つに保つ

5. **プルリクエスト作成**
   - `develop` ではなく、**`master` 宛**のPRを作る（`gh pr create --base master --head release/v$ARGUMENTS`）
   - PRタイトルはコミットタイトルと同じ `v$ARGUMENTS リリース`。レビュー対応で追加コミットが積まれた場合は、マージ前にコミットを1つにまとめ直すか、squash merge 時にステップ4のメッセージ内容になるよう調整する
   - PR本文には、更新したバージョン番号と、マージ後の手順を明記する。両方含めること
     1. `git tag v$ARGUMENTS` → `git push origin v$ARGUMENTS` でリリースワークフローが起動すること
     2. タグ付け後、`master` を `develop` にマージして履歴を統合すること（`git checkout develop && git pull && git merge master && git push origin develop`。ただし `develop` は直接pushできないため、PR経由で取り込む）。`backend/pyproject.toml`・`backend/uv.lock`・`frontend/package.json`・`package-lock.json` のバージョンでコンフリクトした場合は `master` 側（今回のバージョン）を採用する。省略すると両ブランチの履歴が共有祖先を失い、次回以降のリリースPRで想定外の差分が出たり、ステップ4の前バージョン特定が誤動作したりする
   - 通常の `feature/*` → `develop` とは異なるリリース専用PRのため、対応するissueがなければ `Closes #` は不要

6. **完了報告**
   - 作成したPRのURLを表示する
   - **master へのマージ、タグ付け、タグ付け後の `master` → `develop` マージは人間が行うため、ここでは絶対に実施しない**旨を明記する

## 前提・注意点

- `master` と `develop` への直接コミットは禁止（`CLAUDE.md`）。本SKILLも例外なく PR 経由でのみ `master` を変更する
- タグは `master` 上のマージコミットに対して人間が打つ（マージ前のブランチにタグを打たない）
- 同一バージョンへのリリース再実行は `release.yml` 側が非対応（既存タグへの `gh release create` は失敗する）。誤ったバージョンで実行した場合はPRをマージせずクローズし、正しいバージョンでやり直す
- `master` と `develop` の履歴が共有祖先を失っていると、`develop` から切ったブランチのPRに実在しない大量の差分が出ることがある。その場合は `release/v$ARGUMENTS` を `master` の先頭から作り直すことを検討し、必ず人間に報告する
- `release.yml` はタグが指す `master` コミットの本文をリリースノートに使う（`--generate-notes` は使わない）。ステップ4のコミット本文の質がそのままリリースページの品質になる
