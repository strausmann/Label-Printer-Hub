---
title: API keys
description: Create a key per caller, choose its scope and printers, and recover when every admin key is lost.
---

Everything that is not a browser behind an SSO proxy signs in with an API key: the web UI, scripts, other apps. Send it in the `X-Label-Hub-Key` header. The header name and the `lh_` prefix of the keys are kept from the former project name, so existing clients keep working.

## Scopes

| Scope | Allows | Use for |
|---|---|---|
| `read` | Reading only | Monitoring, status pages |
| `print` | Reading and printing | Apps and scripts that print |
| `admin` | Everything, including settings and keys | People who manage the hub |

Each scope includes the ones above it. A `read` or `print` key can also be limited to some printers; an empty list allows all of them. A key with the `admin` scope always acts on every printer, so it cannot be limited: a printer list on an admin key is refused with `422` and `admin_key_not_restrictable`.

## Creating a key

1. Sign in with an admin key and open **Settings > Access and keys**.
2. Create a key with a name that says who uses it and its scope. The form sets no printer list or rate limit; set `allowed_printer_ids` (not for `admin`) and `rate_limit_per_minute` through the API, with `POST /api/v1/admin/api-keys` or `PATCH /api/v1/admin/api-keys/{id}`.
3. Copy the key. It is shown **once**; the hub stores only a bcrypt hash of it.

Create one key per caller, so you can revoke one without touching the others.

## Using a key

```bash
curl -H "X-Label-Hub-Key: lh_..." https://labelyard.example.com/api/v1/printers

curl -X POST https://labelyard.example.com/api/v1/print \
  -H "X-Label-Hub-Key: lh_..." -H "Content-Type: application/json" \
  -d '{"content_type": "qr_two_lines",
       "data": {"title": "Asset 123", "primary_id": "ASSET-123",
                "qr_payload": "https://snipe.example.com/hardware/123"}}'
```

Requests authenticated by a key header are not subject to the CSRF check; that check only guards browser sessions.

## Rate limits

The default is 60 requests per minute and key, adjustable from 1 to 10,000. Above it the hub answers `429` with a `Retry-After` header and the error code `rate_limit_exceeded`.

## Sheets

Sheets are shared physical material: the sheet routes are not limited by a key's printers, and every key sees every sheet.

| Route | Scope |
|---|---|
| `GET /api/v1/sheets`, `/sheets/{code}`, `/sheets/next-code`, `/sheet-cells` | `read` |
| `POST /api/v1/sheets` (create), `/sheets/{code}/cells/mark`, `/cells/unmark`, `/cells/resolve` | `print` |
| `POST /api/v1/sheets/{code}/discard` | `admin` |

Discarding a sheet needs `admin` since 1.5.x; before, a `print` key could do it. A discard cannot be undone and the code is never issued again, so a key that only prints labels should not retire a sheet. A `print` key gets `403` with `insufficient_scope`. Marking and resolving cells stay with `print`, also for keys limited to some printers.

## Batches, previews and drawing

Tape batches (`POST /api/v1/print/{printer}/batch`) are limited per printer and per key:

| Limit | Default | Setting |
|---|---|---|
| Tape runs a printer has queued or printing | 5 (at least 5) | `LABELYARD_MAX_QUEUED_RUNS_PER_PRINTER` |
| Tape runs of one key, over all printers, held runs included | 20 | `LABELYARD_MAX_QUEUED_RUNS_PER_KEY` |
| Held runs per printer (stopped, or waiting for `/continue`) | 5 | fixed |
| Held runs of one key on one printer | 2 | fixed |

A browser session signed in with a key counts as that key for these limits. Over a queued-run limit the batch answers `429` with the error code `too-many-queued-runs`. A key's third held run on a printer discards that key's own oldest held run (`run_discarded_limit`), never another key's. While a printer's five held places are taken, a batch of more than 50 labels from a key without a held run there is refused with `429`; smaller batches are always taken.

Only the key that submitted a batch may `continue`, `reprint` or `discard` its run, and `GET /api/v1/batches/runs/held` shows a key only its own runs. For any other key the batch answers `404`, also on `GET /api/v1/batches/{id}`. SSO users and admin keys may see and act on all runs. All callers without a key (SSO users) count as **one** key for the held-run limits: one SSO user's held run lets every SSO user pass the held-places check, and an SSO user's further held run can discard another SSO user's oldest one.

