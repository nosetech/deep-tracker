# セットアップ手順

## A. 画面の起動とLAN公開

frontend の待ち受けアドレスは環境変数 `LAN_IP` / `TAILSCALE_IP`、ポートは `config/config.yaml` の `frontend.port` で決まる（producer-desk と同じ方式）。
バックエンドは常に `127.0.0.1` で待ち受け、LAN公開の対象にならない（ブラウザは frontend の `/api/*` 中継経由でアクセスする）。

```bash
cd backend && uv sync && cd ..
(cd frontend && npm install)
scripts/start.sh               # backend と frontend をバックグラウンドで起動
scripts/stop.sh                # 両方を停止（未起動でもエラーにならない）
```

- `scripts/start.sh` は frontend が未ビルドなら自動で `npm run build` する。`/api/*` の中継先（`BACKEND_URL`）は実行時に読まれるため、`backend.port` を変えてもビルドし直しは不要開発サーバで起動するには `FRONTEND_MODE=dev scripts/start.sh`
- PID は `logs/deep-tracker.<instance>.{backend,frontend}.pid`、ログは `logs/{backend,frontend}.log` に出る。`instance` ごとにPIDが分かれるため、展開先を分ければ並行稼働できる
- 二重起動は拒否される。異常終了でPIDファイルが残っていても、次の `scripts/start.sh` は起動できる

| 設定 | 動作 |
|---|---|
| 環境変数 | 動作 |
|---|---|
| 未指定（既定） | `127.0.0.1` で待ち受け、このマシンからのみ閲覧できる |
| `LAN_IP=<このマシンのLAN IP>` | そのIPで待ち受け、同じネットワーク内の別デバイスから `http://<IP>:<frontend.port>` で閲覧できる |
| `TAILSCALE_IP=<このマシンのtailnet IP>` | そのIPで待ち受け、tailnet内の別デバイスから閲覧できる |
| 両方を指定 | エラーで起動しない |

`0.0.0.0`（全インターフェース）では待ち受けない。

LAN公開する手順:

1. `scripts/stop.sh` で停止する
2. `LAN_IP=192.168.0.10 scripts/start.sh`（tailnet なら `TAILSCALE_IP=100.x.y.z scripts/start.sh`）で起動する。以前の `frontend.host` が `config.yaml` に残っているとエラーになるため、削除する
3. 別デバイスのブラウザから `http://<このマシンのIP>:3700` を開く。開けない場合は macOS のファイアウォール設定を確認する

> **リスク**: 本アプリに認証はない。`LAN_IP` / `TAILSCALE_IP` を指定すると、同じネットワーク（tailnet）に接続できる全員が購読フィードの閲覧・追加・削除、既読操作などを行える。
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

# サマリの定期実行

サマリを launchd で定期的に自動生成する手順。前提は「定期取得バッチ」と同じ（`config/config.yaml` を用意済みであること）。

## 1. 周期の設定

`config/config.yaml` の `summary.interval` で決める。既定は `weekly`。

| 値 | 生成される期間（ローカル時刻） | 生成の時期（最速） |
|---|---|---|
| `daily` | 前日 0:00〜当日 0:00 | 毎日 0:00 以降 |
| `weekly`（既定） | 前週の月曜 0:00〜今週の月曜 0:00（月曜〜日曜） | 毎週月曜 0:00 以降 |
| `monthly` | 前月 1日 0:00〜今月 1日 0:00 | 毎月1日 0:00 以降 |

実行時刻の指定はできない。期間の区切り（0:00）以降の最初のバッチ起動で生成される。サマリ画面のサイドバー下部には、この周期と次回実行予定（次の区切り）が表示される。

変更後は次回のバッチ起動から反映される（バッチは毎回設定を読み直す）。

## 2. 登録

```bash
scripts/summary-job.sh install
```

- ジョブ名は `com.nosetech.deep-tracker.<instance>.summary`（instance ごとに別ジョブ）
- launchd は既定で3600秒ごとに起動する（`SUMMARY_TICK_SECONDS=1800 scripts/summary-job.sh install` で変更可）。
  期間が終わった後の最初の起動で生成される。生成済みの期間は何もしない
- 操作（`uninstall` / `start` / `stop` / `status` / `run`）は `scripts/fetch-job.sh` と同じ
- launchd 経由のジョブは `PATH` が `/usr/bin:/bin:/usr/sbin:/sbin` に限られ、`claude` が見つからない。`config/config.yaml` の `ai.command` に `which claude` の絶対パスを指定する（例: `command: /Users/<user>/.local/bin/claude`）

## 3. 動作

- 同じ期間のサマリが既にある場合（失敗・実行中を含む）は二重に生成しない
- 対象期間に記事が無い場合は生成しない
- 利用制限などでAI処理が失敗した場合は、`status=failed` のサマリを記録して終了する。自動リトライはせず、次の期間まで待つ
- 成功時は期間・トピック見出し・GUIへのリンクがSlack通知される（`slack.enabled: true` の場合）。失敗も通知されるが、`slack.notify_on_failure: false` で止められる
- 通知内のリンクは `slack.base_url` があればそれを、なければ `LAN_IP` / `TAILSCALE_IP`（未指定なら `localhost`）と `frontend.port` から作る。launchd 経由のジョブには `LAN_IP` / `TAILSCALE_IP` が渡らないため、LAN公開時は `base_url` にアドレスを指定する
- 多重起動は `<db.path の親>/summary.lock` で防ぐ

ログは `logs/summary.log`（1MBで5世代ローテーション）。launchd が受け取った出力は `logs/summary.launchd.log`。
