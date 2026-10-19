#!/bin/bash
# frontend（Next.js）を設定ファイルの待ち受けホスト・ポートで起動する。
#
# 使い方: scripts/frontend.sh {dev|start}
#   dev    開発サーバを起動する（next dev）
#   start  ビルド済みの本番サーバを起動する（next start。事前に npm run build が必要）
#
# 待ち受けは config.yaml の frontend.host / frontend.port、中継先のバックエンドは backend.port から決まる。
# 既定は 127.0.0.1。LAN公開する場合は frontend.host を 0.0.0.0 にして再起動する。
set -euo pipefail

DEPLOY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$DEPLOY_ROOT/backend/.venv/bin/python"

if [[ ! -x "$PYTHON" ]]; then
    echo "backend/.venv が見つかりません。先に (cd backend && uv sync) を実行してください" >&2
    exit 1
fi

case "${1:-}" in
dev | start) ;;
*)
    echo "使い方: $0 {dev|start}" >&2
    exit 2
    ;;
esac

# 設定ファイルの値を取得する（不正な設定ならここで失敗する）
SETTINGS="$(cd "$DEPLOY_ROOT/backend" && "$PYTHON" -m deep_tracker.config)"
eval "$SETTINGS"

# バックエンドは常に 127.0.0.1 で待ち受けるため、中継先も固定する
export BACKEND_URL="${BACKEND_URL:-http://127.0.0.1:${BACKEND_PORT}}"

if [[ "$FRONTEND_HOST" == "0.0.0.0" ]]; then
    echo "警告: LAN公開で起動します（認証なし）。信頼できるネットワーク/VPN内でのみ使ってください" >&2
fi

cd "$DEPLOY_ROOT/frontend"
exec npx next "$1" -H "$FRONTEND_HOST" -p "$FRONTEND_PORT"
