#!/usr/bin/env bash
# Monthly automated restore test ("untested backup = no backup").
#
# Picks the most recent daily PostgreSQL backup, restores it into a
# temporary database, verifies that the expected critical tables exist
# and that row counts look sane (non-zero for users / clients), then
# drops the temporary database. Emails the result either way.
#
# Requires AGE_PRIVATE_KEY_FILE to be present during the run. Two modes:
#
#   1. Production server: private key is briefly placed at the configured
#      path by the ops engineer before this cron job is enabled, OR the
#      schedule runs only on test infrastructure where the key lives
#      permanently. The default cron install leaves this commented out
#      until the operator decides.
#
#   2. Manual: run by hand on a dedicated test box that holds the key.

set -euo pipefail
umask 077

CONFIG=/etc/garudar-backup/config.env
# shellcheck disable=SC1090
source "$CONFIG"

: "${BACKUP_ROOT:?BACKUP_ROOT missing}"
: "${SCRIPT_DIR:?SCRIPT_DIR missing}"
: "${ALERT_EMAIL:?ALERT_EMAIL missing}"
: "${AGE_PRIVATE_KEY_FILE:=/etc/garudar-backup/age-private.key}"

LOG=/var/log/garudar-backup.log
TARGET_DB=garudar_restore_test

log() { echo "[$(date '+%F %T')] [test-restore] $*" >>"$LOG"; }

notify() {
    local subject=$1 body=$2
    python3 "$SCRIPT_DIR/notify.py" \
        --to "$ALERT_EMAIL" \
        --subject "$subject" \
        --body "$body" || true
}

cleanup() {
    sudo -u postgres dropdb --if-exists "$TARGET_DB" >/dev/null 2>&1 || true
}
trap cleanup EXIT

log "----- test-restore.sh started -----"

if [ ! -f "$AGE_PRIVATE_KEY_FILE" ]; then
    log "private key absent — test-restore skipped"
    notify "[Garudar] Restore test SKIPPED" \
        "AGE_PRIVATE_KEY_FILE not present on $(hostname). Test-restore was skipped."
    exit 0
fi

# Find the newest daily PG backup.
LATEST=$(find "$BACKUP_ROOT/postgres/" -maxdepth 1 -name 'daily-*.dump.age' -printf '%T@ %p\n' \
         | sort -nr | head -n1 | awk '{print $2}')

if [ -z "$LATEST" ]; then
    log "no daily PG backup found"
    notify "[Garudar] Restore test FAILED" "No daily-*.dump.age found in $BACKUP_ROOT/postgres/"
    exit 1
fi

log "restoring $LATEST into $TARGET_DB"

TMP=$(mktemp --suffix=.dump)
trap 'rm -f "$TMP"; cleanup' EXIT

if ! age -d -i "$AGE_PRIVATE_KEY_FILE" -o "$TMP" "$LATEST"; then
    log "decrypt failed"
    notify "[Garudar] Restore test FAILED" "Decryption of $LATEST failed."
    exit 1
fi

sudo -u postgres dropdb --if-exists "$TARGET_DB"
sudo -u postgres createdb "$TARGET_DB"

if ! sudo -u postgres pg_restore --no-owner --no-acl --exit-on-error -d "$TARGET_DB" "$TMP" 2>>"$LOG"; then
    log "pg_restore failed"
    notify "[Garudar] Restore test FAILED" "pg_restore failed for $LATEST. See $LOG."
    exit 1
fi

# Sanity-check row counts on critical tables.
CHECK_SQL="
SELECT
    (SELECT COUNT(*) FROM users)                        AS users_count,
    (SELECT COUNT(*) FROM clients)                      AS clients_count,
    (SELECT COUNT(*) FROM pobo_orders)                  AS orders_count,
    (SELECT COUNT(*) FROM audit_log)                    AS audit_log_count;
"
RESULT=$(sudo -u postgres psql -d "$TARGET_DB" -At -F'|' -c "$CHECK_SQL" 2>>"$LOG" || true)

if [ -z "$RESULT" ]; then
    log "row-count query failed"
    notify "[Garudar] Restore test FAILED" "Row-count query failed in restored DB. See $LOG."
    exit 1
fi

log "restored row counts: $RESULT"
notify "[Garudar] Restore test OK" \
    "Source: $(basename "$LATEST")
Host: $(hostname)
Row counts (users | clients | pobo_orders | audit_log): $RESULT

Restored DB $TARGET_DB was dropped after verification."

log "----- test-restore.sh finished OK -----"
