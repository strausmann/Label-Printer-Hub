// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

/// <reference lib="webworker" />
import { prepareZXingModule, readBarcodes } from "zxing-wasm/reader";
// Bundled by Vite and served from this origin: no CDN, and the CSP stays at worker-src 'self'.
import wasmUrl from "zxing-wasm/reader/zxing_reader.wasm?url";
import type { ScanHit, WorkerRequest, WorkerResponse } from "./decoder";

// ZXing's names for the formats in SCAN_FORMATS (BarcodeDetector spelling on our side).
const FORMAT_NAMES: Record<string, string> = { QRCode: "qr_code", Code128: "code_128", DataMatrix: "data_matrix" };

prepareZXingModule({
  overrides: { locateFile: (path: string, prefix: string) => (path.endsWith(".wasm") ? wasmUrl : prefix + path) },
  fireImmediately: false,
});

function toImageData(frame: ImageBitmap): ImageData {
  const canvas = new OffscreenCanvas(frame.width, frame.height);
  const context = canvas.getContext("2d", { willReadFrequently: true })!;
  context.drawImage(frame, 0, 0);
  return context.getImageData(0, 0, frame.width, frame.height);
}

self.onmessage = async (event: MessageEvent<WorkerRequest>) => {
  const { id, frame } = event.data;
  let response: WorkerResponse;
  try {
    const image = toImageData(frame);
    frame.close();
    const [first] = await readBarcodes(image, {
      formats: ["QRCode", "Code128", "DataMatrix"],
      tryHarder: true,
      maxNumberOfSymbols: 1,
    });
    const hit: ScanHit | null = first?.isValid && FORMAT_NAMES[first.format] ? { format: FORMAT_NAMES[first.format]!, text: first.text } : null;
    response = { id, hit };
  } catch (error) {
    response = { id, error: error instanceof Error ? error.message : String(error) };
  }
  self.postMessage(response);
};
