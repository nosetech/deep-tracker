#!/bin/bash
# backend と frontend をバックグラウンドで起動する。
#
# 使い方: scripts/start.sh
# 環境変数: FRONTEND_MODE  start（既定。未ビルドなら build する）| dev
#
# 待ち受けは config.yaml の frontend.host / frontend.port / backend.port に従う。
# 停止は scripts/stop.sh。フォアグラウンドで frontend だけ起動する場合は scripts/frontend.sh。
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
load_config
mkdir -p "$LOG_DIR"

MODE="${FRONTEND_MODE:-start}"
case "$MODE" in
start | dev) ;;
*)
    echo "FRONTEND_MODE は start か dev を指定してください: $MODE" >&2
    exit 2
    ;;
esac

for svc in backend frontend; do
    if is_running "$svc"; then
        echo "$svc は既に起動しています（pid $(cat "$(pid_file "$svc")")）。先に scripts/stop.sh を実行してください" >&2
        exit 1
    fi
done

# /api/* の中継先は next build 時に固定される。未ビルド、または別のポートでビルド済みなら作り直す
BACKEND_URL="${BACKEND_URL:-http://127.0.0.1:$BACKEND_PORT}"
BUILT_URL_FILE="$DEPLOY_ROOT/frontend/.next/BACKEND_URL"
if [[ "$MODE" == start ]] &&
    [[ ! -f "$DEPLOY_ROOT/frontend/.next/BUILD_ID" || "$(cat "$BUILT_URL_FILE" 2>/dev/null)" != "$BACKEND_URL" ]]; then
    echo "frontend をビルドします（中継先 ${BACKEND_URL}）"
    (cd "$DEPLOY_ROOT/frontend" && BACKEND_URL="$BACKEND_URL" env -u NODE_ENV npm run build)
    echo "$BACKEND_URL" >"$BUILT_URL_FILE"
fi

(cd "$DEPLOY_ROOT/backend" && nohup uv run python -m deep_tracker.main \
    >>"$LOG_DIR/backend.log" 2>&1 & echo $! >"$(pid_file backend)")

# ホスト/ポート/BACKEND_URL の解決と LAN公開の警告は frontend.sh に任せる
(nohup "$DEPLOY_ROOT/scripts/frontend.sh" "$MODE" \
    >>"$LOG_DIR/frontend.log" 2>&1 & echo $! >"$(pid_file frontend)")

echo "起動しました: backend http://127.0.0.1:$BACKEND_PORT / frontend http://$FRONTEND_HOST:$FRONTEND_PORT"
echo "ログ: $LOG_DIR/{backend,frontend}.log"
