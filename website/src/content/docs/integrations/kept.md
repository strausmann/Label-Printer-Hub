---
title: Kept
description: Print labels for the things, places and boxes of the Kept home inventory through the Labelyard API.
---

[Kept](https://keptinventory.info) is a self-hosted home inventory. It prints its labels through Labelyard's API, so Labelyard needs no plugin for it.

## Setup

1. In Labelyard, create an API key with `print` scope for Kept. Limit it to the printers Kept should use (see [API keys](/admin/api-keys/)).
2. In Kept, enter the hub's address and that key. Kept's own documentation shows where.

If both run in the same Docker stack, Kept can reach the hub at `http://labelyard:8000` without going through the reverse proxy; the key is all it needs.

## What to check

- The key needs `print` scope; with `read` the print calls are refused.
- A job from Kept appears on the **Jobs** page like any other, with its source, so you can follow it there.
