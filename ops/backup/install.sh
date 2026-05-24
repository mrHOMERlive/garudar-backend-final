#!/usr/bin/env bash
# One-time setup of the backup system on the production VPS.
# Re-runnable: detects existing state and skips already-completed steps.
#
# Run as root:
#   sudo bash ops/backup/install.sh
#
# What it does:
#   1. Install apt deps (age, postgresql-client, rsync).
#   2. Create /var/backups/garudar/{postgres,minio,configs}, /var/log file.
#   3. Generate an age key pair if none exists yet. PRIVATE KEY IS PRINTED
#      ONCE to the terminal — operator must save it offline, then confirm.
#   4. Place /etc/garudar-backup/config.env (from example template) if absent.
#   5. Install /etc/cron.d/garudar-backup.
#   6. Print next steps.

set -euo pipefail

if [ "$EUID" -ne 0 ]; then
    echo "Run as root: sudo bash $0" >&2
    exit 1
fi

# Resolve the directory this script lives in, so cron entries use absolute paths.
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)
echo "install.sh: script dir = $SCRIPT_DIR"

# Гарантируем execute-bit для всех .sh в этой папке. На Windows-машинах git
# по умолчанию не трекает chmod на новых файлах, поэтому после `git clone`
# или `git pull` на Linux-проде шеллы могут оказаться без `x`-флага. Без
# этого `sudo <script>` падает с "command not found", а cron — silently
# (произошло на прод-сервере 2026-05-24, см. ops/backup/README.md).
chmod +x "$SCRIPT_DIR"/*.sh

# --- 1. apt dependencies -----------------------------------------------------
echo
echo "[1/6] Installing apt dependencies (age, postgresql-client-N matching server, rsync)..."
apt-get update -qq

# Определить версию установленного PostgreSQL-сервера (если есть),
# чтобы поставить совпадающий по версии postgresql-client-N. Метапакет
# `postgresql-client` из pgdg-репо всегда указывает на latest — это бы
# поставило client-18 на сервер 16 и приводило к лишним предупреждениям /
# несовместимостям при future-апгрейдах. Авто-детект делает поведение
# скрипта стабильным независимо от текущего «latest» в pgdg.
PG_SERVER_VERSION=$(dpkg-query -W -f='${binary:Package}\n' 'postgresql-[0-9]*' 2>/dev/null \
    | grep -oE 'postgresql-[0-9]+' | grep -oE '[0-9]+$' | sort -n | tail -1)
PG_CLIENT_PACKAGE="postgresql-client-${PG_SERVER_VERSION:-16}"
echo "    Target postgres-client package: $PG_CLIENT_PACKAGE (matching server v${PG_SERVER_VERSION:-16})"

# Ставим ТОЛЬКО недостающие пакеты. Это уважает `apt-mark hold` на уже
# установленных версиях (`apt install -y` иначе пытается апгрейд и падает
# с «Held packages were changed and -y was used without --allow-change-held-packages»).
# Заодно делает re-run скрипта идемпотентным.
#
# Используем dpkg-query с явной проверкой статуса «install ok installed»,
# чтобы НЕ принять half-configured / removed-but-config-left состояния за
# нормально установленный пакет — такие сломанные пакеты нужно
# переустановить, чтобы скрипт точно работал.
is_installed() {
    dpkg-query -W -f='${Status}' "$1" 2>/dev/null | grep -q '^install ok installed$'
}

MISSING_PKGS=()
for pkg in age "$PG_CLIENT_PACKAGE" rsync; do
    if ! is_installed "$pkg"; then
        MISSING_PKGS+=("$pkg")
    fi
done
if [ ${#MISSING_PKGS[@]} -gt 0 ]; then
    echo "    Installing missing packages: ${MISSING_PKGS[*]}"
    apt-get install -y -qq "${MISSING_PKGS[@]}"
else
    echo "    All required packages already installed; skipping apt-get install."
fi

# --- 2. Directories ----------------------------------------------------------
echo
echo "[2/6] Creating backup directories..."
install -d -m 0700 -o root -g root /var/backups/garudar
install -d -m 0700 -o root -g root /var/backups/garudar/postgres
install -d -m 0700 -o root -g root /var/backups/garudar/minio
install -d -m 0700 -o root -g root /var/backups/garudar/configs
install -d -m 0700 -o root -g root /etc/garudar-backup
touch /var/log/garudar-backup.log
chmod 0600 /var/log/garudar-backup.log

# --- 3. age key pair ---------------------------------------------------------
echo
echo "[3/6] age key pair..."
CONFIG=/etc/garudar-backup/config.env
EXAMPLE=$SCRIPT_DIR/config.env.example

EXISTING_PUB=""
if [ -f "$CONFIG" ] && grep -qE '^AGE_PUBLIC_KEY=age1[a-z0-9]+' "$CONFIG"; then
    EXISTING_PUB=$(grep -E '^AGE_PUBLIC_KEY=' "$CONFIG" | head -n1 | cut -d= -f2)
fi

if [ -n "$EXISTING_PUB" ]; then
    echo "    age public key already in $CONFIG, skipping key generation."
    echo "    Existing public key: $EXISTING_PUB"
else
    KEYFILE=$(mktemp --suffix=.age-key)
    # age 1.0.0 (Ubuntu jammy) при `-o` отказывается перезаписать существующий
    # файл (mktemp его уже создал) и при этом возвращает exit code 0 — ловушка
    # для `set -euo pipefail`. Используем stdout-режим: shell-redirect `>`
    # truncate'ит и заполняет файл сам, обходя баг.
    if ! age-keygen 2>/dev/null > "$KEYFILE"; then
        echo "    age-keygen failed to generate key" >&2
        rm -f "$KEYFILE"
        exit 73
    fi
    PUB=$(grep '# public key:' "$KEYFILE" | awk '{print $NF}')
    if [ -z "$PUB" ]; then
        echo "    age-keygen succeeded but produced no public key in $KEYFILE" >&2
        rm -f "$KEYFILE"
        exit 74
    fi

    cat <<EOF

================================================================================
  age private key generated. SAVE THIS TO OFFLINE STORAGE NOW.

  - Print on paper and store in a safe, OR
  - Store in a password manager that you control, OR
  - Both (preferred — paper survives password manager loss).

  WITHOUT THIS KEY, NONE OF YOUR BACKUPS CAN BE DECRYPTED.

  Private key file contents:

$(cat "$KEYFILE")

  Public key (will be saved to $CONFIG): $PUB
================================================================================

EOF
    read -r -p "Have you saved the private key offline? Type 'yes' to continue: " confirm
    if [ "$confirm" != "yes" ]; then
        shred -u "$KEYFILE"
        echo "Aborted. Private key has been shredded. Re-run install.sh when ready."
        exit 1
    fi

    # Wipe key file from disk (best-effort: shred on ext4 helps but isn't foolproof on COW FS).
    shred -u "$KEYFILE"
    echo "    Private key file removed from $KEYFILE."

    # Write/refresh config file from example, fill in AGE_PUBLIC_KEY.
    if [ ! -f "$CONFIG" ]; then
        cp "$EXAMPLE" "$CONFIG"
    fi
    if grep -qE '^AGE_PUBLIC_KEY=' "$CONFIG"; then
        sed -i "s|^AGE_PUBLIC_KEY=.*$|AGE_PUBLIC_KEY=$PUB|" "$CONFIG"
    else
        echo "AGE_PUBLIC_KEY=$PUB" >>"$CONFIG"
    fi
    chmod 0600 "$CONFIG"
    echo "    Public key written to $CONFIG."
fi

# --- 4. config.env from template if not present ------------------------------
echo
echo "[4/6] config.env..."
if [ ! -f "$CONFIG" ]; then
    cp "$EXAMPLE" "$CONFIG"
    chmod 0600 "$CONFIG"
    echo "    Created $CONFIG from template. EDIT IT BEFORE FIRST BACKUP RUN."
else
    echo "    $CONFIG already exists, leaving in place."
fi

# Ensure SCRIPT_DIR is set in config (use absolute path detected above).
if grep -qE '^SCRIPT_DIR=' "$CONFIG"; then
    sed -i "s|^SCRIPT_DIR=.*$|SCRIPT_DIR=$SCRIPT_DIR|" "$CONFIG"
else
    echo "SCRIPT_DIR=$SCRIPT_DIR" >>"$CONFIG"
fi

# --- 5. Cron -----------------------------------------------------------------
echo
echo "[5/6] Installing /etc/cron.d/garudar-backup..."
cat >/etc/cron.d/garudar-backup <<EOF
# Garudar automated backups. Times are in the server's local timezone.
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# Daily snapshot @ 02:00 (PostgreSQL + MinIO + promotion + rotation).
0 2 * * * root $SCRIPT_DIR/backup.sh

# Weekly host configs @ Sunday 03:00 (NPM data, letsencrypt, .env).
0 3 * * 0 root $SCRIPT_DIR/backup-configs.sh

# Monthly self-test of restore @ 1st of month, 04:00.
# Commented out by default: enable only after AGE_PRIVATE_KEY_FILE is in place
# (either on this host briefly, or on a dedicated test box).
#0 4 1 * * root $SCRIPT_DIR/test-restore.sh
EOF
chmod 0644 /etc/cron.d/garudar-backup
echo "    cron installed."

# --- 6. Final message --------------------------------------------------------
cat <<EOF

[6/6] Done.

Next steps:

  1. Edit $CONFIG and fill in DB_NAME, SMTP_PASSWORD, MINIO_DATA_DIR (if not default),
     INFRA_DIR (where the host docker-compose.yml lives), ALERT_EMAIL.

  2. Run the first daily backup manually to verify:
       sudo bash $SCRIPT_DIR/backup.sh
       ls -lh /var/backups/garudar/postgres/

  3. Test a restore into a throwaway DB:
       # (copy your offline private key to /etc/garudar-backup/age-private.key first)
       sudo bash $SCRIPT_DIR/restore-postgres.sh \\
           /var/backups/garudar/postgres/daily-\$(date +%Y%m%d).dump.age \\
           garudar_restore_test
       # then shred the private key file when done:
       sudo shred -u /etc/garudar-backup/age-private.key

  4. After 1 week, verify cron is producing 7 daily files in postgres/ and minio/.

  5. When off-site destination is decided, edit upload.sh.

  See ops/backup/README.md and INSTALL.md for full documentation.
EOF
