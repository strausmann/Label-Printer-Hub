// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { FAKE_CAMERA } from "./env";
import { singleCode, writeFakeCameraFile } from "./fake-camera";

/** Draws the codes the fake camera shows; made at test time so no picture is checked in. */
export default async function globalSetup(): Promise<void> {
  await writeFakeCameraFile(FAKE_CAMERA.qr, singleCode(FAKE_CAMERA.qrText, "QRCode"));
  await writeFakeCameraFile(FAKE_CAMERA.dataMatrix, singleCode(FAKE_CAMERA.dataMatrixText, "DataMatrix"));
  await writeFakeCameraFile(FAKE_CAMERA.sheet, singleCode(FAKE_CAMERA.sheetText, "QRCode"));
  await writeFakeCameraFile(FAKE_CAMERA.grocycode, singleCode(FAKE_CAMERA.grocycodeText, "QRCode"));
  await writeFakeCameraFile(FAKE_CAMERA.grocyBattery, singleCode(FAKE_CAMERA.grocyBatteryText, "QRCode"));
  // An item label first (two seconds), then the sheet's code: the print dialog has to skip the first and take the second.
  await writeFakeCameraFile(FAKE_CAMERA.itemThenSheet, [
    { text: FAKE_CAMERA.qrText, format: "QRCode", frames: 60 },
    { text: FAKE_CAMERA.sheetText, format: "QRCode", frames: 60 },
  ]);
}
