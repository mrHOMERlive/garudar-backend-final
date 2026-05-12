#!/usr/bin/env bash
# Off-site upload for a single backup file.
#
# Status: PLACEHOLDER (2026-05-13).
# Off-site destination is pending a decision with the customer (Backblaze B2,
# Wasabi, second VPS, etc). Once decided, replace the body of this script
# with the actual upload command — no other file in ops/backup/ needs to
# change.
#
# Examples for future implementation:
#
#   # Backblaze B2 via rclone
#   rclone copy "$1" b2:garudar-backups/ --b2-hard-delete
#
#   # AWS S3-compatible (Wasabi/AWS/MinIO)
#   aws --endpoint-url "$OFFSITE_ENDPOINT" s3 cp "$1" "s3://$OFFSITE_BUCKET/"
#
#   # MinIO Client
#   mc cp "$1" "garudar-offsite/$OFFSITE_BUCKET/"
#
# The caller (backup.sh) treats upload.sh failures as NON-FATAL — local
# backup still succeeds. When off-site goes live, optionally tighten that.

set -euo pipefail

FILE="${1:-}"

if [ -z "$FILE" ]; then
    echo "upload.sh: no file provided" >&2
    exit 64
fi

if [ ! -f "$FILE" ]; then
    echo "upload.sh: file not found: $FILE" >&2
    exit 65
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] upload.sh: off-site destination not configured yet; skipping upload of $FILE"
exit 0
