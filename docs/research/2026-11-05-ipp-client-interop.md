# IPP client interoperability check (spike S2)

Date: 2026-11-05. Time box: 60 minutes. Outcome: no codec or client defect found.

## Question

The hub's IPP codec and `IppClient` were only ever tested against `FakeIppPrinter`,
which is built on the same codec. A symmetric encoder/decoder bug would cancel out
there. This spike checks both directions against a second implementation, CUPS
(libcups), before real hardware is involved.

## Setup

- CUPS 2.4.10 (`cups-ipp-utils`, Debian trixie), run only inside a throw-away container
  on the host network; nothing was installed on the host, and the container and image were
  removed afterwards. Not a dependency of the repo or of CI.
- Reference printer: `ippeveprinter` on loopback, high port. Two instances:
  - **A**: `-f application/pdf`, otherwise defaults (full `media-col-database`,
    `media-type-supported` includes `labels`, no `print-scaling-supported`).
  - **B**: an attribute file adding `media-type-supported labels,stationery`,
    `print-scaling-supported auto,fill,fit,none`, `print-color-mode-supported monochrome,color`
    and a PDF `document-format-supported`.
- Driver: a throw-away script (not committed) using `IppClient` from the backend venv.
- Reverse direction: `ipptool -tv` against `FakeIppPrinter` served on loopback by the
  repo's `serve_on_loopback` helper, using CUPS's bundled tests plus one chained test.
- Request bytes from libcups: `ipptool` pointed at a raw TCP listener; the captured body
  was decoded with our `decode`.

## Results: our client against `ippeveprinter`

| Operation | Printer A | Printer B |
|---|---|---|
| Get-Printer-Attributes (`all`) | decoded: 103 attributes, nested collections (`media-col-database`, `media-col-ready`, `finishings-col-database`) intact | decoded: 59 attributes |
| Validate-Job with `media-col`, `print-scaling`, `print-color-mode` | ok | ok (see below: status 0x0001) |
| Print-Job (PDF, `media-col{media-size, media-type=labels}`, `print-scaling=none`, `print-color-mode=monochrome`, `copies`) | ok; the printer's job environment shows `media-col={media-size={x-dimension=2100 y-dimension=2970} media-type=labels}`, `print-scaling=none`, `print-color-mode=monochrome`, `document-format=application/pdf`, and the spooled file is byte-identical to the PDF sent | ok; `print-scaling`, `print-color-mode` received; `media-col` refused (see below) |
| Get-Job-Attributes | ok (`job-state`, `job-state-reasons`, `job-impressions-completed`) | ok |
| Get-Jobs (`not-completed`, `completed`) | ok; the job appears in the right list | ok |
| Cancel-Job | ok while the job was processing | `client-error-not-possible` (0x0404) once the job had already finished: raised as `IppStatusError`, as intended |
| Get-Job-Attributes, unknown job id | `client-error-not-found` -> `IppNotFoundError` | same |

Out-of-band values (`printer-geo-location` as `unknown`) decode as `OutOfBand`. No
attribute decoded as `Unknown`.

## Results: `ipptool` against `FakeIppPrinter`

- `ipptool` decodes every response of the fake without a framing or tag error.
- A chained test (Print-Job with PDF and `media-col`/`print-scaling`/`print-color-mode`,
  Get-Job-Attributes, Get-Jobs, Cancel-Job, Get-Job-Attributes with the `job-id` taken from
  the Print-Job response) passes 5 of 5, including the final `job-state = canceled`.
- CUPS's generic conformance tests (`get-printer-attributes.test`, `print-job-media-col.test`,
  `get-job-attributes.test`) fail only on the fake being a minimal printer: it omits attributes
  the conformance suite expects (`printer-name`, `operations-supported`, `charset-supported`,
  `media-col-default`, ...), and `print-job-media-col.test` sends `application/octet-stream`,
  which the fake refuses by design. None of this is a codec problem; no change was made.
  `print-job.test`, `get-jobs.test`, `validate-job.test` and `cancel-current-job.test` pass.

## Results: libcups-encoded request, decoded by our codec

A Print-Job produced by `ipptool` (nested `media-col` collection with `media-size`
sub-collection, keywords, mimeMediaType, name, document) decodes in `app.printer_backends.ipp.codec.decode`
into exactly the intended attributes; the trailing 15 bytes are the document.

## Observations and decisions

1. **`successful-ok-ignored-or-substituted-attributes` is treated as success.** Printer B
   refused its own reference tool's `media-col` as well (its attribute file replaced the
   media database), and answered Validate-Job and Print-Job with status 0x0001. `IppClient`
   returns success and drops the `unsupported-attributes` group, as the status range check
   (`0x0000-0x00FF`) and the error contract say. Consequence for the caller: **Validate-Job
   cannot be used to prove that `media-col` will be honoured.** The check that a printer
   supports the media size/type must come from the Get-Printer-Attributes summary (Task 4),
   not from Validate-Job or from a successful Print-Job. Decision: no client change;
   handed to the controller (see report).
2. **Duplicate attributes from a printer.** With the attribute file, B listed
   `document-format-supported` twice. The decoded summary keeps the first occurrence
   (`pdf`, `urf`), because `Message.attrs` keeps the first value list of a repeated name. Acceptable.
3. **`Cancel-Job` on a job that is already `completed` -> 0x0404.** Callers that cancel
   must treat `client-error-not-possible` as "already finished", not as a failure.
4. **Cancel is asynchronous.** Right after Cancel-Job the job reports
   `job-state = processing` with reason `processing-to-stop-point`; `canceled` follows.
   A cancel must be confirmed by polling, not assumed from the Cancel-Job status.
5. **`print-scaling` is not advertised by printer A** (it did not appear in
   `print-scaling-supported`); it was still accepted and delivered. A printer ignoring the
   attribute is not detectable through the client, same conclusion as 1.

## Not covered

- TLS (`ipps`), authentication, and large documents (the reference printer spools to disk).
- Real label-printer firmware, which is the next check.
- No hand-built fixtures were added; the brief asked for none.
