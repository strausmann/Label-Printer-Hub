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
