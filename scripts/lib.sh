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
