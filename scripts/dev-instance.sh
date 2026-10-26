#!/bin/bash
# 運用と分離した動作確認用の backend / frontend を起動・停止・確認する。
#
# 使い方: scripts/dev-instance.sh start|stop|status
# 環境変数: DEV_BACKEND_PORT / DEV_FRONTEND_PORT  ポートの明示指定（運用既定値・使用中は拒否）
#
# ポート・DB・設定・ログ・PID記録は <展開先>/.dev-run/ に閉じる。
# Slack通知とAI(Claude Code CLI)呼び出しは DEEP_TRACKER_DEV_MODE=1 で常に無効。
# stop は記録と一致するプロセスグループだけを止め、名前やポートで探して kill しない。
set -euo pipefail

DEPLOY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="$DEPLOY_ROOT/.dev-run"
STATE="$RUN_DIR/state.env"
MARKER_ENV="DEEP_TRACKER_DEV_INSTANCE"

die() {
    echo "$*" >&2
    exit 1
}

# プロセスグループのリーダーとして起動する（macOS に setsid が無いため python で代替）。
# 引数: 名前 作業ディレクトリ コマンド...
spawn() {
    local name=$1 dir=$2
    shift 2
    (
        cd "$dir"
        nohup python3 -I -c 'import os, sys; os.setsid(); os.execvp(sys.argv[1], sys.argv[1:])' "$@" \
            >>"$RUN_DIR/$name.log" 2>&1 &
        echo $! >"$RUN_DIR/$name.pid"
    )
}

# 記録と実プロセスが一致するか（生存・自身がグループリーダー・グループ内の起動時の目印）
matches_record() {
    local pid=$1 token=$2
    kill -0 "$pid" 2>/dev/null || return 1
    [[ "$(ps -o pgid= -p "$pid" | tr -d ' ')" == "$pid" ]] || return 1
    # npm はプロセス名を書き換えて環境変数が見えなくなるため、同じグループのいずれかに目印があればよい
    # grep -q の早期終了で pipefail が SIGPIPE を拾わないよう、出力を変数に取ってから判定する
    local group_env
    group_env="$(ps -axww -E -o pgid=,command= 2>/dev/null | awk -v g="$pid" '$1 == g')"
    [[ "$group_env" == *"$MARKER_ENV=$token"* ]]
}

load_state() {
    [[ -f "$STATE" ]] || return 1
    # shellcheck disable=SC1090
    source "$STATE"
}

cmd_start() {
    [[ -d "$DEPLOY_ROOT/backend/.venv" ]] || die "backend/.venv がありません。backend で uv sync を実行してください"
    [[ -d "$DEPLOY_ROOT/frontend/node_modules" ]] || die "frontend/node_modules がありません。frontend で npm install を実行してください"
    if load_state; then
        for svc_pid in "${BACKEND_PID:-}" "${FRONTEND_PID:-}"; do
            # PID が再利用された無関係なプロセスは「起動中」とみなさない
            if [[ -n "$svc_pid" ]] && matches_record "$svc_pid" "${TOKEN:-}"; then
                die "既に起動しています。先に scripts/dev-instance.sh stop を実行してください"
            fi
        done
    fi
    mkdir -p "$RUN_DIR"

    local ports backend_port frontend_port args=()
    [[ -n "${DEV_BACKEND_PORT:-}" ]] && args+=(--backend-port "$DEV_BACKEND_PORT")
    [[ -n "${DEV_FRONTEND_PORT:-}" ]] && args+=(--frontend-port "$DEV_FRONTEND_PORT")
    ports="$(cd "$DEPLOY_ROOT/backend" && uv run python -m deep_tracker.config.dev prepare \
        --run-dir "$RUN_DIR" --worktree "$(basename "$DEPLOY_ROOT")" ${args[@]+"${args[@]}"})" || exit 1
    backend_port="$(python3 -I -c 'import json,sys; print(json.load(sys.stdin)["backend_port"])' <<<"$ports")"
    frontend_port="$(python3 -I -c 'import json,sys; print(json.load(sys.stdin)["frontend_port"])' <<<"$ports")"

    local token
    token="$(python3 -I -c 'import secrets; print(secrets.token_hex(8))')"
    : >"$RUN_DIR/backend.log"
    : >"$RUN_DIR/frontend.log"

    # 運用から継承した設定は使わない。NODE_ENV は production だと next dev が HTTP 500 になるため除外する
    local base_env=(env -u NODE_ENV -u BACKEND_URL -u FRONTEND_HOST -u FRONTEND_PORT
        "$MARKER_ENV=$token" DEEP_TRACKER_DEV_MODE=1 DEEP_TRACKER_CONFIG="$RUN_DIR/config.yaml")
    spawn backend "$DEPLOY_ROOT/backend" "${base_env[@]}" uv run python -m deep_tracker.main
    spawn frontend "$DEPLOY_ROOT/frontend" "${base_env[@]}" \
        BACKEND_URL="http://127.0.0.1:$backend_port" FRONTEND_HOST=127.0.0.1 \
        FRONTEND_PORT="$frontend_port" NEXT_DIST_DIR=.next-dev npm run dev

    local backend_pid frontend_pid
    backend_pid="$(cat "$RUN_DIR/backend.pid")"
    frontend_pid="$(cat "$RUN_DIR/frontend.pid")"
    cat >"$STATE" <<STATE_EOF
BACKEND_PID=$backend_pid
BACKEND_PGID=$backend_pid
FRONTEND_PID=$frontend_pid
FRONTEND_PGID=$frontend_pid
BACKEND_PORT=$backend_port
FRONTEND_PORT=$frontend_port
TOKEN=$token
STATE_EOF

    echo "起動しました: backend http://127.0.0.1:$backend_port / frontend http://127.0.0.1:$frontend_port"
    echo "ログ: $RUN_DIR/{backend,frontend}.log"
    # 失敗してもプロセスは残す（ログを確認し、不要なら stop する）
    wait_healthy "$backend_port" "$frontend_port" || exit 1
}

