#!/bin/bash
# frontend だけを停止する。未起動でもエラーにしない。
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
load_config
stop_service frontend
