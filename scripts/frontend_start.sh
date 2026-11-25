#!/bin/bash
# frontend だけをバックグラウンドで起動する（起動したらすぐ終了する）。
#
# 使い方: scripts/frontend_start.sh
# 環境変数: FRONTEND_MODE  start（既定。未ビルドなら build する）| dev（配布版は start のみ）
#           LAN_IP | TAILSCALE_IP  待ち受けさせるIP（どちらか一方。未指定なら 127.0.0.1。.env にも書ける）
# 停止は scripts/frontend_stop.sh。PID・ログ・ポートは start.sh と共通（混在して停止できる）。
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
load_config
resolve_frontend_mode
start_frontend
# 一括起動（start.sh）からは DEEP_TRACKER_BATCH=1 で呼ばれ、案内は start.sh がまとめて出す
if [[ -z "${DEEP_TRACKER_BATCH:-}" ]]; then
    print_frontend_notice
    echo "起動しました: frontend http://$FRONTEND_HOST:$FRONTEND_PORT"
    echo "ログ: $LOG_DIR/frontend.log（日次ローテーション、${LOG_RETENTION_DAYS}日保持）"
fi
