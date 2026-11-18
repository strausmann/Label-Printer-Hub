---
title: Sheets and layouts
description: Print onto label sheets with a page printer, keep track of used cells and lay out tape labels.
---

A page printer prints onto label sheets: A4 or letter pages with a grid of labels. Labelyard keeps track of every physical sheet, so a sheet you only half used can go back into the tray and be filled later.

## Sheet types

A **sheet type** describes a product: page size, the number of rows and columns and the measurements of a cell. Open **Sheets** to create one or to import one. Sheet types are versioned: when you correct a measurement, you add a version, and sheets that were already in use keep the version they were printed with.

Sheet types marked **verified** were measured on real sheets. Labelyard 1.7.0 adds Avery Zweckform 6121, 3490 and L4737REV (3490 has its sheet code printed on the back of the liner, see [Where the sheet code goes](#where-the-sheet-code-goes)) and corrects L4731REV (sheets you already have keep the old measurement). A type you created or imported under the same key is taken over with your prefix and its older versions kept, and the bell tells you once. A taken-over type counts as shipped from then on, so you can archive it but not delete it.

You can export a sheet type to a file and import it in this or another hub, so a product only has to be measured once.

Every sheet type has its own switch **QR codes on labels**, in the details of the type in the **Sheet archive**. A new type starts with it on when the shorter side of a label is at least 10 mm: on 25.4 × 10 mm labels a QR code with a short number beside it prints and scans. With the switch off, the labels on that type are printed without their QR code, the sheet ID label included, and the print preview marks those cells with "Code only on this sheet type". Types that already exist keep the setting they have.

## Sheets and their ID label

Each physical sheet gets its own code. When you add a sheet, you can print an ID label for it right away, so you can scan it later. A sheet knows which of its cells are free and which are used.

- **Free cells** take the next labels.
- **Unconfirmed cells** are cells of a job whose outcome is not known, for example when the printer failed mid-page. Check the sheet and confirm which of them were printed, one by one. When there are two or more, **Resolve all as printed** and **Resolve all as not printed** settle them in one go; the hub asks first and names how many cells it is about. If the number changed in the meantime, nothing is written and you are asked to check the list again.
- **Discarding** a sheet takes it out of the picker. Its code is never given out again; labels already printed stay printed.

## Where the sheet code goes

The sheet code identifies a sheet when you scan it, for example `A3490-0001`. Each sheet type says where the hub prints it; change it in the **Sheet archive**, tab **Where the code goes**:

- **Margin**: the code goes in the free band around the labels, with the sheet's first print. No extra pass.
- **Back side**: the code goes on the back of the liner, in a pass of its own.
- **Reserved cell**: one cell of the sheet holds the code and takes no label. You choose the cell; it is left out of planning, and when it is already used the code takes the first free cell.

A new sheet type chooses automatically: the margin when a band of 4 mm fits on the printer, otherwise the back side. The tab marks that option as **Default for this sheet**. Avery Zweckform 3490 has no usable margin, so its code goes on the back.

**Activating a sheet with its code on the back.** When you add such a sheet, the hub guides you in three steps: turn the sheet over along the long edge and load it top edge first, print the sheet code, then check it. The code counts as printed only after you answer **Yes, it is printed**: a finished job says nothing about smeared toner. If it smeared, **Print again** prints on the same sheet. If you close the dialog before you confirm, the sheet page offers **Print back side** later. Until then the sheet list marks the sheet **Back side missing**, and the filter of the same name shows only those sheets. The first time, the hub asks how the tray takes paper (see [How a tray takes paper](/using/printers/#how-a-tray-takes-paper)).

**Backing designs.** Many liners carry the vendor's print on the back. A backing design names its free strips, and the code goes into the first strip that takes it. Labelyard ships the design of Avery Zweckform ultragrip and links it to 3490 and 6121. Choose a design, or a plain liner, in the same tab; **Choose automatically** returns a type to the automatic choice; adding or changing a design is done through the API (`/api/v1/backing-designs`).

A sheet that you start from the print dialog, or that a Grocy label opens, follows its type in the same way. A sheet in the margin or added by hand whose code was never printed, such as a 3490 sheet from before 1.7.0, can switch to the back side when its type puts the code there: open it and choose **Print back side**.

**The Sheet code panel.** The page of every sheet has a panel **Sheet code** next to the grid. It names where the code is (in a cell, in the margin, added by hand, on the back of the liner) and whether it is printed. When a sheet has a code on the back, or one is asked for, the panel adds **Back side: missing** until you confirm it, then **Back side: confirmed**. A sheet that never asked for a code on the back has no such line and is not marked **Back side missing**. A key that may print sees the buttons:

- **Reprint margin code** prints the code into the margin of a margin sheet again, for example when the first one smeared or was cut off. Put the sheet back the way it went in the first time and choose the printer and tray. Only the code is printed: no cell is used and no label is printed. While a margin code is still on its way to the printer, a second one is refused.
- **Print back side** also works on a sheet whose code is already printed in a cell, in the margin or by hand. The sheet keeps its code where it is and gets the same code on the back as well. Until you confirm it with **Yes, the back side is printed**, the list marks the sheet **Back side missing**.

## Printing onto a sheet

Choose **Print onto a sheet**, pick the sheet (or scan its code) and the cells. The preview shows where every label goes. When not everything fits, the rest stays in the [cart](/using/cart/) for the next sheet, or the preview plans it on the next one.

If another device used cells of the same sheet while you were looking, the hub tells you and asks you to check the new plan before it prints.

## Layouts

A layout decides what a label shows: a QR code, a code, a title and a detail line, in combinations from "code only" to "QR code, code, title and detail". Layouts that need a field the item does not have are refused before printing, with the missing field named. On a sheet type with QR codes switched off, a QR layout prints its text only (see [Sheet types](#sheet-types)).
