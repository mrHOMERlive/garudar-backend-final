#!/usr/bin/env bash
# Daily backup with GFS retention.
#
# - Always: PostgreSQL pg_dump + MinIO filesystem snapshot, both age-encrypted.
# - Sunday:    promote today's daily to weekly  (hard link, no extra disk).
# - 1st of M:  promote today's daily to monthly (hard link).
# - 1st of Y:  promote today's daily to yearly  (hard link, PostgreSQL only).
# - Then: rotate (delete) old files per retention policy.
# - On any error: email alert via notify.py, exit 1.
#
# Designed to be invoked by cron once per day. Re-entrant runs are blocked
# by flock so manual + scheduled invocations never collide.

set -euo pipefail
umask 077

CONFIG=/etc/garudar-backup/config.env
if [ ! -f "$CONFIG" ]; then
    echo "backup.sh: $CONFIG not found — run install.sh first" >&2
    exit 78
fi
# shellcheck disable=SC1090
source "$CONFIG"

: "${DB_NAME:?DB_NAME missing in config.env}"
: "${BACKUP_ROOT:?BACKUP_ROOT missing in config.env}"
: "${SCRIPT_DIR:?SCRIPT_DIR missing in config.env}"
: "${AGE_PUBLIC_KEY:?AGE_PUBLIC_KEY missing in config.env}"
: "${ALERT_EMAIL:?ALERT_EMAIL missing in config.env}"
: "${MINIO_DATA_DIR:=/home/documents_s3/}"

LOG=/var/log/garudar-backup.log
LOCK=/var/lock/garudar-backup.lock

# Single-instance lock. Exit silently if another run is in progress.
exec 9>"$LOCK"
if ! flock -n 9; then
    echo "[$(date '+%F %T')] backup.sh: another instance is running, exiting" >>"$LOG"
    exit 0
fi

# --- Error handler -----------------------------------------------------------
TMP_FILES=()
cleanup() {
    for f in "${TMP_FILES[@]:-}"; do
        [ -n "$f" ] && [ -e "$f" ] && rm -f "$f" || true
    done
}
on_error() {
    local lineno=$1
    local body
    body="backup.sh aborted at line $lineno (exit $?).
Host: $(hostname)
See $LOG (last 40 lines):
$(tail -n 40 "$LOG" 2>/dev/null || echo '(no log)')"
    python3 "$SCRIPT_DIR/notify.py" \
        --to "$ALERT_EMAIL" \
        --subject "[Garudar] Backup FAILED" \
        --body "$body" || true
    cleanup
    exit 1
}
trap 'on_error $LINENO' ERR
trap cleanup EXIT

log() { echo "[$(date '+%F %T')] $*" >>"$LOG"; }
log "----- backup.sh started -----"

# --- Sanity checks -----------------------------------------------------------
command -v age >/dev/null         || { log "age binary missing";        exit 70; }
command -v pg_dump >/dev/null     || { log "pg_dump binary missing";    exit 70; }
command -v rsync >/dev/null       || { log "rsync binary missing";      exit 70; }
[ -d "$MINIO_DATA_DIR" ]          || { log "MinIO data dir not found: $MINIO_DATA_DIR"; exit 71; }

# Need >2 GiB free in BACKUP_ROOT.
FREE_KB=$(df -P "$BACKUP_ROOT" | awk 'NR==2 {print $4}')
if [ "$FREE_KB" -lt 2097152 ]; then
    log "Insufficient disk space ($FREE_KB KiB free, need >=2 GiB)"
    exit 72
fi

mkdir -p "$BACKUP_ROOT/postgres" "$BACKUP_ROOT/minio/current"

# --- Date markers ------------------------------------------------------------
DOW=$(date +%u)        # 1=Mon .. 7=Sun
DOM=$(date +%d)        # 01-31
MONTH=$(date +%m)      # 01-12
TODAY=$(date +%Y%m%d)
YEARMONTH=$(date +%Y%m)
YEAR=$(date +%Y)

# --- PostgreSQL daily --------------------------------------------------------
PG_TMP="$BACKUP_ROOT/postgres/daily-$TODAY.dump.tmp"
PG_OUT="$BACKUP_ROOT/postgres/daily-$TODAY.dump.age"
TMP_FILES+=("$PG_TMP")

