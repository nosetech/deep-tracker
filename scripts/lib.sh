# shellcheck shell=bash
# start.sh / stop.sh 等の共通処理。source して使う。
DEPLOY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# 展開先ルートの .env から LAN_IP / TAILSCALE_IP を読み込む（frontend の公開先IP）。
# シェルで既に指定されている環境変数が優先される。書式は KEY=VALUE（# 始まりの行は無視、値は引用符で囲んでもよい）
load_env() {
    local f="$DEPLOY_ROOT/.env" line key val
    [[ -f "$f" ]] || return 0
    while IFS= read -r line || [[ -n "$line" ]]; do
        line="${line#"${line%%[![:space:]]*}"}"
        [[ "$line" =~ ^(LAN_IP|TAILSCALE_IP)=(.*)$ ]] || continue
        key="${BASH_REMATCH[1]}"
        val="${BASH_REMATCH[2]}"
        val="${val%"${val##*[![:space:]]}"}"
        val="${val#[\"\']}"
        val="${val%[\"\']}"
        if [[ -n "$val" && -z "${!key:-}" ]]; then
            export "$key=$val"
        fi
    done <"$f"
}

# 配布版（frontend が Next.js の standalone ビルド済みで展開されている）か
is_standalone() { [[ -f "$DEPLOY_ROOT/frontend/server.js" ]]; }

# 設定ファイルの値を読み込む（検証は backend の設定ローダーに任せる。不正なら失敗する）
load_config() {
    load_env
    local vars
    vars="$(cd "$DEPLOY_ROOT/backend" && uv run python -m deep_tracker.config)" || exit 1
    eval "$vars"
    PID_DIR="$LOG_DIR"
}

pid_file() { echo "$PID_DIR/deep-tracker.$INSTANCE.$1.pid"; }

is_running() {
    local f
    f="$(pid_file "$1")"
    [[ -f "$f" ]] && kill -0 "$(cat "$f")" 2>/dev/null
}

# 常時起動（launchd の LaunchAgent）のラベル。load_config の後に使う
service_label() { echo "com.nosetech.deep-tracker.$INSTANCE.$1"; }

# 常時起動サービスが launchd に登録されているか（start.sh との二重起動防止に使う）
service_registered() {
    launchctl print "gui/$(id -u)/$(service_label "$1")" >/dev/null 2>&1
}

# frontend が未ビルド（または旧方式のビルド）ならビルドする。配布版はビルド済みなので何もしない
ensure_frontend_build() {
    is_standalone && return 0
    local legacy="$DEPLOY_ROOT/frontend/.next/BACKEND_URL"
    if [[ ! -f "$DEPLOY_ROOT/frontend/.next/BUILD_ID" || -f "$legacy" ]]; then
        echo "frontend をビルドします"
        rm -f "$legacy"
        (cd "$DEPLOY_ROOT/frontend" && env -u NODE_ENV npm run build)
    fi
}

# FRONTEND_MODE を検証して MODE に入れる（start | dev。配布版は start のみ）
resolve_frontend_mode() {
    MODE="${FRONTEND_MODE:-start}"
    if is_standalone && [[ "$MODE" == dev ]]; then
        echo "配布版では FRONTEND_MODE=dev は使えません" >&2
        exit 2
    fi
    case "$MODE" in
    start | dev) ;;
    *)
        echo "FRONTEND_MODE は start か dev を指定してください: $MODE" >&2
        exit 2
        ;;
    esac
}

# 起動前チェック（launchd 登録中・二重起動は拒否する）。引数: backend | frontend
guard_start() {
    local svc=$1
    if service_registered "$svc"; then
        echo "$svc は常時起動（launchd）に登録されています。scripts/service.sh stop（または uninstall）で止めてから実行してください" >&2
        exit 1
    fi
    if is_running "$svc"; then
        echo "$svc は既に起動しています（pid $(cat "$(pid_file "$svc")")）。先に scripts/stop.sh（または ${svc}_stop.sh）を実行してください" >&2
        exit 1
    fi
}

# 標準入力を日次ローテーション付きで $LOG_DIR/$1 へ書き出す（プロセス置換から呼ぶ）
rotate_to() {
    cd "$DEPLOY_ROOT/backend" && exec "$DEPLOY_ROOT/backend/.venv/bin/python" -m deep_tracker.log_rotator \
        --path "$LOG_DIR/$1" --retention-days "$LOG_RETENTION_DAYS"
}

