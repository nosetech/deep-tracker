#!/bin/bash
# サマリ定期実行バッチの launchd ジョブを管理する。
#
# 使い方: scripts/summary-job.sh {install|uninstall|start|stop|status|run}
#   install    plist を生成して ~/Library/LaunchAgents に置き、登録する（再実行で更新）
#   uninstall  登録を解除して plist を削除する
#   start      登録済みジョブを今すぐ1回実行する
#   stop       実行中のバッチがあれば停止する（定期実行の登録は残る）
#   status     登録状況を表示する
#   run        launchd を介さず、このシェルで1回実行する
#
# 環境変数: SUMMARY_TICK_SECONDS  launchd の起動間隔（秒、既定 3600）
set -euo pipefail

DEPLOY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$DEPLOY_ROOT/backend/.venv/bin/python"
TEMPLATE="$DEPLOY_ROOT/scripts/com.nosetech.deep-tracker.summary.plist.example"
INTERVAL="${SUMMARY_TICK_SECONDS:-3600}"

if [[ ! -x "$PYTHON" ]]; then
    echo "backend/.venv が見つかりません。先に (cd backend && uv sync) を実行してください" >&2
    exit 1
fi

# 設定ファイルの instance を取得する（不正な設定ならここで失敗する）
INSTANCE="$(cd "$DEPLOY_ROOT/backend" && "$PYTHON" -m deep_tracker.jobs.summary --print-instance)"
LABEL="com.nosetech.deep-tracker.${INSTANCE}.summary"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
TARGET="gui/$(id -u)/${LABEL}"

case "${1:-}" in
install)
    mkdir -p "$HOME/Library/LaunchAgents" "$DEPLOY_ROOT/logs"
    sed -e "s|__INSTANCE__|${INSTANCE}|g" \
        -e "s|__DEPLOY_ROOT__|${DEPLOY_ROOT}|g" \
        -e "s|__INTERVAL_SECONDS__|${INTERVAL}|g" \
        "$TEMPLATE" >"$PLIST"
    plutil -lint "$PLIST" >/dev/null
    launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "$PLIST"
    echo "登録しました: ${LABEL}（${INTERVAL}秒ごとに確認）"
    ;;
uninstall)
    launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
    rm -f "$PLIST"
    echo "登録を解除しました: ${LABEL}"
    ;;
start)
    launchctl kickstart "$TARGET"
    echo "実行を開始しました: ${LABEL}"
    ;;
stop)
    launchctl kill SIGTERM "$TARGET"
    echo "停止を要求しました: ${LABEL}"
    ;;
status)
    launchctl print "$TARGET" | grep -E "state|last exit code|run interval|runs" || true
    ;;
run)
    cd "$DEPLOY_ROOT/backend" && exec "$PYTHON" -m deep_tracker.jobs.summary
    ;;
*)
    sed -n '2,13p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit 2
    ;;
esac
