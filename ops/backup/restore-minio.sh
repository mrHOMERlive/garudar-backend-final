#!/usr/bin/env bash
# Restore a MinIO documents tarball into a target directory.
#
# Usage: restore-minio.sh <backup-file.tar.gz.age> <target-dir>
#
# By default the target is a fresh dir — operator chooses when to swap
# the live MinIO data dir (/home/documents_s3/) with the restored copy.
# We never overwrite the live MinIO storage automatically.

set -euo pipefail
umask 077

CONFIG=/etc/garudar-backup/config.env
# shellcheck disable=SC1090
source "$CONFIG"

: "${AGE_PRIVATE_KEY_FILE:=/etc/garudar-backup/age-private.key}"

BACKUP="${1:-}"
TARGET="${2:-}"

usage() {
    echo "Usage: $0 <backup-file.tar.gz.age> <target-dir>"
    echo "Example: $0 /var/backups/garudar/minio/daily-20260513.tar.gz.age /tmp/minio-restore"
    exit 64
}

[ -n "$BACKUP" ] && [ -n "$TARGET" ] || usage
[ -f "$BACKUP" ]                || { echo "Backup file not found: $BACKUP" >&2; exit 65; }
[ -f "$AGE_PRIVATE_KEY_FILE" ]  || { echo "Private key not found at $AGE_PRIVATE_KEY_FILE. Copy it from offline storage first." >&2; exit 66; }
command -v age >/dev/null       || { echo "age binary missing" >&2; exit 70; }

if [ -e "$TARGET" ] && [ "$(find "$TARGET" -mindepth 1 -maxdepth 1 | head -n1)" ]; then
    echo "Target $TARGET is not empty. Refusing to overwrite."
    exit 1
fi

mkdir -p "$TARGET"

echo "Decrypting + extracting $BACKUP -> $TARGET ..."
age -d -i "$AGE_PRIVATE_KEY_FILE" "$BACKUP" | tar -xzf - -C "$TARGET"

echo
echo "Restore complete. Inspect with:"
echo "  ls -la $TARGET"
echo
echo "To put it live, stop MinIO container, swap the volume contents, and start MinIO again:"
echo "  docker stop garudar-minio"
echo "  rsync -a --delete $TARGET/ /home/documents_s3/"
echo "  docker start garudar-minio"
