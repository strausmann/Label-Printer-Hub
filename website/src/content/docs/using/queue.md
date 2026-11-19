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

A tape job is **done** only when the printer confirmed it: either the printer reports the job state over IPP, or its label counter rose by the labels sent. The test print on the printer page finds out which of the two your printer offers and shows it under **Print confirmation**. Each test print tries IPP again, so a printer that was asleep during one test print is found again by the next. Only when the printer took a test label over IPP and did not finish it, without a fault such as a jam, an open cover or the tape end to explain it, does the next test print stay on the label counter; **Print confirmation** then says that IPP is not tried. The hub waits for the confirmation 15 seconds, plus 8 seconds per label, plus one second per 20 mm of tape, so a long label gets the time it needs; a printer that still reports that it is printing gets up to twice that. A label longer than the tape allows (1000 mm on TZe tape, 500 mm on heat-shrink tube) is refused when you print it, before it is queued: "This label is x mm long; this tape holds at most y mm." A batch with one such label is refused as a whole, and nothing of it is printed; the printer stays free for the next job. When the printer confirms fewer labels than were sent, the job fails with "The printer confirmed x of y labels": the confirmed labels are done, and a retry or **Reprint** prints only the rest. A printer that offers neither keeps the old rule: a label that was sent counts as printed. When the printer refuses its label counter three times in a row (within an hour, and with no other answer to the counter in between; a status read that fails altogether counts neither way), the hub stops reading it, and **Print confirmation** says so ("Not confirmed — the label counter does not answer"). It asks for the counter again after an hour, with a fresh count of three, with every test print and after a restart of the hub; from then on **Print confirmation** no longer says that the counter does not answer, until it is refused three times again.

When the printer took a tape job over IPP but did not finish it in time and did not let the hub cancel it, the labels may still come out. Unless the label counter shows every label, the job fails with `outcome_unknown` ("The print stopped while this label was being sent. It may or may not have printed.") and the printer **pauses** ("A print may not have finished — check the printer"), a single job just like a long run, so nothing else is sent meanwhile. Check what came out, reprint what is missing, then **Resume** the printer. A plain shortfall ("The printer confirmed x of y labels") does not pause the printer.

Finished jobs (done, failed, cancelled) are deleted after `LABELYARD_JOB_RETENTION_DAYS`, 30 days by default.

## Long tape jobs

A long run of tape labels is split into parts. When the outcome of a part is unknown, for example because the printer went offline in the middle, the job stops there instead of guessing. You see which labels are certainly printed and choose:

- **Continue with part N** when the labels came out, or
- **Reprint from label N** when they did not.

On page printers the same idea applies to sheet cells: their state stays unconfirmed until you check the sheet (see [sheets](/using/sheets/)).

## From scripts

`POST /api/v1/print` returns a job ID at once; poll `GET /api/v1/jobs/{job_id}` for its state. Problems that are known before printing (no tape, cover open, printer offline) are answered right away with an error code instead of a queued job. The [API reference](/developers/api/) lists them.
