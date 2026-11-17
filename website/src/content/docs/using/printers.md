---
title: Printers
description: The printer pages, what their states mean and how to recover a printer that stopped.
---

The **Printers** page lists every printer you added, with its live state. Open one to see its queue, the loaded material and its settings.

## Tape and label rolls

For PT-Series and QL-Series printers the hub reads the loaded tape or label roll from the printer itself. A label is laid out for what is loaded; you do not configure the tape width anywhere. When the printer reports that it is running low or empty, the overview says so before the next job fails.

## States

| State | Meaning | What to do |
|---|---|---|
| Ready | The printer answers and can print | Nothing |
| Printing | A job is on its way | Wait; the job page shows progress |
| Cover open, no tape, offline | The printer reported a problem | Fix it at the printer, then resume the printer's queue |
| Paused | Someone paused the queue | Resume it on the printer page |

When the printer reports a recoverable problem in the middle of the queue, the queue stops instead of throwing jobs away. After you fixed it, resume the printer: in the web UI on the printer page, or with `POST /api/v1/printer/resume`.

## How a tray takes paper

To print the sheet code on the back of a sheet, the hub needs to know how a tray of a page printer takes paper: which face it prints on, and which edge of the print comes first. Set it once per tray, in **Settings**, the printer's trays, **Set up**, or when the hub asks while you activate a sheet:

1. Take a plain sheet and mark a cross on the side facing up, next to the edge that goes in first.
2. Put it into the tray and print the test page. It shows a big "TOP ↑" at the top edge of the print and "PRINTED SIDE" in the middle.
3. Answer whether the print is on the side with the cross, and whether "TOP" is next to the cross.

Anyone who may print on the printer can answer once. After that only an admin can change it, with **Set up again**. When a tray leaves the printer's list, or the printer is replaced by another device, its answer goes too.

## Disabled printers

A disabled printer takes no jobs: a print to it is refused with `printer_disabled`.
