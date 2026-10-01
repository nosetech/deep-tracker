# producer-desk の Claude Code 呼び出し実装の調査

`AIProvider`（Claude Code CLI 実装）の設計材料として、producer-desk の実装を調べた結果をまとめる。
調査対象は `producer-desk/orchestrator/orchestrator/` の `agent_runner.py`・`usage_store.py`・`slack_notifier.py`・`config.py`。
CLI の挙動は Claude Code 2.1.287 で実機確認した。

## 1. 要点（結論）

- 呼び出しは `claude -p <prompt>` のワンショット起動（`subprocess.Popen`）。
- deep-tracker では `--output-format json`（最終結果が1つのJSON）で足りる。`stream-json` は `--verbose` が必須で、途中経過が不要な用途では過剰。
- 利用制限（サブスクリプション上限）の到達は、終了コード非0 かつ結果JSONの `is_error: true` と `api_error_status: 429` で検出する。解除予定時刻は `result` の自由文（例: `resets 1pm (Asia/Tokyo)`）を正規表現で抜く。
- 権限フラグ `--dangerously-skip-permissions` は不要。ツールを全部無効にする `--tools ""` で足りる。
- 利用制限は「待機」ではなく「失敗として扱い、ジョブを失敗記録して次回周期で再試行」とする（CLAUDE.md の「アプリ側で上限を設けず、制限に達したらエラーを返す」と整合）。

## 2. producer-desk の `claude -p` 呼び出し

`build_claude_command()` が組み立てるコマンド（`agent_runner.py`）:

```
claude -p <message>
  --output-format stream-json --verbose
  --dangerously-skip-permissions
  --chrome
  --append-system-prompt <system_prompt>
  [--model <model>]
  (--resume <session_id> | --session-id <session_id>)
```

| 引数 | producer-desk での目的 | deep-tracker での扱い |
|---|---|---|
| `-p` | 非対話のワンショット実行 | 使う |
| `--output-format stream-json` + `--verbose` | ツール呼び出し単位のNDJSONをログへ逐次書き出す（長時間タスクの監視用）。`-p` で `stream-json` を使うと `--verbose` が必須（無いとエラー終了を実機確認） | 使わない。`json` を使う |
| `--dangerously-skip-permissions` | issue対応でファイル編集・`gh` 実行等を無確認で許可 | 使わない（§4） |
| `--chrome` | `-p` では既定無効のClaude in Chromeを有効化 | 使わない |
| `--append-system-prompt` | ラベル遷移・コメント書式などの運用ルールを毎回明示 | 使える。ただし deep-tracker は既定プロンプトを置き換える `--system-prompt` の方が出力が安定する（§4） |
| `--model` | LiteLLM Proxy 経由のモデル別名指定 | 設定でモデル名を指定可能にする程度 |
| `--session-id` / `--resume` | issue単位でセッションを継続（複数ターン） | 使わない。要約・判定は1回完結で、毎回独立させる（§4） |

その他の実装上の要点:

- 起動は `Popen(command, cwd=worktree, stdout=PIPE, stderr=STDOUT, text=True, bufsize=1, env=...)`。標準エラーを標準出力へ合流させ、1行ずつログへ flush しながら全文を保持する（`_stream_process_output`）。
- 出力は NDJSON 全体から、最後の `"type":"result"` イベントを取り出す（`_parse_result_payload`）。JSON として解釈できない行（stderr 混入）は読み飛ばす。
- 環境変数: `ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN` は子プロセスへ素通しせず除去している（サブスクリプション経路を確実にするため）。deep-tracker でも同様に除去するのが安全。API キー環境変数（`ANTHROPIC_API_KEY`）が残っているとサブスクリプションではなく従量課金になりうるため、これも除去対象に含める。

## 3. 利用制限エラーの検出

### 3-1. 出方

- プロセスは終了コード非0 で終了する。
- 結果イベント（`"type":"result"`）が `is_error: true`、`api_error_status: 429` となり、`result` に人間向け文言が入る。例: `You've hit your session limit · resets 1pm (Asia/Tokyo)`。
- `result` は構造化されておらず、解除予定時刻は自由文に埋まっている。

### 3-2. 検出ロジック（producer-desk 実装）

`usage_store.py`:

