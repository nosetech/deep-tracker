#!/bin/bash
# backend だけをバックグラウンドで起動する（起動したらすぐ終了する）。
#
# 使い方: scripts/backend_start.sh
# 停止は scripts/backend_stop.sh。PID・ログ・ポートは start.sh と共通（混在して停止できる）。
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
load_config
start_backend
# 一括起動（start.sh）からは DEEP_TRACKER_BATCH=1 で呼ばれ、案内は start.sh がまとめて出す
if [[ -z "${DEEP_TRACKER_BATCH:-}" ]]; then
    echo "起動しました: backend http://127.0.0.1:$BACKEND_PORT"
    echo "ログ: $LOG_DIR/{backend,backend.stderr}.log（日次ローテーション、${LOG_RETENTION_DAYS}日保持）"
fi
