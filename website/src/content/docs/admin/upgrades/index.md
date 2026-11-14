---
title: Upgrades
description: Image tags, how to update, and what to read before a bigger step.
sidebar:
  order: 1
  label: Tags and updating
---

## Image tags

Every stable release is published to the GitHub Container Registry and to Docker Hub, for `linux/amd64` and `linux/arm64`, with these tags:

| Tag | Example for 1.6.0 | Use when |
|---|---|---|
| `1.6.0` | exact version | You want full reproducibility |
| `1.6` | latest patch of 1.6 | You want bug fixes automatically |
| `1` | latest release of 1.x | You stay on the major version and get features |
| `latest` | most recent stable release | Anything new is fine |

Pre-releases such as `1.6.0-rc.1` get only their full version tag, never `latest`, `1` or `1.6`.

## Updating

1. Read the [release notes](https://github.com/strausmann/labelyard/releases) of every release between yours and the new one.
2. Take a [backup](/admin/backups/).
3. Change the tag in your compose file, then:

   ```bash
   docker compose pull
   docker compose up -d
   ```

Database migrations run at start. Your data volume, keys and settings carry over.

## Bigger steps

- [Coming from Label Printer Hub](/admin/upgrades/from-label-printer-hub/): Labelyard 1.6.0 is the renamed project. Images, command and environment prefix changed; data and API stay.
- From 1.4.x: release 1.5.0 moved every API route under `/api/v1/` without aliases. Update scripts, proxy rules and bookmarks first; the [1.5.0 release notes](https://github.com/strausmann/labelyard/releases/tag/v1.5.0) list the moved paths.
- [Upgrading to 1.7.0](/admin/upgrades/to-1-7-0/): printer responses report `connection.snmp.community_set` instead of the SNMP community.
