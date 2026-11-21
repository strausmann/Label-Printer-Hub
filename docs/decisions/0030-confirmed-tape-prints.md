<!--
SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
SPDX-License-Identifier: AGPL-3.0-or-later
-->

# 0030 — A tape print counts only when the printer confirms it

- **Status:** Accepted
- **Accepted:** 2026-11-21 — shipped in 1.7.0 (#389, #393); written down after the fact by the ADR audit of 2026-11-21
- **Date:** 2026-11-21
- **Deciders:** maintainer
- **Amends:** [0005](0005-print-queue-is-mandatory.md) (transport and pause of a tape job), [0006](0006-status-sources-by-phase.md) (the phase after sending), [0020](0020-backend-kinds-ipp-page-printers.md) (the IPP client also sends to tape printers)
- **Decision label:** D27
- **Related:** [0024](0024-runtime-printer-wiring-and-hardware-identity.md) (wiring of tape printers)

## Context

Neither print library reads anything back over the network: `brother_ql` reports `sent` right after writing, and `ptouch` only writes (ADR 0006, amendment of 2026-11-17). Until 1.7.0 a tape job was therefore `done` as soon as its bytes were on the wire. A label that jammed, a roll that ran out halfway through a run, or a QL that refused the job because the wrong roll was loaded was still reported as printed, and a sheet of follow-up labels went out after it.

#389 added an SNMP read right before and right after sending (ADR 0006, 2026-11-17). That catches a blocking error bit, but it cannot say whether the labels came out: a printer with no error bit may still have printed nothing, and when the read after sending got no answer, a single job stayed `done` on purpose.

#393 measured two ways a Brother tape printer can say what it printed, on a QL-820NWB and a PT-P750W (`backend/app/printer_backends/tape_confirmation.py:4-18`):

- **IPP.** The printer accepts the unchanged Brother raster bytes as an IPP Print-Job with `document-format: application/octet-stream` and reports the job's state (`9` completed, `8` aborted, `7` canceled) with `job-impressions-completed` as the printed count.
- **Label counter.** The SNMP printer MIB entry `prtMarkerLifeCount` counts single labels. Read before sending and polled after it, it says how many labels came out.

## Decision

**A tape job is `done` only when the printer confirms the labels it was sent; a shortfall fails the job with "x of y labels printed", and an outcome the hub cannot learn pauses the printer.**

- **Before sending.** The SNMP read before sending stays as ADR 0006 describes it (blocking bits, missing or different tape refuse the send, nothing goes out). The read now also keeps the label counter for the check after sending (`backend/app/printer_backends/post_send.py:97-102`, `check_after_send` docstring at `post_send.py:167-168`).
- **The channel is decided per printer by a test print and stored.** The test print records a `ConfirmationRecord` (`tape_confirmation.py:166-181`) in `printers.print_confirmation` (`backend/app/models/printer.py:56-60`): `confirm_transport` is `ipp` only when the test label went out as an IPP Print-Job and reached job state 9, else `raw`; `label_counter` says whether the counter rose by exactly the labels sent. A printer without a record is probed once per backend instance.
- **IPP transport for tape printers.** With `confirm_transport: ipp` both raster backends send through `TapeIppTransport` (`tape_confirmation.py:272-340`; wired in `backend/app/printer_backends/brother_ql_backend.py:51,277` and `backend/app/printer_backends/ptouch_backend.py:39,294`), which uses the hub's own IPP client (`IppClient`, ADR 0020) to send a Print-Job with `application/octet-stream` (`tape_confirmation.py:110,336-340`). TCP/9100 stays the transport of every printer without IPP; the label counter confirms it.
- **After sending, the hub waits for the confirmation** (`check_after_send`, `post_send.py:157`). IPP jobs are polled until a final state; job state 9 counts as printed and the counter, if read, is only a second witness (IPP wins). Without IPP the counter is polled until it rose by the labels sent and the printer is idle, or the count held still for `STEADY_READS` reads. The wait is bounded by `confirm_timeout_s` (`tape_confirmation.py:131`; first values `CONFIRM_BASE_S` 15 s plus `CONFIRM_PER_LABEL_S` 8 s per label, `tape_confirmation.py:54,58`), longer for a printer that still reports `printing`.
- **A shortfall fails the job, "x of y".** An IPP job that ends aborted or canceled, or a counter that did not rise by the labels sent before the timeout, raises `LabelsNotConfirmedError` (`backend/app/printer_backends/exceptions.py:90-104`): the job fails with `labels_not_confirmed` and the message "x of y labels printed". A blocking error bit reported at the same time raises that error instead, carrying the printed count; labels that were confirmed stay `done` and the printer pauses (`backend/app/services/print_queue.py:2747-2750`).
- **An outcome the hub cannot learn pauses the printer.** An IPP job with no final state in time is cancelled (best effort, `tape_confirmation.py:343`). When that cancel fails, the labels may still print: `ConfirmationUnknownError` (`exceptions.py:119-127`) ends the job `outcome_unknown` and, for a single job as for a run, pauses the printer until someone checked it (`print_queue.py:179-182`, `print_queue.py:2779-2783`). A counter that rose by exactly the labels sent overrides this. An IPP job the printer accepted is never sent again over TCP/9100.
- **A counter that cannot be read never fails a job.** A counter missing before or after, one that went down, or one that jumped by more than the labels plus `COUNTER_JUMP_SLACK` is logged and accepted. After `UNANSWERED_POLLS_LIMIT` (5) reads in a row without an SNMP answer the wait ends early and the labels count as printed with a warning (`post_send.py:129-132`), so an unreachable printer does not hold the worker for the whole timeout. A backend that reports no label count gets the single read of ADR 0006.

## Options considered

### Option A — confirm through IPP job state or the label counter, decided per printer (chosen)
- Pros: a label counts only when the printer says so; "x of y" is exact where the printer reports it; IPP gives a job-level answer and a cancel for a job that did not finish; printers without IPP still get a confirmation from the counter.
- Cons: every tape send waits for the confirmation, so a job ends later; two channels, a test print and a stored record per printer; the timeouts are first values from two printers.

### Option B — keep "sent is printed" with the SNMP reads of #389
- Pros: no waiting, no new state.
- Cons: a printer that prints nothing without raising an error bit is reported as printed; follow-up labels of a run go out after a jam.

### Option C — IPP only
- Pros: one channel with job identity and cancel.
- Cons: not every tape printer takes `application/octet-stream` over IPP or answers the job operations; those would lose every confirmation.

### Option D — label counter only
- Pros: works on TCP/9100 without IPP.
- Cons: no job identity and no cancel; a counter that does not answer leaves nothing else.

## Consequences

- New job error codes `labels_not_confirmed` and `outcome_unknown` (`print_queue.py:194-195`); `outcome_unknown` is a pause reason for single jobs too, not only for tape runs (#277).
- ADR 0005: TCP/9100 is no longer the only transport of a tape worker, and the hub may cancel a tape job it sent over IPP, but only to stop a job whose confirmation did not come. A user still cannot cancel a tape job that is `printing` (`backend/app/api/routes/jobs.py:238-256`).
- ADR 0006: the after-send row of the 2026-11-17 amendment ("one SNMP read"; "a single job stays `done`" when unread) is replaced by the wait above. The table stays in ADR 0006 as history.
- ADR 0020: the hub's IPP client is no longer used for page printers only. `ipp` printer rows still never enter the tape wiring, and page printers are still sent PDF only.
- The test print is the place where a printer's channel changes; a printer whose IPP job did not complete during a test print stays on TCP/9100 until the next test print.
- Register label D27.

## References

- Issues: #389, #393, #277 (tape runs)
- Code: `backend/app/printer_backends/tape_confirmation.py`, `backend/app/printer_backends/post_send.py`, `backend/app/printer_backends/exceptions.py`, `backend/app/services/print_queue.py`
- Related ADRs: [0005](0005-print-queue-is-mandatory.md), [0006](0006-status-sources-by-phase.md), [0020](0020-backend-kinds-ipp-page-printers.md) (all amended), [0024](0024-runtime-printer-wiring-and-hardware-identity.md)
