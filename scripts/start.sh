#!/bin/bash
# backend と frontend をバックグラウンドで起動する（backend_start.sh → frontend_start.sh）。
#
# 使い方: scripts/start.sh
# 環境変数: FRONTEND_MODE  start（既定。未ビルドなら build する）| dev（配布版は start のみ）
#           LAN_IP | TAILSCALE_IP  frontend を待ち受けさせるIP（どちらか一方。未指定なら 127.0.0.1）
#                                 展開先ルートの .env にも書ける（シェルの環境変数が優先）
#
# 本体の出力は deep_tracker.log_rotator へパイプし、JST 0時に日次ローテーションする
# （保持日数は config.yaml の logging.retention_days）。`>>` だとローテーション後も旧ファイルへ書き続けるため使わない。
#
# ポートは config.yaml の frontend.port / backend.port に従う。個別の起動・停止は
# scripts/{backend,frontend}_{start,stop}.sh。停止は scripts/stop.sh。
set -euo pipefail
dir="$(dirname "${BASH_SOURCE[0]}")"
source "$dir/lib.sh"
load_config
mkdir -p "$LOG_DIR"

# どちらかが起動できない状態なら、片方だけ起動してしまう前に拒否する
resolve_frontend_mode
(guard_start backend)
(guard_start frontend)

export DEEP_TRACKER_BATCH=1
"$dir/backend_start.sh"
"$dir/frontend_start.sh"

print_frontend_notice
echo "起動しました: backend http://127.0.0.1:$BACKEND_PORT / frontend http://$FRONTEND_HOST:$FRONTEND_PORT"
echo "ログ: $LOG_DIR/{backend,backend.stderr,frontend}.log（日次ローテーション、${LOG_RETENTION_DAYS}日保持）"