log "pg_dump $DB_NAME -> $PG_OUT"
sudo -u postgres pg_dump \
    --format=custom --compress=9 --no-owner --no-acl \
    "$DB_NAME" >"$PG_TMP"

age -r "$AGE_PUBLIC_KEY" -o "$PG_OUT" "$PG_TMP"
rm -f "$PG_TMP"
chmod 0400 "$PG_OUT"

PG_SIZE=$(stat -c%s "$PG_OUT")
log "pg_dump done ($PG_SIZE bytes)"
bash "$SCRIPT_DIR/upload.sh" "$PG_OUT" >>"$LOG" 2>&1 || log "upload.sh (pg) returned non-zero (non-fatal)"

# --- MinIO daily -------------------------------------------------------------
log "rsync MinIO $MINIO_DATA_DIR -> $BACKUP_ROOT/minio/current/"
rsync -a --delete "$MINIO_DATA_DIR" "$BACKUP_ROOT/minio/current/"

MINIO_OUT="$BACKUP_ROOT/minio/daily-$TODAY.tar.gz.age"
log "tar+age MinIO snapshot -> $MINIO_OUT"
tar -czf - -C "$BACKUP_ROOT/minio/current" . | age -r "$AGE_PUBLIC_KEY" >"$MINIO_OUT"
chmod 0400 "$MINIO_OUT"

MINIO_SIZE=$(stat -c%s "$MINIO_OUT")
log "MinIO snapshot done ($MINIO_SIZE bytes)"
bash "$SCRIPT_DIR/upload.sh" "$MINIO_OUT" >>"$LOG" 2>&1 || log "upload.sh (minio) returned non-zero (non-fatal)"

# --- Promotion via hard links (no extra disk until daily rotates out) --------
promote() {
    local src=$1 dst=$2
    if [ ! -e "$dst" ]; then
        cp -l "$src" "$dst"
        log "promoted $(basename "$src") -> $(basename "$dst")"
    fi
}

if [ "$DOW" = "7" ]; then
    promote "$PG_OUT"    "$BACKUP_ROOT/postgres/weekly-$TODAY.dump.age"
    promote "$MINIO_OUT" "$BACKUP_ROOT/minio/weekly-$TODAY.tar.gz.age"
fi
if [ "$DOM" = "01" ]; then
    promote "$PG_OUT"    "$BACKUP_ROOT/postgres/monthly-$YEARMONTH.dump.age"
    promote "$MINIO_OUT" "$BACKUP_ROOT/minio/monthly-$YEARMONTH.tar.gz.age"
fi
if [ "$DOM" = "01" ] && [ "$MONTH" = "01" ]; then
    promote "$PG_OUT" "$BACKUP_ROOT/postgres/yearly-$YEAR.dump.age"
fi

# --- Rotation ----------------------------------------------------------------
# PostgreSQL
find "$BACKUP_ROOT/postgres/" -maxdepth 1 -name 'daily-*.dump.age'   -mtime +7    -print -delete >>"$LOG" || true
find "$BACKUP_ROOT/postgres/" -maxdepth 1 -name 'weekly-*.dump.age'  -mtime +28   -print -delete >>"$LOG" || true
find "$BACKUP_ROOT/postgres/" -maxdepth 1 -name 'monthly-*.dump.age' -mtime +180  -print -delete >>"$LOG" || true
find "$BACKUP_ROOT/postgres/" -maxdepth 1 -name 'yearly-*.dump.age'  -mtime +2555 -print -delete >>"$LOG" || true

# MinIO (no yearly tier — those tarballs are large)
find "$BACKUP_ROOT/minio/" -maxdepth 1 -name 'daily-*.tar.gz.age'   -mtime +7   -print -delete >>"$LOG" || true
find "$BACKUP_ROOT/minio/" -maxdepth 1 -name 'weekly-*.tar.gz.age'  -mtime +28  -print -delete >>"$LOG" || true
find "$BACKUP_ROOT/minio/" -maxdepth 1 -name 'monthly-*.tar.gz.age' -mtime +180 -print -delete >>"$LOG" || true

log "----- backup.sh finished OK -----"
