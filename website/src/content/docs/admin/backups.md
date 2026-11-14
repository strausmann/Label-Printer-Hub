---
title: Backups and restore
description: What to back up, how to take a consistent copy of the database and how to restore it.
sidebar:
  label: Backups and restore
---

Labelyard keeps all of its state in two places, and a backup needs both:

1. **The data volume** (`/data` in the container, `./data` next to the compose file in the examples). It holds the SQLite database: printers, sheet types, sheets and their cells, API keys, settings and jobs.
2. **`LABELYARD_SECRET_KEY`.** Secrets stored in the database, such as integration API keys, are encrypted with it. A database without its key restores everything except those secrets; the integrations page then asks you to enter them again.

Keep the key somewhere other than the backup of the volume, for example in your password manager.

## Taking a backup

The simplest consistent copy is taken with the container stopped:

```bash
docker compose stop labelyard
tar -czf labelyard-$(date +%F).tar.gz data
docker compose start labelyard
```

To back up without stopping, use SQLite's own backup command on the database file, which copies a consistent snapshot while the hub runs (the file is `printer-hub.db` unless you changed `LABELYARD_DATABASE_URL`):

```bash
sqlite3 data/printer-hub.db ".backup 'labelyard-backup.db'"
```

## Restoring

1. Stop the container.
2. Put the saved `data` directory (or the database file) back in place, owned by the user the container runs as (`1000:1000` in the examples).
3. Make sure the container gets the same `LABELYARD_SECRET_KEY` as before.
4. Start the container. Database migrations run at start, so a backup from an older release is brought up to date automatically. Going back to an older release with a newer database is not supported.

## Exporting settings

Admins can also export the runtime settings as a file from the settings page. That export is a convenience for moving settings, not a replacement for a backup of the volume.
