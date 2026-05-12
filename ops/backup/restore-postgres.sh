#!/usr/bin/env bash
# Restore a PostgreSQL backup into a target database.
#
# Usage: restore-postgres.sh <backup-file.dump.age> <target-db-name>
#
# Requirements (intentional — restoration is meant to be a deliberate act):
#   - age private key present at the path given by AGE_PRIVATE_KEY_FILE in
#     config.env (default /etc/garudar-backup/age-private.key). The key is
#     NOT kept on the server during normal operation; copy it from offline
#     storage just before restore, and shred it afterwards.
#   - target DB will be DROPPED and recreated. Never aim at the live DB
#     unless you really mean it.

set -euo pipefail
umask 077

CONFIG=/etc/garudar-backup/config.env
# shellcheck disable=SC1090
source "$CONFIG"

: "${AGE_PRIVATE_KEY_FILE:=/etc/garudar-backup/age-private.key}"

BACKUP="${1:-}"
TARGET="${2:-}"

usage() {
    echo "Usage: $0 <backup-file.dump.age> <target-db-name>"
    echo "Example: $0 /var/backups/garudar/postgres/daily-20260513.dump.age garudar_restore_test"
    exit 64
}

[ -n "$BACKUP" ] && [ -n "$TARGET" ] || usage
[ -f "$BACKUP" ]                || { echo "Backup file not found: $BACKUP" >&2; exit 65; }
[ -f "$AGE_PRIVATE_KEY_FILE" ]  || { echo "Private key not found at $AGE_PRIVATE_KEY_FILE. Copy it from offline storage first." >&2; exit 66; }
command -v age >/dev/null       || { echo "age binary missing" >&2; exit 70; }

# Refuse to overwrite the live DB unless the operator types its name twice.
if [ "$TARGET" = "${DB_NAME:-}" ]; then
    echo
    echo "WARNING: target DB '$TARGET' is the LIVE production database (DB_NAME from config.env)."
    read -r -p "Type the DB name again to confirm DROP + RESTORE: " confirm
    if [ "$confirm" != "$TARGET" ]; then
        echo "Aborted."
        exit 1
    fi
fi

TMP=$(mktemp --suffix=.dump)
trap 'rm -f "$TMP"' EXIT

echo "Decrypting $BACKUP ..."
age -d -i "$AGE_PRIVATE_KEY_FILE" -o "$TMP" "$BACKUP"

echo "Dropping and recreating $TARGET ..."
sudo -u postgres dropdb --if-exists "$TARGET"
sudo -u postgres createdb "$TARGET"

echo "Restoring into $TARGET ..."
sudo -u postgres pg_restore --no-owner --no-acl --exit-on-error -d "$TARGET" "$TMP"

echo
echo "Restore complete. Verify with:"
echo "  sudo -u postgres psql $TARGET -c '\\dt'"
