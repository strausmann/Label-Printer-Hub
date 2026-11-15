---
title: Scanning
description: Scan barcodes, printed labels and sheet codes with the phone's camera, or pick a photo instead.
---

The web UI can scan with the camera of your phone or laptop. Install it on the phone's home screen first: open the hub's address in the browser and accept "Add to Home Screen". It then opens like an app.

## What you can scan

- **A barcode or ID of an item**, for example a Snipe-IT asset tag or a Grocy product barcode. The hub looks it up in the app that owns it and shows its label, ready to print or to put into the cart.
- **A label the hub printed.** Its QR code is a label link (`/asset/…`, `/loc/…`, `/spool/…`, `/product/…`) that opens the item again.
- **A sheet code**, to choose that physical sheet when you print onto a sheet.

You can type an ID instead of scanning it: an asset tag (`AT-0042`), a numeric ID (`42`) or a printed label link. Locations need the `loc:` prefix, for example `loc:17`.

## When the camera does not start

| Message | Cause | Fix |
|---|---|---|
| The camera needs a secure connection | The page is not `https` and not `localhost` | Open the hub at its [HTTPS](/install/https/) address |
| The camera is blocked | The browser denied the permission | Allow the camera for the site in the browser settings |
| No camera | The device has none | Choose a photo of the code instead |
| Another app may be using the camera | It is busy | Close the other app and try again |

Picking a photo works everywhere: the hub reads the code from the image. If it finds none, hold the camera closer and take the photo again.
