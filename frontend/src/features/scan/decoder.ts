// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

/** What a camera frame turned out to hold. `format` uses the BarcodeDetector spelling. */
export interface ScanHit {
  format: string;
  text: string;
}

export interface Decoder {
  /** Which engine reads the frames: the browser's own detector or the WebAssembly worker. */
  engine: "native" | "worker";
  /** The first code in the frame, or null. Rejects when the engine itself failed. */
  decode(frame: ImageBitmap): Promise<ScanHit | null>;
  close(): void;
}

/** The formats the hub's labels use: QR first, then ASN labels and some printed codes. */
export const SCAN_FORMATS = ["qr_code", "code_128", "data_matrix"] as const;

interface DetectorInstance {
  detect(frame: ImageBitmap): Promise<Array<{ format: string; rawValue: string }>>;
}
interface DetectorClass {
  new (options: { formats: string[] }): DetectorInstance;
  getSupportedFormats(): Promise<string[]>;
}

/** The slice of `Worker` the decoder uses, so tests can stand in for it. */
export interface WorkerLike {
  onmessage: ((event: { data: unknown }) => void) | null;
  onerror: ((event: { message?: string }) => void) | null;
  postMessage(message: unknown, transfer?: Transferable[]): void;
  terminate(): void;
}

export interface DecoderDeps {
  /** `BarcodeDetector` of the page, if it has one. */
  detector?: DetectorClass | undefined;
  createWorker: () => WorkerLike;
}

/** Messages between `createDecoder` and `decoder.worker.ts`. */
export interface WorkerRequest {
  id: number;
  frame: ImageBitmap;
}
export type WorkerResponse = { id: number; hit: ScanHit | null } | { id: number; error: string };

const pageDetector = (): DetectorClass | undefined => (globalThis as { BarcodeDetector?: DetectorClass }).BarcodeDetector;

/** Moves the ZXing build into its own thread; it loads from this origin (CSP: worker-src 'self'). */
const defaultWorker = (): WorkerLike => new Worker(new URL("./decoder.worker.ts", import.meta.url), { type: "module" }) as unknown as WorkerLike;

async function nativeIfComplete(Detector: DetectorClass | undefined): Promise<DetectorInstance | null> {
  if (!Detector) return null;
  try {
    const supported = await Detector.getSupportedFormats();
    // One engine for every format: a detector that lacks one of them would silently never see it.
    if (!SCAN_FORMATS.every((f) => supported.includes(f))) return null;
    return new Detector({ formats: [...SCAN_FORMATS] });
  } catch {
    return null;
  }
}

function workerDecoder(worker: WorkerLike): Decoder {
  let next = 0;
  const waiting = new Map<number, { resolve(hit: ScanHit | null): void; reject(error: Error): void }>();
  worker.onmessage = (event) => {
    const response = event.data as WorkerResponse;
    const entry = waiting.get(response.id);
    if (!entry) return;
    waiting.delete(response.id);
    if ("error" in response) entry.reject(new Error(response.error));
    else entry.resolve(response.hit);
  };
  worker.onerror = (event) => {
    const error = new Error(event.message || "The code reader failed to start");
    for (const entry of waiting.values()) entry.reject(error);
    waiting.clear();
  };
  return {
    engine: "worker",
    decode(frame) {
      const id = next++;
      return new Promise<ScanHit | null>((resolve, reject) => {
        waiting.set(id, { resolve, reject });
        worker.postMessage({ id, frame } satisfies WorkerRequest, [frame]);
      });
    },
    close() {
      worker.terminate();
      for (const entry of waiting.values()) entry.reject(new Error("closed"));
      waiting.clear();
    },
  };
}

/**
 * The browser's BarcodeDetector when it reads every format we need, otherwise the ZXing
 * WebAssembly build in a worker.
 */
export async function createDecoder(deps: DecoderDeps = { detector: pageDetector(), createWorker: defaultWorker }): Promise<Decoder> {
  const native = await nativeIfComplete(deps.detector);
  if (native) {
    return {
      engine: "native",
      async decode(frame) {
        const [first] = await native.detect(frame);
        return first ? { format: first.format, text: first.rawValue } : null;
      },
      close() {},
    };
  }
  return workerDecoder(deps.createWorker());
}
