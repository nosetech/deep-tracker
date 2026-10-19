# セットアップ手順

## A. 画面の起動とLAN公開

frontend の待ち受けは `config/config.yaml` の `frontend.host` / `frontend.port` で決まる。
バックエンドは常に `127.0.0.1` で待ち受け、LAN公開の対象にならない（ブラウザは frontend の `/api/*` 中継経由でアクセスする）。

```bash
cd backend && uv sync && cd ..
(cd frontend && npm install && env -u NODE_ENV npm run build)
scripts/frontend.sh start      # 開発時は scripts/frontend.sh dev
```

| 設定 | 動作 |
|---|---|
| `frontend.host: 127.0.0.1`（既定） | このマシンからのみ閲覧できる |
| `frontend.host: 0.0.0.0` | 同じネットワーク内の別デバイスから `http://<このマシンのIP>:<frontend.port>` で閲覧できる |

LAN公開する手順:

1. `config/config.yaml` の `frontend.host` を `0.0.0.0` にする
2. `scripts/frontend.sh` を再起動する（設定はホットリロードされない）
3. 別デバイスのブラウザから `http://<このマシンのIP>:3700` を開く。開けない場合は macOS のファイアウォール設定を確認する

> **リスク**: 本アプリに認証はない。`0.0.0.0` にすると、同じネットワークに接続できる全員が購読フィードの閲覧・追加・削除、既読操作などを行える。
> 自宅などの信頼できるネットワーク内に限り、外出時は VPN 経由でアクセスすること。インターネットへ直接公開（ポート開放など）してはならない。

# 定期取得バッチ

購読フィードを launchd で定期的に自動取得する手順。対象は macOS（per-user LaunchAgent）。

## 1. 前提

```bash
cd backend && uv sync
cp config/config.yaml.example config/config.yaml   # 展開先ルートで実行。必要に応じて編集
```

- `instance`: launchd ジョブ名に使われる。バージョンを並行稼働する場合は展開先ごとに別の値にする
- `db.path`: 展開先ごとに別のファイルにする
- `feed.fetch_interval_minutes`: フィードの既定の取得間隔（分）。フィード個別に指定した値があればそちらが優先される

## 2. 登録

```bash
scripts/fetch-job.sh install
```

- ジョブ名は `com.nosetech.deep-tracker.<instance>.fetch`。plist は `~/Library/LaunchAgents/` に生成される
- launchd は既定で300秒ごとにバッチを起動する（`FETCH_TICK_SECONDS=600 scripts/fetch-job.sh install` で変更可）。
  起動のたびに、取得間隔を過ぎた有効フィードだけを取得する。取得間隔より短い値にすること
- 設定ファイルを変更した場合は、次回のバッチ起動から反映される（バッチは毎回設定を読み直す）。
  `instance` を変えた場合は、旧 instance で `uninstall` してから `install` し直す

## 3. 操作

| コマンド | 内容 |
|---|---|
| `scripts/fetch-job.sh status` | 登録状況を表示する |
| `scripts/fetch-job.sh start` | 今すぐ1回実行する（取得間隔を過ぎたフィードのみ対象） |
| `scripts/fetch-job.sh stop` | 実行中のバッチを停止する（定期実行の登録は残る） |
| `scripts/fetch-job.sh run` | launchd を介さず、ターミナルで1回実行する（動作確認用） |
| `scripts/fetch-job.sh uninstall` | 登録を解除する |

## 4. 複数バージョンの並行稼働

展開先ディレクトリごとに `config/config.yaml` の `instance` と `db.path`・ポートを分け、それぞれの展開先で
`scripts/fetch-job.sh install` を実行する。ジョブ名に `instance` が含まれるため、別ジョブとして登録される。
多重起動防止のロックファイルは DB と同じディレクトリ（`<db.path の親>/fetch.lock`）に置かれ、
DBを分けていれば互いに干渉しない。

## 5. 多重起動の防止

バッチは起動時に排他ロックを取り、別のバッチが実行中ならスキップして正常終了する（ログに記録される）。
ロックはOSが管理するため、プロセスが異常終了しても残骸で止まることはない。

## 6. ログ

| ファイル | 内容 |
|---|---|
| `logs/fetch.log` | バッチの実行結果。1回ごとに「有効・対象・新規記事・失敗」の件数と、失敗したフィードのURL・原因を記録する。1MBで5世代までローテーションする |
| `logs/fetch.launchd.log` | ログ設定前のクラッシュなど、launchd が受け取った標準出力・標準エラー |

```bash
tail -f logs/fetch.log
```
