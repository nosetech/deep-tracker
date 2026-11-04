#!/bin/bash
# 旧バージョンの展開先から、tarball に含まれない利用者固有の状態（config/config.yaml・DB・.env・logs/）を
# 新バージョンの展開先（このスクリプトの1階層上）へ引き継ぐ。
#
# 使い方:
#   cd <新バージョンの展開先> && ./scripts/migrate.sh <旧バージョンの展開先> [--with-logs] [--force]
#
#   --with-logs  logs/ も引き継ぐ（既定は対象外）
#   --force      新バージョン側に同名ファイルがある場合、<file>.bak-<timestamp> に退避して上書きする
#                （既定はスキップ。何度実行しても安全）
#
# 前提: 新バージョン側で (cd backend && uv sync) を済ませておく（設定の検証・DB検査に使う）。
#
# 引き継ぎ対象:
#   config/config.yaml  YAMLとして検証してからコピーする。instance / ポート / db.path が新旧で
#                       衝突しうるため、並行稼働する場合は変更を促す警告を出す（自動では書き換えない）
#   DB（db.path）        SQLite のオンラインバックアップでコピーする（旧バージョン稼働中でも安全）。
#                       コピー前に Alembic のリビジョンを確認し、新バージョンが対応しない（新しすぎる）
#                       場合はエラーで停止する。古い場合は新バージョンの起動時に自動で引き上げられる
#   .env                LAN_IP / TAILSCALE_IP を引き継ぐ。不正な組み合わせは警告する
#   logs/               --with-logs 指定時のみ
#
# 旧展開先は変更・削除しない。新バージョンの起動は移行後に利用者が行う。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NEW_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON="$NEW_ROOT/backend/.venv/bin/python"
HELPER="$SCRIPT_DIR/_migrate_helper.py"

log() { echo "[migrate] $*"; }
warn() { echo "[migrate] 警告: $*"; }
err() { echo "[migrate] $*" >&2; }

usage() {
    sed -n '2,3p;5,6p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    echo "  --with-logs  logs/ も引き継ぐ"
    echo "  --force      新バージョン側の既存ファイルをバックアップして上書きする（既定はスキップ）"
}

if [[ $# -lt 1 ]]; then
    usage >&2
    exit 1
fi
OLD_ARG="$1"
shift
WITH_LOGS=0
FORCE=0
while [[ $# -gt 0 ]]; do
    case "$1" in
    --with-logs) WITH_LOGS=1 ;;
    --force) FORCE=1 ;;
    -h | --help)
        usage
        exit 0
        ;;
    *)
        err "不明なオプション: $1"
        usage >&2
        exit 1
        ;;
    esac
    shift
done

[[ -d "$OLD_ARG" ]] || {
    err "旧バージョンの展開先が見つかりません: $OLD_ARG"
    exit 1
}
OLD_ROOT="$(cd "$OLD_ARG" && pwd)"
if [[ "$OLD_ROOT" == "$NEW_ROOT" ]]; then
    err "旧バージョンと新バージョンの展開先が同一です: $OLD_ROOT"
    exit 1
fi
[[ -x "$PYTHON" ]] || {
    err "backend/.venv が見つかりません。先に (cd backend && uv sync) を実行してください"
    exit 1
}

log "移行元: $OLD_ROOT"
log "移行先: $NEW_ROOT"

# 移行先に既にあるファイルを処理する。コピーしてよければ 0、スキップなら 1 を返す
prepare_dst() {
    local dst="$1" label="$2"
    if [[ -e "$dst" ]]; then
        if [[ "$FORCE" -ne 1 ]]; then
            log "スキップ: ${label}（移行先に既に存在します。上書きするには --force: ${dst}）"
            return 1
        fi
        local backup="$dst.bak-$(date +%Y%m%d-%H%M%S)"
        mv "$dst" "$backup"
        log "移行先の既存ファイルを退避: $backup"
    fi
    mkdir -p "$(dirname "$dst")"
}

copy_file() {
    local src="$1" dst="$2" label="$3"
    if [[ ! -f "$src" ]]; then
        log "スキップ: ${label}（移行元に存在しません）"
        return 0
    fi
    prepare_dst "$dst" "$label" || return 0
    cp "$src" "$dst"
    log "コピー完了: $label"
}

