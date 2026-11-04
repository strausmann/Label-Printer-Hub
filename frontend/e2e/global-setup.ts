import { FAKE_CAMERA } from "./env";
import { writeFakeCameraFile } from "./fake-camera";

/** Draws the codes the fake camera shows; made at test time so no picture is checked in. */
export default async function globalSetup(): Promise<void> {
  await writeFakeCameraFile(FAKE_CAMERA.qr, FAKE_CAMERA.qrText, "QRCode");
  await writeFakeCameraFile(FAKE_CAMERA.dataMatrix, FAKE_CAMERA.dataMatrixText, "DataMatrix");
}
