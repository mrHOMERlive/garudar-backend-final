# Garudar backup system

Automated, encrypted backups of the Garudar production VPS with
grandfather-father-son retention and operational alerting.

## What gets backed up

| Tier   | Source                                  | Frequency | Tool        |
|--------|-----------------------------------------|-----------|-------------|
| Daily  | PostgreSQL (`pg_dump` custom format)    | Every day | `backup.sh` |
| Daily  | MinIO `/home/documents_s3/`             | Every day | `backup.sh` |
| Weekly | NPM `data/` + `letsencrypt/` + `.env`   | Sunday    | `backup-configs.sh` |

The application source code, Docker images, and `__pycache__` are **not**
backed up — they live in git and are reproducible.

## Retention (GFS)

| Tier    | Count             | Disposition                       |
|---------|-------------------|-----------------------------------|
| Daily   | 7                 | Last 7 days                       |
| Weekly  | 4                 | Last 4 Sundays                    |
| Monthly | 6                 | Last 6 month-firsts               |
| Yearly  | 7 (PostgreSQL only) | Last 7 January 1sts             |

Weekly / monthly / yearly tiers are hard links to the corresponding daily
file. They cost no extra disk until the daily expires.

## Encryption

Every backup file is encrypted with [age](https://age-encryption.org/) using
asymmetric X25519 keys.

- **Public key** lives on the server (in `/etc/garudar-backup/config.env`)
  and is the only key needed to *create* a backup.
- **Private key** is generated once by `install.sh`, printed to the terminal
  ONCE, and then deleted from the server. Operator saves it offline
  (password manager + paper). Without the private key, no backup is
  recoverable — losing both the server and the private key is a total
  data-loss event, so off-site copies of the private key are essential.

The server never holds the private key during normal operation. If
production is compromised, the attacker cannot decrypt existing backups.

## Off-site

The script `upload.sh` is invoked after each successful local backup.
Currently it is a **placeholder** that logs "off-site not configured yet" —
local backups still succeed.

Once an off-site target is chosen (Backblaze B2, Wasabi, second VPS, etc.),
replace the body of `upload.sh` with the appropriate `rclone` / `aws s3 cp` /
`mc cp` invocation. No other script changes are required.

## Layout on the production host

```
/home/.../clear-garudar-backend/ops/backup/   <- scripts (from git)
/etc/garudar-backup/config.env                <- per-host config (NOT in git)
/etc/garudar-backup/age-private.key           <- present only during restores
/etc/cron.d/garudar-backup                    <- cron schedule
/var/backups/garudar/                         <- backup files
  ├── postgres/
  │   ├── daily-YYYYMMDD.dump.age
  │   ├── weekly-YYYYMMDD.dump.age
  │   ├── monthly-YYYYMM.dump.age
  │   └── yearly-YYYY.dump.age
  ├── minio/
  │   ├── current/                            <- live-mirrored tree (rsync)
  │   ├── daily-YYYYMMDD.tar.gz.age
  │   ├── weekly-YYYYMMDD.tar.gz.age
  │   └── monthly-YYYYMM.tar.gz.age
  └── configs/
      └── configs-YYYYMMDD.tar.gz.age
/var/log/garudar-backup.log                   <- run log
/var/lock/garudar-backup.lock                 <- flock guard
```

## Cron schedule

| When            | Job                              |
|-----------------|----------------------------------|
| Daily 02:00     | `backup.sh`                      |
| Sunday 03:00    | `backup-configs.sh`              |
| 1st of month 04:00 | `test-restore.sh` (commented by default; see security note) |

## Alerting

Any non-zero exit from `backup.sh` or `backup-configs.sh` triggers an email
via `notify.py` to `ALERT_EMAIL` (`info@garudar.id` by default) using the
same Gmail SMTP relay that the application uses.

There is **no** "OK" mail by design (it would be noise). Success is verified
by absence of failures + the monthly restore test result.

## Restore

### PostgreSQL

```bash
# 1. Copy the offline private key onto the server.
sudo install -m 0600 -o root -g root /path/to/your/key /etc/garudar-backup/age-private.key

# 2. Restore the chosen dump into a fresh DB.
sudo bash ops/backup/restore-postgres.sh \
    /var/backups/garudar/postgres/daily-20260513.dump.age \
    garudar_restore_test

# 3. Inspect.
sudo -u postgres psql garudar_restore_test -c '\dt'

# 4. Shred the private key when done.
sudo shred -u /etc/garudar-backup/age-private.key
```

### MinIO

```bash
sudo bash ops/backup/restore-minio.sh \
    /var/backups/garudar/minio/daily-20260513.tar.gz.age \
    /tmp/minio-restore
```

If the live MinIO data needs to be replaced:

```bash
docker stop garudar-minio
sudo rsync -a --delete /tmp/minio-restore/ /home/documents_s3/
docker start garudar-minio
```

## Untested backups don't exist

`test-restore.sh` automates the restore drill on the latest daily PG dump:

1. Decrypt it into `/tmp`.
2. Restore into a temporary database (`garudar_restore_test`).
3. Run row-count checks against critical tables.
4. Drop the temporary DB.
5. Email the result.

By default this is **commented out in cron** — running it requires the
private key to be present on the host. Two recommended modes:

- **Manual quarterly drill**: copy the key, run `test-restore.sh`,
  shred the key. Record the date in the operations log.
- **Dedicated test machine**: a second box that pulls backups from
  off-site storage and holds the private key permanently. The cron entry
  for `test-restore.sh` is enabled there.

## Files in this directory

| File                  | Purpose                                          |
|-----------------------|--------------------------------------------------|
| `README.md`           | This document.                                   |
| `INSTALL.md`          | Step-by-step setup procedure for the prod VPS.   |
| `config.env.example`  | Template of `/etc/garudar-backup/config.env`.    |
| `install.sh`          | One-time install (apt deps, dirs, key, cron).    |
| `backup.sh`           | Daily PG + MinIO snapshot, GFS promotion, rotation. |
| `backup-configs.sh`   | Weekly NPM + `.env` tarball.                     |
| `upload.sh`           | Off-site upload (placeholder; replace body).     |
| `restore-postgres.sh` | Decrypt + restore a PG dump into a target DB.    |
| `restore-minio.sh`    | Decrypt + extract a MinIO tarball into a dir.    |
| `test-restore.sh`     | Automated restore drill + row-count check.       |
| `notify.py`           | Email helper (stdlib smtplib).                   |

## Compliance notes (Indonesian regulator)

- POJK 12/2017 (anti-money-laundering) requires KYC and transaction records
  to be retained for at least **5 years** after the end of the client
  relationship. This retention is satisfied by the **live PostgreSQL and
  MinIO data** — backups are an *operational recovery* mechanism, not the
  primary retention vehicle.
- Yearly archives provide an additional 7-year safety net on PostgreSQL,
  which is the most demanding-to-recreate data store.
- The monthly restore test produces a verifiable journal in
  `/var/log/garudar-backup.log` (plus the per-test email). Regulators may
  request evidence of backup-restoration capability.
