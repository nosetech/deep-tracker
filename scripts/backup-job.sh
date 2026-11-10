#!/bin/bash
# DBバックアップの launchd ジョブを管理する。
#
# 使い方: scripts/backup-job.sh {install|uninstall|start|stop|status|run}
#   install    plist を生成して ~/Library/LaunchAgents に置き、登録する（再実行で更新）
#   uninstall  登録を解除して plist を削除する
#   start      登録済みジョブを今すぐ1回実行する
#   stop       実行中のバッチがあれば停止する（定期実行の登録は残る）
#   status     登録状況を表示する
#   run        launchd を介さず、このシェルで1回実行する
#
# 毎日3:00に実行する。バックアップ先と保持日数は config.yaml の backup セクションで指定する。
set -euo pipefail

DEPLOY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$DEPLOY_ROOT/backend/.venv/bin/python"
TEMPLATE="$DEPLOY_ROOT/scripts/com.nosetech.deep-tracker.backup.plist.example"

if [[ ! -x "$PYTHON" ]]; then
    echo "backend/.venv が見つかりません。先に (cd backend && uv sync) を実行してください" >&2
    exit 1
fi

# 設定ファイルの instance を取得する（不正な設定ならここで失敗する）
INSTANCE="$(cd "$DEPLOY_ROOT/backend" && "$PYTHON" -m deep_tracker.jobs.backup --print-instance)"
LABEL="com.nosetech.deep-tracker.${INSTANCE}.backup"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
TARGET="gui/$(id -u)/${LABEL}"

case "${1:-}" in
install)
    mkdir -p "$HOME/Library/LaunchAgents" "$DEPLOY_ROOT/logs"
    sed -e "s|__INSTANCE__|${INSTANCE}|g" \
        -e "s|__DEPLOY_ROOT__|${DEPLOY_ROOT}|g" \
        "$TEMPLATE" >"$PLIST"
    plutil -lint "$PLIST" >/dev/null
    launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "$PLIST"
    echo "登録しました: ${LABEL}（毎日3:00）"
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
    launchctl print "$TARGET" | grep -E "state|last exit code|runs" || true
    ;;
run)
    cd "$DEPLOY_ROOT/backend" && exec "$PYTHON" -m deep_tracker.jobs.backup
    ;;
*)
    sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit 2
    ;;
esac