```python
_LIMIT_RESET_PATTERN = re.compile(r"resets?\s+.+$", re.IGNORECASE)

def parse_limit_reset_text(message: str) -> str | None:
    match = _LIMIT_RESET_PATTERN.search(message)
    return match.group(0).strip() if match else None
```

`agent_runner.py` の `_classify_run_error()`:

- `is_error` と `api_error_status` と `result` を取り出す。
- `is_error and api_error_status == 429 and result` のとき、`parse_limit_reset_text(result) or result` を `limit_reset_text` とする（パース失敗時は生文字列を保持するフォールバック）。

### 3-3. 待機は実装されていない

producer-desk には「リミット解除まで待機して再開する」実装は**無い**。到達時は以下のみ:

- 異常終了として issue にコメント（「API利用リミットに達したため停止しました（解除予定時刻）」）を投稿し、`needs-human-decision` へ遷移する。
- 利用量記録（SQLite）に `is_error` / `api_error_status` / `limit_reset_text` を残す。
- 429 でも `result` が空で情報が得られなければ、終了コード・ログパス付きの通常の異常終了メッセージにフォールバックする。

issue 本文の「検出・待機」のうち「待機」は存在しないため、deep-tracker では §5 の方針を採る。

### 3-4. 注意点

- 429 の判定は `api_error_status` を第一とする。文言（`limit` 等）の部分一致だけに頼ると誤検出・取りこぼしが出る。
- `result` の文言は CLI のバージョンで変わりうる。解除時刻の抽出は「失敗しても生文字列を保持」して機能を落とさない設計にする。
- 5時間枠・週間上限に対する消費率(%)は `-p` 実行の結果からは取得できない（producer-desk の issue #60 で確認済み）。deep-tracker でも消費率は扱わない。

## 4. deep-tracker 向けの起動引数

用途は「ツール不要の要約・判定」。

```
claude -p <prompt>
  --output-format json
  --tools ""
  --no-session-persistence
  --system-prompt <instruction>
  [--model <model>]
```

実機確認（Claude Code 2.1.287）: `claude -p "1+1は?数字のみ" --output-format json --tools "" --no-session-persistence --system-prompt "簡潔に答える"` は終了コード0で、次の形のJSONを1つ返した（抜粋）。

```json
{"type":"result","subtype":"success","is_error":false,"api_error_status":null,
 "result":"2","session_id":"...","total_cost_usd":0.04439,
 "usage":{"input_tokens":2,"output_tokens":3,...},
 "modelUsage":{"claude-sonnet-5-5":{...}}}
```

| 引数 | 理由 |
|---|---|
| `-p` | 非対話のワンショット |
| `--output-format json` | 結果が1つのJSON。`result`（本文）・`is_error`・`api_error_status`・`usage` を1回のパースで取れる。`stream-json` は不要（`--verbose` 必須でNDJSON処理が要る） |
| `--tools ""` | 組み込みツールを全て無効化。要約・判定はテキスト入出力のみで、ファイル/シェル/ネットワークの権限が不要になる。**権限フラグ（`--dangerously-skip-permissions`・`--allowedTools`）が不要になる**のが最大の利点 |
| `--no-session-persistence` | セッションをディスクに残さない。毎回独立した1回完結の呼び出しで、`--session-id`/`--resume` を使わない |
| `--system-prompt` | 既定のコーディング用プロンプトを置き換え、要約・判定の指示だけにする。`--append-system-prompt` は既定プロンプトが残る分、コンテキストが増えコストが上がる |
| `--model`（任意） | 設定ファイルで指定可能にする程度。未指定ならCLI既定 |

### 権限フラグの検討結果

`--dangerously-skip-permissions` は**不要**。理由:

- 対話確認が発生するのはツール実行時のみで、`--tools ""` により発生しない。
- producer-desk で必要だったのは、worktree 内のファイル編集・`gh`/`git` 実行を無人で通すため。deep-tracker の AI 処理にこの副作用は無い。
- 入力にはRSS記事本文（外部由来の不信頼テキスト）が入る。ツールを持たせなければ、プロンプトインジェクションで任意コマンド実行やファイル操作に誘導される経路を断てる。

### プロンプトと入出力

