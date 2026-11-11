---
title: Print queue and jobs
description: How jobs move through the queue, what pause, resume, cancel and retry do, and what happens when an outcome is unknown.
sidebar:
  label: Print queue
---

Every print, from the web UI, a plugin, a webhook or the API, becomes a **job** in the queue of its printer. Nothing goes to a printer past the queue, so two callers never interleave on one printer.

## The jobs page

**Jobs** lists what is waiting, printing and finished, with the source of each job. A job page shows its progress live.

| Action | What it does |
|---|---|
| Pause / Resume | Holds or releases the queue of a printer |
| Cancel | Removes a waiting job; a printing job is asked to stop at the next safe point |
| Cancel queued | Cancels every waiting job of a printer at once |
| Retry | Queues a failed job again |

Finished jobs (done, failed, cancelled) are deleted after `LABELYARD_JOB_RETENTION_DAYS`, 30 days by default.

## Long tape jobs

A long run of tape labels is split into parts. When the outcome of a part is unknown, for example because the printer went offline in the middle, the job stops there instead of guessing. You see which labels are certainly printed and choose:

- **Continue with part N** when the labels came out, or
- **Reprint from label N** when they did not.

On page printers the same idea applies to sheet cells: their state stays unconfirmed until you check the sheet (see [sheets](/using/sheets/)).

## From scripts

`POST /api/v1/print` returns a job ID at once; poll `GET /api/v1/jobs/{job_id}` for its state. Problems that are known before printing (no tape, cover open, printer offline) are answered right away with an error code instead of a queued job. The [API reference](/developers/api/) lists them.
