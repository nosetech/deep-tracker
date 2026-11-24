#!/bin/bash
# scripts/start.sh で起動した frontend / backend を停止する（frontend_stop.sh → backend_stop.sh）。
# 未起動でもエラーにしない。片方が失敗してももう片方は停止し、いずれか失敗なら非0で終了する。
dir="$(dirname "${BASH_SOURCE[0]}")"
rc=0
"$dir/frontend_stop.sh" || rc=1
"$dir/backend_stop.sh" || rc=1
exit "$rc"
