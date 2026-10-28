#!/bin/bash
# backend と frontend をバックグラウンドで起動する。
#
# 使い方: scripts/start.sh
# 環境変数: FRONTEND_MODE  start（既定。未ビルドなら build する）| dev
#           LAN_IP | TAILSCALE_IP  frontend を待ち受けさせるIP（どちらか一方。未指定なら 127.0.0.1）
#
# ポートは config.yaml の frontend.port / backend.port に従う。
# 停止は scripts/stop.sh。
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

# /api/* の中継先は実行時に BACKEND_URL から読まれる（ビルドし直し不要）。backend は常に 127.0.0.1
BACKEND_URL="${BACKEND_URL:-http://127.0.0.1:$BACKEND_PORT}"
# 旧方式（rewrites）のビルドは BACKEND_URL ファイルが残っているため、1度だけ作り直す
LEGACY_MARKER="$DEPLOY_ROOT/frontend/.next/BACKEND_URL"
if [[ "$MODE" == start ]] && [[ ! -f "$DEPLOY_ROOT/frontend/.next/BUILD_ID" || -f "$LEGACY_MARKER" ]]; then
    echo "frontend をビルドします"
    rm -f "$LEGACY_MARKER"
    (cd "$DEPLOY_ROOT/frontend" && env -u NODE_ENV npm run build)
fi

(cd "$DEPLOY_ROOT/backend" && nohup uv run python -m deep_tracker.main \
    >>"$LOG_DIR/backend.log" 2>&1 & echo $! >"$(pid_file backend)")

if [[ -n "$FRONTEND_PUBLIC" ]]; then
    echo "注意: $FRONTEND_HOST で待ち受けます（認証なし）。同じネットワーク/tailnet に接続できる全員が操作できます" >&2
else
    echo "LAN_IP / TAILSCALE_IP が未指定のため、このマシンからのみ接続できます（127.0.0.1）"
fi

DEV_ORIGINS_DEFAULT="$BASE_URL_HOST"
if [[ -n "$FRONTEND_PUBLIC" ]]; then
    DEV_ORIGINS_DEFAULT="${DEV_ORIGINS_DEFAULT:+$DEV_ORIGINS_DEFAULT,}$FRONTEND_HOST"
fi

# BACKEND_URL は /api/* の中継先
# ALLOWED_DEV_ORIGINS は next dev が許可する接続元ホスト（既定は slack.base_url のホストと bind先のIP）
(cd "$DEPLOY_ROOT/frontend" &&
    FRONTEND_HOST="$FRONTEND_HOST" FRONTEND_PORT="$FRONTEND_PORT" BACKEND_URL="$BACKEND_URL" \
        ALLOWED_DEV_ORIGINS="${ALLOWED_DEV_ORIGINS:-$DEV_ORIGINS_DEFAULT}" \
        nohup npm run "$MODE" >>"$LOG_DIR/frontend.log" 2>&1 & echo $! >"$(pid_file frontend)")

echo "起動しました: backend http://127.0.0.1:$BACKEND_PORT / frontend http://$FRONTEND_HOST:$FRONTEND_PORT"
echo "ログ: $LOG_DIR/{backend,frontend}.log"
