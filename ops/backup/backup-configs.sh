#!/usr/bin/env bash
# Weekly backup of host-side configuration that is NOT in git:
#   - Nginx Proxy Manager /data and /letsencrypt
#   - .env files (backend, infra)
#
# Output: a single age-encrypted tarball per run, kept for 90 days.

set -euo pipefail
umask 077

CONFIG=/etc/garudar-backup/config.env
# shellcheck disable=SC1090
source "$CONFIG"

: "${BACKUP_ROOT:?BACKUP_ROOT missing}"
: "${AGE_PUBLIC_KEY:?AGE_PUBLIC_KEY missing}"
: "${ALERT_EMAIL:?ALERT_EMAIL missing}"
: "${SCRIPT_DIR:?SCRIPT_DIR missing}"
: "${INFRA_DIR:?INFRA_DIR missing — set to host directory containing the NPM docker-compose.yml}"

LOG=/var/log/garudar-backup.log

on_error() {
    python3 "$SCRIPT_DIR/notify.py" \
        --to "$ALERT_EMAIL" \
        --subject "[Garudar] Config backup FAILED" \
        --body "backup-configs.sh failed on $(hostname). See $LOG." || true
    exit 1
}
trap on_error ERR

log() { echo "[$(date '+%F %T')] [configs] $*" >>"$LOG"; }
log "----- backup-configs.sh started -----"

mkdir -p "$BACKUP_ROOT/configs"
TODAY=$(date +%Y%m%d)
OUT="$BACKUP_ROOT/configs/configs-$TODAY.tar.gz.age"

# Build a list of paths that exist (skip any that don't, but warn).
PATHS=()
add_path() {
    if [ -e "$1" ]; then
        PATHS+=("$1")
    else
        log "skip missing path: $1"
    fi
}

add_path "$INFRA_DIR/data"
add_path "$INFRA_DIR/letsencrypt"
add_path "$INFRA_DIR/docker-compose.yml"
add_path "$SCRIPT_DIR/../../.env"          # backend .env (relative to ops/backup/)

if [ "${#PATHS[@]}" -eq 0 ]; then
    log "no config paths exist — nothing to back up"
    exit 0
fi

log "tar+age ${#PATHS[@]} path(s) -> $OUT"
tar -czf - "${PATHS[@]}" 2>>"$LOG" | age -r "$AGE_PUBLIC_KEY" >"$OUT"
chmod 0400 "$OUT"
log "configs snapshot done ($(stat -c%s "$OUT") bytes)"

bash "$SCRIPT_DIR/upload.sh" "$OUT" >>"$LOG" 2>&1 || log "upload.sh (configs) returned non-zero (non-fatal)"

# Retain configs for 90 days.
find "$BACKUP_ROOT/configs/" -maxdepth 1 -name 'configs-*.tar.gz.age' -mtime +90 -print -delete >>"$LOG" || true

log "----- backup-configs.sh finished OK -----"
