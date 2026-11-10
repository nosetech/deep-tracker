#!/bin/bash
# backend と frontend をバックグラウンドで起動する。
#
# 使い方: scripts/start.sh
# 環境変数: FRONTEND_MODE  start（既定。未ビルドなら build する）| dev（配布版は start のみ）
#           LAN_IP | TAILSCALE_IP  frontend を待ち受けさせるIP（どちらか一方。未指定なら 127.0.0.1）
#                                 展開先ルートの .env にも書ける（シェルの環境変数が優先）
#
# 本体の出力は deep_tracker.log_rotator へパイプし、JST 0時に日次ローテーションする
# （保持日数は config.yaml の logging.retention_days）。`>>` だとローテーション後も旧ファイルへ書き続けるため使わない。
#
# ポートは config.yaml の frontend.port / backend.port に従う。
# 停止は scripts/stop.sh。
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
load_config
mkdir -p "$LOG_DIR"

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

for svc in backend frontend; do
    if service_registered "$svc"; then
        echo "$svc は常時起動（launchd）に登録されています。scripts/service.sh stop（または uninstall）で止めてから実行してください" >&2
        exit 1
    fi
    if is_running "$svc"; then
        echo "$svc は既に起動しています（pid $(cat "$(pid_file "$svc")")）。先に scripts/stop.sh を実行してください" >&2
        exit 1
    fi
done

# 標準入力を日次ローテーション付きで $LOG_DIR/$1 へ書き出す（プロセス置換から呼ぶ）
rotate_to() {
    cd "$DEPLOY_ROOT/backend" && exec uv run python -m deep_tracker.log_rotator \
        --path "$LOG_DIR/$1" --retention-days "$LOG_RETENTION_DAYS"
}

# /api/* の中継先は実行時に BACKEND_URL から読まれる（ビルドし直し不要）。backend は常に 127.0.0.1
BACKEND_URL="${BACKEND_URL:-http://127.0.0.1:$BACKEND_PORT}"
if [[ "$MODE" == start ]]; then
    ensure_frontend_build
fi

# backend.log は backend 自身が logging で書く。ここへ来るのは起動前のクラッシュ・未捕捉例外など
# logging を経由しない出力で、同じパスを2プロセスが開くとローテーションが競合するため別ファイルにする。
# PIDは本体のもの（プロセス置換の $!）。本体が止まるとパイプが閉じてローテータも終了する
(cd "$DEPLOY_ROOT/backend" && PYTHONUNBUFFERED=1 nohup uv run python -m deep_tracker.main \
    > >(rotate_to backend.stderr.log) 2>&1 & echo $! >"$(pid_file backend)")

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
if is_standalone; then
    # 配布版: Next.js の standalone 出力を node で直接起動する（利用者側の npm / ビルドは不要）
    (cd "$DEPLOY_ROOT/frontend" &&
        NODE_ENV=production HOSTNAME="$FRONTEND_HOST" PORT="$FRONTEND_PORT" BACKEND_URL="$BACKEND_URL" \
            nohup node server.js > >(rotate_to frontend.log) 2>&1 & echo $! >"$(pid_file frontend)")
else
    (cd "$DEPLOY_ROOT/frontend" &&
        FRONTEND_HOST="$FRONTEND_HOST" FRONTEND_PORT="$FRONTEND_PORT" BACKEND_URL="$BACKEND_URL" \
            ALLOWED_DEV_ORIGINS="${ALLOWED_DEV_ORIGINS:-$DEV_ORIGINS_DEFAULT}" \
            nohup npm run "$MODE" > >(rotate_to frontend.log) 2>&1 & echo $! >"$(pid_file frontend)")
fi

echo "起動しました: backend http://127.0.0.1:$BACKEND_PORT / frontend http://$FRONTEND_HOST:$FRONTEND_PORT"
echo "ログ: $LOG_DIR/{backend,backend.stderr,frontend}.log（日次ローテーション、${LOG_RETENTION_DAYS}日保持）"
