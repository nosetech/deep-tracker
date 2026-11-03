# start.sh / stop.sh 共通。source して使う。
DEPLOY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# 設定ファイルの値を読み込む（検証は backend の設定ローダーに任せる。不正なら失敗する）
load_config() {
    eval "$(cd "$DEPLOY_ROOT/backend" && uv run python -m deep_tracker.config)" || exit 1
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

# frontend が未ビルド（または旧方式のビルド）ならビルドする
ensure_frontend_build() {
    local legacy="$DEPLOY_ROOT/frontend/.next/BACKEND_URL"
    if [[ ! -f "$DEPLOY_ROOT/frontend/.next/BUILD_ID" || -f "$legacy" ]]; then
        echo "frontend をビルドします"
        rm -f "$legacy"
        (cd "$DEPLOY_ROOT/frontend" && env -u NODE_ENV npm run build)
    fi
}