wait_healthy() {
    local backend_port=$1 frontend_port=$2 i
    for i in $(seq 1 60); do
        if curl -fsS "http://127.0.0.1:$backend_port/api/health" 2>/dev/null | grep -q '"status":"ok"' &&
            curl -fsS "http://127.0.0.1:$frontend_port/api/health" 2>/dev/null | grep -q '"status":"ok"'; then
            echo "/api/health: ok"
            return 0
        fi
        sleep 1
    done
    echo "警告: 60秒以内に /api/health が ok になりませんでした。ログを確認してください" >&2
    return 1
}

stop_group() {
    local name=$1 pid=$2 pgid=$3 i
    if ! kill -0 "$pid" 2>/dev/null; then
        echo "$name は起動していません"
        return 0
    fi
    if [[ "$pgid" != "$pid" ]] || ! matches_record "$pid" "$TOKEN"; then
        echo "$name: 記録（pid ${pid}）と実プロセスが一致しないため、停止しません" >&2
        return 1
    fi
    kill -- "-$pgid" 2>/dev/null || true
    for i in $(seq 1 20); do
        kill -0 "$pid" 2>/dev/null || break
        sleep 0.5
    done
    if kill -0 "$pid" 2>/dev/null; then
        kill -KILL -- "-$pgid" 2>/dev/null || true
    fi
    echo "$name を停止しました"
}

cmd_stop() {
    load_state || {
        echo "起動していません"
        return 0
    }
    local rc=0
    stop_group frontend "$FRONTEND_PID" "$FRONTEND_PGID" || rc=1
    stop_group backend "$BACKEND_PID" "$BACKEND_PGID" || rc=1
    if [[ $rc -eq 0 ]]; then
        rm -f "$STATE" "$RUN_DIR"/*.pid
    fi
    return $rc
}

cmd_status() {
    load_state || {
        echo "起動していません"
        return 0
    }
    local svc pid
    for svc in backend frontend; do
        if [[ $svc == backend ]]; then pid=$BACKEND_PID; else pid=$FRONTEND_PID; fi
        if kill -0 "$pid" 2>/dev/null; then echo "$svc: 起動中 (pid $pid)"; else echo "$svc: 停止"; fi
    done
    echo "URL: backend http://127.0.0.1:$BACKEND_PORT / frontend http://127.0.0.1:$FRONTEND_PORT"
    echo "ログ: $RUN_DIR/{backend,frontend}.log"
}

case "${1:-}" in
start) cmd_start ;;
stop) cmd_stop ;;
status) cmd_status ;;
*) die "使い方: scripts/dev-instance.sh start|stop|status" ;;
esac
