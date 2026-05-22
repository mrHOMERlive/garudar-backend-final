# Installing the Garudar backup system on the production VPS

Estimated time: **30 minutes** (most of it spent saving the age private key
to offline storage).

Prerequisites:

- Root access to the Garudar production VPS.
- An offline place to store the age private key (paper + password manager
  is the recommended combination).
- The Gmail app password for `info@garudar.id` (used by `notify.py`).

## Step 1 — pull the latest code

```bash
ssh root@<production-vps>
cd /home/.../clear-garudar-backend
git pull
ls ops/backup/                 # confirm files arrived
```

## Step 2 — run install.sh

```bash
sudo bash ops/backup/install.sh
```

The script will:

1. `apt install age postgresql-client rsync`.
2. Create `/var/backups/garudar/` and `/etc/garudar-backup/`.
3. Generate an age key pair, print the private key, and wait for you to
   save it offline. **READ AND SAVE THE PRIVATE KEY BEFORE TYPING `yes`.**
4. Place the public key into `/etc/garudar-backup/config.env`.
5. Install `/etc/cron.d/garudar-backup`.

### Saving the private key

When the install script prints the key, do all of the following before
continuing:

- Copy the key block into a password manager you control
  (e.g. 1Password, Bitwarden, KeePassXC) under an item named
  *"Garudar backup age private key"*.
- Print the key onto paper. Place it in a physically secure location
  (locked drawer, safe). Two paper copies in two locations is better
  than one.
- Optional: encrypt the key with a long passphrase (`age -p`) and email
  the ciphertext to yourself; ensure the passphrase is also in your
  password manager.

The script will **shred** the on-disk copy as soon as you confirm.

## Step 3 — edit the config

```bash
sudo nano /etc/garudar-backup/config.env
```

Fill in:

- `DB_NAME` — name of your live PostgreSQL database.
- `MINIO_DATA_DIR` — leave default (`/home/documents_s3/`) unless you
  changed the MinIO mount in `docker-compose.yml`.
- `INFRA_DIR` — absolute path of the directory that contains the *host-side*
  `docker-compose.yml` (the one that runs NPM, pgadmin, and the frontends).
  Example: `/home/garudar-ops/`.
- `SMTP_PASSWORD` — the same Gmail app password your application uses.
- `ALERT_EMAIL` — where backup-failure alerts go. Default `info@garudar.id`.

Confirm permissions:

```bash
sudo ls -l /etc/garudar-backup/config.env
# -rw------- 1 root root ... config.env
```

## Step 4 — first manual backup

```bash
sudo bash /home/.../clear-garudar-backend/ops/backup/backup.sh
```

Verify:

```bash
sudo ls -lh /var/backups/garudar/postgres/
# daily-YYYYMMDD.dump.age, mode 0400

sudo ls -lh /var/backups/garudar/minio/
# daily-YYYYMMDD.tar.gz.age, mode 0400 (size depends on documents)

sudo tail /var/log/garudar-backup.log
# should end with "backup.sh finished OK"
```

Encryption sanity check:

```bash
sudo head -c 40 /var/backups/garudar/postgres/daily-*.dump.age | head
# expect output starting with "age-encryption.org/v1"
```

## Step 5 — restore drill

This step requires the private key to be on the server briefly.

```bash
# Copy your offline private key onto the server.
# (Paste contents into a heredoc or scp it in.)
sudo install -m 0600 -o root -g root \
    /path/to/your/key.age-key /etc/garudar-backup/age-private.key

# Restore the most recent daily into a throwaway DB.
sudo bash /home/.../clear-garudar-backend/ops/backup/restore-postgres.sh \
    "$(ls -1t /var/backups/garudar/postgres/daily-*.dump.age | head -1)" \
    garudar_restore_test

# Spot-check.
sudo -u postgres psql garudar_restore_test -c '\dt' | head -20
sudo -u postgres psql garudar_restore_test -c 'SELECT COUNT(*) FROM users;'

# Drop the test DB.
sudo -u postgres dropdb garudar_restore_test

# Shred the private key so it is no longer on the live server.
sudo shred -u /etc/garudar-backup/age-private.key
```

## Step 6 — trigger an alert email

Simulate failure to verify alerting:

```bash
# Point BACKUP_ROOT at a non-existent path; backup.sh should fail and email.
sudo BACKUP_ROOT=/nonexistent bash /home/.../clear-garudar-backend/ops/backup/backup.sh
```

Check the inbox of `ALERT_EMAIL` for *"[Garudar] Backup FAILED"*.

## Step 7 — let cron take over

```bash
sudo cat /etc/cron.d/garudar-backup
# verify schedule

systemctl status cron
# verify cron daemon is running
```

After tomorrow's 02:00 run, the first scheduled backup will appear in
`/var/log/garudar-backup.log` and a new `daily-*.dump.age` will be in
`/var/backups/garudar/postgres/`.

## Step 8 — schedule a quarterly manual restore drill

Add to your operations calendar: every 3 months, re-run Step 5
(restore + verify + drop + shred). Record the date in
`/var/log/garudar-backup.log` (manually append) or in your ticket system.

This satisfies "untested backup = no backup" for compliance.

## Step 9 — off-site

When the customer chooses an off-site destination, replace the body of
`ops/backup/upload.sh` with the appropriate upload command, commit, push,
`git pull` on prod. Existing backups already created will not be uploaded
retroactively unless you run `upload.sh` on them manually.

## Notes on PostgreSQL version

`install.sh` auto-detects the installed PostgreSQL server version (by scanning
`postgresql-N` packages with `dpkg-query`) and installs the matching
`postgresql-client-N`, so that `pg_dump` is never a different major version
than the live server.

If you later upgrade the PostgreSQL server (e.g. 16 → 17 → 18), re-run
`install.sh` — it will detect the new version and install the corresponding
client.

The script intentionally avoids the `postgresql-client` metapackage from
pgdg, which always resolves to the latest available client. Pinning a fixed
version this way also prevents `apt-mark hold postgresql-client-16` from
being silently bypassed: pgdg can install `postgresql-client-18` as a
*different* package name, and `apt-mark` only blocks upgrades, not new
installs.

## Troubleshooting

- **`backup.sh: another instance is running`** — a previous run hasn't
  finished. Check `tail -f /var/log/garudar-backup.log`.
- **`Insufficient disk space`** — backups grew; clean older yearlys or
  resize the VPS.
- **`age binary missing`** — `apt install age` failed during install. Retry
  manually.
- **`notify.py: failed to send mail`** — Gmail credentials are wrong, or
  Gmail blocked the login. Re-issue an app password and put it in
  `SMTP_PASSWORD`.
- **`pg_dump` errors about permission** — `sudo -u postgres` requires peer
  auth set up. Verify `sudo -u postgres psql -c '\l'` works as root.