# --- config/config.yaml ---
OLD_CONFIG="$OLD_ROOT/config/config.yaml"
NEW_CONFIG="$NEW_ROOT/config/config.yaml"
OLD_DB_RAW=""
if [[ -f "$OLD_CONFIG" ]]; then
    if ! info="$(cd "$NEW_ROOT/backend" && "$PYTHON" "$HELPER" validate-config "$OLD_CONFIG")"; then
        err "config/config.yaml の検証に失敗しました。移行を中止します: $OLD_CONFIG"
        exit 1
    fi
    OLD_DB_RAW="$(sed -n 's/^db_path=//p' <<<"$info")"
    copy_file "$OLD_CONFIG" "$NEW_CONFIG" "config/config.yaml"
    if [[ -f "$NEW_CONFIG" ]] && cmp -s "$OLD_CONFIG" "$NEW_CONFIG"; then
        warn "instance / backend.port / frontend.port / db.path は旧バージョンと同じ値です。"
        warn "旧バージョンを並行稼働する場合は、$NEW_CONFIG でこれらを変更してください（自動では書き換えません）。"
        sed -n 's/^\(instance\|backend_port\|frontend_port\|db_path\)=/  現在値: \1=/p' <<<"$info"
    fi
    (cd "$NEW_ROOT/backend" && "$PYTHON" "$HELPER" config-diff "$OLD_CONFIG" "$NEW_ROOT/config/config.yaml.example") |
        sed 's/^/[migrate] ヒント: /' || true
else
    log "スキップ: config/config.yaml（移行元に存在しません）"
fi

# --- DB ---
resolve_path() { # 相対パスは展開先ルート基準（~ は展開する）
    local p="$1" root="$2"
    p="${p/#\~/$HOME}"
    [[ "$p" == /* ]] && echo "$p" || echo "$root/$p"
}
OLD_DB="$(resolve_path "${OLD_DB_RAW:-data/deep-tracker.db}" "$OLD_ROOT")"
NEW_DB_RAW="data/deep-tracker.db"
if [[ -f "$NEW_CONFIG" ]]; then
    NEW_DB_RAW="$(cd "$NEW_ROOT/backend" && "$PYTHON" "$HELPER" validate-config "$NEW_CONFIG" | sed -n 's/^db_path=//p')"
fi
NEW_DB="$(resolve_path "$NEW_DB_RAW" "$NEW_ROOT")"

if [[ -f "$OLD_DB" ]]; then
    if [[ "$OLD_DB" == "$NEW_DB" ]]; then
        warn "DB のパスが新旧で同一です（${OLD_DB}）。コピーしません。並行稼働するなら db.path を分けてください"
    else
        state="$(cd "$NEW_ROOT/backend" && "$PYTHON" "$HELPER" db-state "$OLD_DB")"
        case "$state" in
        NEWER*)
            err "DB のスキーマ（${state#NEWER }）が、この新バージョンの対応する範囲より新しいため、移行を中止します。"
            err "新しいバージョンから古いバージョンへの移行はできません。"
            exit 1
            ;;
        OLD*) log "DB のスキーマは古い版（${state#OLD }）です。新バージョンの起動時に自動で最新へ引き上げられます" ;;
        esac
        if prepare_dst "$NEW_DB" "DB"; then
            "$PYTHON" "$HELPER" backup "$OLD_DB" "$NEW_DB"
            log "コピー完了: DB -> $NEW_DB"
        fi
    fi
else
    log "スキップ: DB（移行元に存在しません: ${OLD_DB}）"
fi

# --- .env ---
if [[ -f "$OLD_ROOT/.env" ]]; then
    if grep -Eq '^[[:space:]]*LAN_IP=[^[:space:]]' "$OLD_ROOT/.env" &&
        grep -Eq '^[[:space:]]*TAILSCALE_IP=[^[:space:]]' "$OLD_ROOT/.env"; then
        warn "移行元の .env は LAN_IP と TAILSCALE_IP を同時に指定しています（起動時にエラーになります）。どちらか一方にしてください"
    fi
    copy_file "$OLD_ROOT/.env" "$NEW_ROOT/.env" ".env"
    warn "LAN_IP / TAILSCALE_IP はネットワーク環境に依存します。移行後に値が正しいか確認してください"
else
    log "スキップ: .env（移行元に存在しません）"
fi

# --- logs/ ---
if [[ "$WITH_LOGS" -eq 1 ]]; then
    if [[ -d "$OLD_ROOT/logs" ]]; then
        mkdir -p "$NEW_ROOT/logs"
        cp -R "$OLD_ROOT/logs/." "$NEW_ROOT/logs/"
        log "コピー完了: logs/"
    else
        log "スキップ: logs/（移行元に存在しません）"
    fi
else
    log "スキップ: logs/（--with-logs 未指定）"
fi

cat <<EOF

[migrate] 移行が完了しました。次の手順で新バージョンを起動してください。
  1. $NEW_ROOT/config/config.yaml を確認する（並行稼働なら instance / ポート / db.path を変える）
  2. cd $NEW_ROOT && scripts/fetch-job.sh install && scripts/summary-job.sh install
  3. 常時起動する場合: scripts/service.sh install（手動なら scripts/start.sh）
  旧バージョンのジョブを止める場合は、旧展開先で次を実行する:
     scripts/service.sh uninstall && scripts/fetch-job.sh uninstall && scripts/summary-job.sh uninstall
  注意: launchd ジョブ名に instance が含まれます。instance が旧バージョンと同じ場合、
        install すると旧バージョンのジョブを新しい展開先のもので上書きします。
EOF
