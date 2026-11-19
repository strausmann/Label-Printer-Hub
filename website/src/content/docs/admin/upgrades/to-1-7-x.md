---
title: Upgrading within 1.7.x
description: What changes for API clients with the 1.7.x patch releases.
sidebar:
  order: 4
---

The 1.7.x releases are patch releases. Your data, keys and settings carry over; update the tag as described in [Tags and updating](/admin/upgrades/). Check the points below if a script or integration reads printer data from the API or sends large or long values.

## A tape printer's address is for admin keys only

A tape printer's address is connection detail, like the address of a page printer. From 1.7.x:

- Read and print keys no longer receive `connection.host`, `connection.port` and `connection.snmp` for tape printers; `connection` is an empty object for them. Admin keys still receive all three.
- A tape printer's `last_error` in the status names the error class only, for example `PySnmpError`, like a page printer's. The server log keeps the full message.
- The `error` of a failed tape job (`GET /api/v1/jobs`) no longer carries the printer's address: an unreachable printer is reported with a fixed text (`The printer could not be reached.`), and an unexpected error with its class name only. The server log keeps the full message.

If a script with a read or print key reads the host of a tape printer, use an admin key for it.

## Limits on request size and field length

Request bodies above 2 MiB are refused with `413` and the error code `body_too_large`, for every route and before authentication (a declared `Content-Length` before the body is read, a body without one as soon as it passes 2 MiB). Webhook ids and event types above 64 characters (`spool_id`, `product_id`, `type`) and lookup identifiers above 120 characters are refused with `422`; a lookup `app` above 32 characters too. Nothing sends values of that size in normal use. See [request body size](/install/reverse-proxy/#request-body-size) for the matching proxy limits.

## Queued labels after a restart

After a restart the hub no longer draws every queued label before it starts, so startup no longer grows with the queue. A queued label is drawn when its turn comes: a label that cannot be drawn again now fails at that moment, with the same error (`recovery_rerender_failed: …`), not during startup. On a printer that was paused when the hub stopped, such a label stays `queued` until you resume the printer.

## Short labels on QL printers

The QL library is now `brother-ql-next`. A QL label shorter than about 12.7 mm (150 dots) gets blank tape at its end, so it prints slightly longer than the preview shows. A QL label longer than 1000 mm (500 mm at 600 dpi) is refused with `422` and the error code `tape_label_too_long`.

## Print confirmation of tape printers

- After a restart, and with every test print, `print_confirmation` no longer keeps `counter_read` `false` from before: the hub asks for the label counter again, and the stored record says so after the printer's first status read. It turns `false` again only when the printer refuses the counter three times in a row.
- A record the hub could not store (a busy database) is stored again by the printer's next status read, instead of at the next change.
- The tape length of a QL label that is wider than the printable width is now the length the printer feeds after scaling it to the roll, not the label's long side. Such a label is no longer refused with `tape_label_too_long` for a length it does not have, and the confirmation wait follows the real length. The blank tape added to a short label counts towards it.