# 注意: PID ファイルに本体の PID を書くため、& は cd && ... のリストではなくコマンド単体に掛ける
#（リストに掛けると $! が起動用サブシェル(bash)の PID になる）。cd は独立した文にする。
# backend: uv run は exec せず子プロセスとして起こすため、venv の python を直接起動する。
# backend.log は backend 自身が logging で書く。ここへ来るのは起動前のクラッシュ・未捕捉例外など
# logging を経由しない出力で、同じパスを2プロセスが開くとローテーションが競合するため別ファイルにする。
# 本体が止まるとパイプが閉じてローテータも終了する
start_backend() {
    guard_start backend
    local py="$DEPLOY_ROOT/backend/.venv/bin/python"
    if [[ ! -x "$py" ]]; then
        echo "backend/.venv がありません。backend で uv sync を実行してください" >&2
        exit 1
    fi
    mkdir -p "$LOG_DIR"
    (
        cd "$DEPLOY_ROOT/backend" || exit 1
        PYTHONUNBUFFERED=1 nohup "$py" -m deep_tracker.main \
            > >(rotate_to backend.stderr.log) 2>&1 &
        echo $! >"$(pid_file backend)"
    )
}

# frontend を起動する（resolve_frontend_mode の後に呼ぶ）。
# /api/* の中継先は実行時に BACKEND_URL から読まれる（ビルドし直し不要）。backend は常に 127.0.0.1
# ALLOWED_DEV_ORIGINS は next dev が許可する接続元ホスト（既定は slack.base_url のホストと bind先のIP）
start_frontend() {
    guard_start frontend
    if [[ "$MODE" == start ]]; then
        ensure_frontend_build
    fi
    mkdir -p "$LOG_DIR"
    local backend_url="${BACKEND_URL:-http://127.0.0.1:$BACKEND_PORT}"
    local dev_origins="$BASE_URL_HOST"
    if [[ -n "$FRONTEND_PUBLIC" ]]; then
        dev_origins="${dev_origins:+$dev_origins,}$FRONTEND_HOST"
    fi
    if is_standalone; then
        # 配布版: Next.js の standalone 出力を node で直接起動する（利用者側の npm / ビルドは不要）
        (
            cd "$DEPLOY_ROOT/frontend" || exit 1
            NODE_ENV=production HOSTNAME="$FRONTEND_HOST" PORT="$FRONTEND_PORT" BACKEND_URL="$backend_url" \
                nohup node server.js > >(rotate_to frontend.log) 2>&1 &
            echo $! >"$(pid_file frontend)"
        )
    else
        (
            cd "$DEPLOY_ROOT/frontend" || exit 1
            FRONTEND_HOST="$FRONTEND_HOST" FRONTEND_PORT="$FRONTEND_PORT" BACKEND_URL="$backend_url" \
                ALLOWED_DEV_ORIGINS="${ALLOWED_DEV_ORIGINS:-$dev_origins}" \
                nohup npm run "$MODE" > >(rotate_to frontend.log) 2>&1 &
            echo $! >"$(pid_file frontend)"
        )
    fi
}

# frontend の待ち受け先の案内（stderr/stdout）
print_frontend_notice() {
    if [[ -n "$FRONTEND_PUBLIC" ]]; then
        echo "注意: $FRONTEND_HOST で待ち受けます（認証なし）。同じネットワーク/tailnet に接続できる全員が操作できます" >&2
    else
        echo "LAN_IP / TAILSCALE_IP が未指定のため、このマシンからのみ接続できます（127.0.0.1）"
    fi
}

# uv / npm は子プロセスを起こすので、子孫を先に止めてから親を止める
kill_tree() {
    local pid=$1 child
    for child in $(pgrep -P "$pid" 2>/dev/null || true); do
        kill_tree "$child"
    done
    kill "$pid" 2>/dev/null || true
}

# サービスを停止する（未起動でもエラーにしない）。引数: backend | frontend
stop_service() {
    local svc=$1
    if is_running "$svc"; then
        kill_tree "$(cat "$(pid_file "$svc")")"
        echo "$svc を停止しました"
    else
        echo "$svc は起動していません"
    fi
    rm -f "$(pid_file "$svc")"
}