A sheet preview (`POST /api/v1/print/{printer}/sheet/preview`) runs once per key at a time; a second one answers `429` `too-many-previews`. For previews, callers without a key are told apart by source, user and address.

At most two pages are drawn at once in the hub, sheet previews and page jobs together. A page that takes longer than `LABELYARD_RENDER_TIMEOUT_S` (default 60 seconds) to draw ends the preview with `504` `render-timeout` and fails a page job with `render_timeout`. Its drawing thread cannot be stopped and keeps its slot until it ends; from the time limit on it counts as stuck, even if its caller has gone away.

Each owner holds at most one of the two slots at once, running or stuck: each API key on its own (a browser session signed in with a key counts as that key), and all callers without a key (SSO users, the hub's own page jobs) together as one group. A second drawing of the same owner waits for its turn, at most the time limit, and then fails like a full hub. While a key has a stuck drawing, its next preview answers `429` `too-many-previews` and its next page job fails with `render_timeout` at once. While the group without a key has a stuck drawing, a preview without a key answers `503` `render-unavailable` and a page job without a key fails with `render_unavailable` at once. With every slot stuck, every caller gets that answer.

The accepted residual risk: one party cannot hang both slots, but two different owners together can (two keys, or a key and an SSO user). Keys are issued by an admin; revoke such a key. Revoking ends its further requests, but the stuck slot itself is freed only when the thread ends or the hub restarts. The callers without a key share their slot, so one stuck drawing of one SSO user refuses every SSO user until it ends or the hub restarts.

`GET /readiness` shows stuck drawings in the check `render_slots`, which fails when every slot is stuck. `/healthz` does not, so restart the hub by hand then. The slots and the counts live in the hub's process; the image runs one process. If you start the backend with several worker processes (for example `uvicorn --workers 2`), each has its own two slots and counts, so a key can hold one slot in each.

## Jobs belong to the key that submitted them

Every job records the API key that submitted it (tape labels, batches, sheets, page jobs, test prints and retries), also when it came from a browser session signed in with that key. A key without `admin` scope sees and acts on its own jobs only, and so does a browser session signed in with such a key: signing in does not widen what a key may see.

- `GET /api/v1/jobs` lists only the jobs the key submitted.
- `GET /api/v1/jobs/{id}`, `POST …/cancel`, `…/retry`, `…/pause` and `…/resume` answer `404` for a job another key submitted, with the same body as for a job that does not exist.
- `GET /api/v1/printers/{id}/queue` lists only the key's own active jobs, and `POST /api/v1/printers/{id}/queue/clear` cancels only the key's own queued jobs; the jobs of other keys and of browser or SSO users stay queued.
- `GET /api/v1/batches/{id}` answers `404` for a batch another key submitted.
- The event stream `GET /api/v1/events` delivers `job.state_changed` and `run.state_changed` only for the key's own jobs and tape runs, live and in the snapshot. Printer events (`printer.status`, `printer.tape_changed`, …) still reach every key of the printer, and `queue_depth` still counts the printer's whole queue.

A job without an owner key belongs to no API key, so a plain key gets `404` for it. That is every job an SSO user submitted, every webhook job (the webhook key is not an API key), and every tape job stored by 1.5.0 or earlier, which stored tape labels, batches and retries without their key. A job the hub recovers after a restart keeps the key it was stored with.

SSO users, admin keys and browser sessions signed in with an admin key see and act on every job of their printers. If several clients shared one printer's jobs through different keys, give the client that must see all of them an admin key, or let each client follow its own jobs.

## First key and recovery

A fresh install has no key; the [installation](/install/) shows the two ways to get the first one. If every admin key is lost, create a new one inside the container. It is printed once:

```bash
docker compose exec labelyard labelyard admin create-key --scope admin --name recovery
```

Whoever can run commands in the container controls the hub anyway, so this adds no new way in. Revoke the lost keys afterwards. Revoking a key also ends every browser session that signed in with it.