- 長い記事本文を引数に直接渡すと OS の引数長上限（macOS は約1MB）に当たりうる。長文は標準入力で渡す（`-p` に短い指示を、本文は stdin）。
- 出力形式が必要な判定（例: 興味に合うかのスコア）は `--json-schema` で構造化出力を指定できる（CLIヘルプで提供を確認。実利用時は別途検証する）。
- 作業ディレクトリ（`cwd`）は、プロジェクトの `CLAUDE.md` を拾わないよう、リポジトリ外の専用ディレクトリを指定する。
- タイムアウトは呼び出し側（`subprocess` の `timeout`）で設ける。CLI 側に実行時間の上限引数は無い。

## 5. `AIProvider` 設計への示唆

- インターフェースは「プロンプト（と任意のシステム指示）を渡し、テキストとメタ情報を返す」だけにする。
- 結果型には最低限、`text`・`is_error`・`usage`（トークン数）を含める。
- 利用制限は専用の例外（例: `UsageLimitError`、`reset_text: str | None` を保持）として送出し、呼び出し側（ジョブ実行管理）で判別できるようにする。その他の失敗は別の例外にする。
- 利用制限時の動作: ジョブを失敗として記録して打ち切り、**待機はしない**。次の定期実行で再試行する。週次サマリのような低頻度ジョブでは、待機のために長時間プロセスを占有する利点が無い。解除予定時刻は記録して画面・Slack通知に出す。
- `AIProvider` の実装は subprocess 呼び出しを関数注入にしてテスト可能にする（producer-desk は `popen` 等を引数注入している）。

## 6. Slack通知・設定読み込みで流用できる点

### `slack_notifier.py`

- 通知は `urllib.request` による Incoming Webhook への JSON POST のみ（`{"text": ...}`）。依存追加が不要で、そのまま流用できる。
- 送信関数（`post_webhook`）と Webhook URL 取得関数（`get_webhook_url`）をコンストラクタ注入にしており、テストで差し替えやすい。この構造は踏襲する。
- 変更点: producer-desk は環境変数 `SLACK_WEBHOOK_URL` から URL を読むが、deep-tracker は CLAUDE.md の確定事項により**設定ファイルから読む**。取得関数の既定実装を「設定から読む」に変えるだけで済む。
- 起動時点の既存状態を「既知」として再通知しない仕組み（`_known`）は、新規発生のみを通知する用途向け。deep-tracker の週次サマリ通知は「生成のたびに1回送る」ため不要。
- 注意点: `urlopen` に `timeout` が指定されていない。流用時は必ずタイムアウトを付け、通知失敗でジョブ本体を失敗扱いにしない。

### `config.py`

- `yaml.safe_load` で YAML を読み、ファイルが無ければ「`*.yaml.example` を参考に作成してください」と案内する `FileNotFoundError` を送出する。deep-tracker の `config/config.yaml.example` 運用と一致するため流用できる。
- 環境変数（`PROJECTS_CONFIG_PATH`）で読み込み先を上書きできる。deep-tracker の複数バージョン並行稼働（設定の同梱・DB/ポートを設定で分ける）では、並行インスタンスごとに別ファイルを指す用途で有用。
- 設定をdataclassに詰めて起動時に検証する構造（`validate_execution_settings`）は、不正な設定を起動時に弾く方針として流用する。
- 流用しない部分: 実行時にYAMLへ書き戻す機能（`update_project_execution_settings`、書き込みロック）。deep-tracker は「設定はGUIから変更せず、YAML編集のみ」のため不要。
- 設定項目の追加案（実装は別issue）: `slack.webhook_url`、`ai.model`（任意）、`ai.timeout_seconds`。

## 7. 利用量の記録

producer-desk は結果JSONの `total_cost_usd`・`usage.*`・`modelUsage.*` を SQLite に記録している。deep-tracker は要件上アプリ側で利用上限を設けないが、`json` 出力から同じ値が取れる（実機確認済み）ため、ジョブ実行履歴に保存しておくと原因調査に使える。ただし必須とはせず、AI基盤（フェーズ3）の実装時に判断する。

## 8. 受け入れ条件との対応

- 利用制限エラーの検出方法: §3（`is_error: true` かつ `api_error_status: 429`、解除予定時刻は `result` から抽出）。
- 呼び出しに使うCLI引数: §4（`-p --output-format json --tools "" --no-session-persistence --system-prompt`）。
