#!/bin/bash
# backend / frontend を常駐サービス（launchd の LaunchAgent）として管理する。
#
# 使い方: scripts/service.sh {install|uninstall|start|stop|restart|status}
#   install    frontend を（未ビルドなら）ビルドし、plist を生成して登録・起動する（再実行で更新）
#   uninstall  登録を解除して plist を削除する
#   start      登録済みのサービスを起動する
#   stop       サービスを停止する（plist は残る。ログイン時に再び起動する）
#   restart    設定変更を反映するため再起動する
#   status     登録状況を表示する
#
# 環境変数: LAN_IP | TAILSCALE_IP  frontend を待ち受けさせるIP（install 時の値を plist に固定する）
#           DEEP_TRACKER_CONFIG  設定ファイルのパス（指定時は install 時の値を plist に固定する）
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

SERVICES=(backend frontend)
DOMAIN="gui/$(id -u)"
AGENTS="$HOME/Library/LaunchAgents"

plist_path() { echo "$AGENTS/$(service_label "$1").plist"; }

bootstrap_all() {
    local svc
    for svc in "${SERVICES[@]}"; do
        if service_registered "$svc"; then
            echo "$svc は既に起動しています"
        else
            launchctl bootstrap "$DOMAIN" "$(plist_path "$svc")"
            echo "$svc を起動しました"
        fi
    done
}

bootout_all() {
    local svc
    for svc in frontend backend; do
        if service_registered "$svc"; then
            launchctl bootout "$DOMAIN/$(service_label "$svc")" 2>/dev/null || true
            # プロセスの終了を待つ（待たずに再登録すると、まだ残っている旧プロセスとぶつかる）
            for _ in $(seq 1 30); do
                service_registered "$svc" || break
                sleep 0.5
            done
            echo "$svc を停止しました"
        else
            echo "$svc は起動していません"
        fi
    done
}

require_plists() {
    local svc
    for svc in "${SERVICES[@]}"; do
        [[ -f "$(plist_path "$svc")" ]] || {
            echo "$svc が未登録です。先に scripts/service.sh install を実行してください" >&2
            exit 1
        }
    done
}

need_tool() {
    command -v "$1" >/dev/null || {
        echo "$1 が見つかりません" >&2
        exit 1
    }
}

install_service() {
    local svc="$1" path="$2" node="$3" backend_url="$4"
    local plist
    plist="$(plist_path "$svc")"
    sed -e "s|__INSTANCE__|${INSTANCE}|g" \
        -e "s|__DEPLOY_ROOT__|${DEPLOY_ROOT}|g" \
        -e "s|__PATH__|${path}|g" \
        -e "s|__NODE__|${node}|g" \
        -e "s|__FRONTEND_HOST__|${FRONTEND_HOST}|g" \
        -e "s|__FRONTEND_PORT__|${FRONTEND_PORT}|g" \
        -e "s|__BACKEND_URL__|${backend_url}|g" \
        "$DEPLOY_ROOT/scripts/com.nosetech.deep-tracker.$svc.plist.example" >"$plist"
    # LAN_IP / TAILSCALE_IP / DEEP_TRACKER_CONFIG は launchd に渡らないため、install 時の値を固定する
    # （backend の通知リンク等も同じ値を参照する）
    local var
    for var in LAN_IP TAILSCALE_IP DEEP_TRACKER_CONFIG; do
        if [[ -n "${!var:-}" ]]; then
            plutil -insert "EnvironmentVariables.$var" -string "${!var}" "$plist"
        fi
    done
    plutil -lint "$plist" >/dev/null
}

cmd="${1:-}"
case "$cmd" in
install)
    load_config
    PYTHON="$DEPLOY_ROOT/backend/.venv/bin/python"
    [[ -x "$PYTHON" ]] || {
        echo "backend/.venv が見つかりません。先に (cd backend && uv sync) を実行してください" >&2
        exit 1
    }
    need_tool node
    need_tool npm
    [[ -d "$DEPLOY_ROOT/frontend/node_modules/next" ]] || {
        echo "frontend の依存がありません。先に (cd frontend && npm install) を実行してください" >&2
        exit 1
    }
    for svc in "${SERVICES[@]}"; do
        if is_running "$svc"; then
            echo "$svc が scripts/start.sh で起動中です。先に scripts/stop.sh を実行してください" >&2
            exit 1
        fi
    done
    ensure_frontend_build
    mkdir -p "$AGENTS" "$LOG_DIR"
    # launchd の PATH は最小限。node / uv / claude のあるディレクトリを引き継ぐ
    SERVICE_PATH="$(dirname "$(command -v node)"):$PATH"
    NODE_BIN="$(command -v node)"
    BACKEND_URL="${BACKEND_URL:-http://127.0.0.1:$BACKEND_PORT}"
    # 更新のため、登録済みなら一度外す
    bootout_all >/dev/null
    for svc in "${SERVICES[@]}"; do
        install_service "$svc" "$SERVICE_PATH" "$NODE_BIN" "$BACKEND_URL"
    done
    bootstrap_all
    echo "登録しました: backend http://127.0.0.1:$BACKEND_PORT / frontend http://$FRONTEND_HOST:$FRONTEND_PORT"
    echo "ログ: $LOG_DIR/{backend,frontend}.log"
    ;;
uninstall)
    load_config
    bootout_all
    for svc in "${SERVICES[@]}"; do
        rm -f "$(plist_path "$svc")"
    done
    echo "登録を解除しました"
    ;;
start)
    load_config
    require_plists
    bootstrap_all
    ;;
stop)
    load_config
    bootout_all
    ;;
restart)
    load_config
    require_plists
    bootout_all
    bootstrap_all
    ;;
status)
    load_config
    for svc in "${SERVICES[@]}"; do
        echo "== $svc ($(service_label "$svc"))"
        if service_registered "$svc"; then
            launchctl print "$DOMAIN/$(service_label "$svc")" | grep -E "^\s*(state|pid|last exit code|runs) " || true
        elif [[ -f "$(plist_path "$svc")" ]]; then
            echo "登録済みですが停止中です（scripts/service.sh start）"
        else
            echo "未登録です"
        fi
    done
    ;;
*)
    sed -n "2,14p" "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit 2
    ;;
esac
