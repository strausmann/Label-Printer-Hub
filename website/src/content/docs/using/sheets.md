---
title: Sheets and layouts
description: Print onto label sheets with a page printer, keep track of used cells and lay out tape labels.
---

A page printer prints onto label sheets: A4 or letter pages with a grid of labels. Labelyard keeps track of every physical sheet, so a sheet you only half used can go back into the tray and be filled later.

## Sheet types

A **sheet type** describes a product: page size, the number of rows and columns and the measurements of a cell. Open **Sheets** to create one or to import one. Sheet types are versioned: when you correct a measurement, you add a version, and sheets that were already in use keep the version they were printed with.

Sheet types marked **verified** were measured on real sheets. Labelyard 1.7.0 adds Avery Zweckform 6121, 3490 and L4737REV (3490 prints no sheet code in the margin; that comes with #350) and corrects L4731REV (sheets you already have keep the old measurement). A type you created or imported under the same key is taken over with your prefix and its older versions kept, and the bell tells you once. A taken-over type counts as shipped from then on, so you can archive it but not delete it.

You can export a sheet type to a file and import it in this or another hub, so a product only has to be measured once.

Every sheet type has its own switch **QR codes on labels**, in the details of the type in the **Sheet archive**. A new type starts with it on when the shorter side of a label is at least 10 mm: on 25.4 × 10 mm labels a QR code with a short number beside it prints and scans. With the switch off, the labels on that type are printed without their QR code, the sheet ID label included, and the print preview marks those cells with "Code only on this sheet type". Types that already exist keep the setting they have.

## Sheets and their ID label

Each physical sheet gets its own code. When you add a sheet, you can print an ID label for it right away, so you can scan it later. A sheet knows which of its cells are free and which are used.

- **Free cells** take the next labels.
- **Unconfirmed cells** are cells of a job whose outcome is not known, for example when the printer failed mid-page. Check the sheet and confirm which of them were printed, one by one. When there are two or more, **Resolve all as printed** and **Resolve all as not printed** settle them in one go; the hub asks first and names how many cells it is about. If the number changed in the meantime, nothing is written and you are asked to check the list again.
- **Discarding** a sheet takes it out of the picker. Its code is never given out again; labels already printed stay printed.

## Printing onto a sheet

Choose **Print onto a sheet**, pick the sheet (or scan its code) and the cells. The preview shows where every label goes. When not everything fits, the rest stays in the [cart](/using/cart/) for the next sheet, or the preview plans it on the next one.

If another device used cells of the same sheet while you were looking, the hub tells you and asks you to check the new plan before it prints.

## Layouts

A layout decides what a label shows: a QR code, a code, a title and a detail line, in combinations from "code only" to "QR code, code, title and detail". Layouts that need a field the item does not have are refused before printing, with the missing field named. On a sheet type with QR codes switched off, a QR layout prints its text only (see [Sheet types](#sheet-types)).
