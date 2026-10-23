#!/bin/bash
# scripts/start.sh で起動した frontend / backend を停止する。未起動でもエラーにしない。
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
load_config

# uv / npm は子プロセスを起こすので、子孫を先に止めてから親を止める
kill_tree() {
    local pid=$1 child
    for child in $(pgrep -P "$pid" 2>/dev/null || true); do
        kill_tree "$child"
    done
    kill "$pid" 2>/dev/null || true
}

for svc in frontend backend; do
    if is_running "$svc"; then
        kill_tree "$(cat "$(pid_file "$svc")")"
        echo "$svc を停止しました"
    else
        echo "$svc は起動していません"
    fi
    rm -f "$(pid_file "$svc")"
done
