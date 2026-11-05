# start.sh / stop.sh 共通。source して使う。
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
