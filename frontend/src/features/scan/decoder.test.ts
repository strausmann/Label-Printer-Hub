// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { describe, expect, it, vi } from "vitest";
import { createDecoder, type DecoderDeps, type WorkerLike } from "./decoder";

const frame = {} as ImageBitmap;

function fakeDetector(formats: string[], found: Array<{ format: string; rawValue: string }>) {
  const detect = vi.fn(async () => found);
  class Detector {
    static getSupportedFormats = async () => formats;
    detect = detect;
  }
  return { Detector: Detector as unknown as NonNullable<DecoderDeps["detector"]>, detect };
}

function fakeWorker(reply: (request: { id: number }) => Record<string, unknown>) {
  const worker: WorkerLike & { posted: unknown[] } = {
    posted: [],
    onmessage: null,
    onerror: null,
    postMessage(message) {
      this.posted.push(message);
      const response = reply(message as { id: number });
      queueMicrotask(() => this.onmessage?.({ data: response }));
    },
    terminate: vi.fn(),
  };
  return worker;
}

const ALL = ["qr_code", "code_128", "data_matrix", "ean_13"];

describe("decoder", () => {
  it("uses BarcodeDetector when it supports every format we need", async () => {
    const { Detector, detect } = fakeDetector(ALL, [{ format: "qr_code", rawValue: "https://hub.example.invalid/asset/42" }]);
    const createWorker = vi.fn();
    const decoder = await createDecoder({ detector: Detector, createWorker });
    expect(await decoder.decode(frame)).toEqual({ format: "qr_code", text: "https://hub.example.invalid/asset/42" });
    expect(detect).toHaveBeenCalledWith(frame);
    expect(createWorker).not.toHaveBeenCalled();
    expect(decoder.engine).toBe("native");
  });

  it("falls back to worker when BarcodeDetector lacks data_matrix", async () => {
    const { Detector, detect } = fakeDetector(["qr_code", "code_128"], []);
    const worker = fakeWorker(({ id }) => ({ id, hit: { format: "data_matrix", text: "HH-0042" } }));
    const decoder = await createDecoder({ detector: Detector, createWorker: () => worker });
    expect(decoder.engine).toBe("worker");
    expect(await decoder.decode(frame)).toEqual({ format: "data_matrix", text: "HH-0042" });
    expect(detect).not.toHaveBeenCalled();
    expect(worker.posted).toHaveLength(1);
    decoder.close();
    expect(worker.terminate).toHaveBeenCalled();
  });

  it("uses the worker when there is no BarcodeDetector at all", async () => {
    const worker = fakeWorker(({ id }) => ({ id, hit: null }));
    const decoder = await createDecoder({ detector: undefined, createWorker: () => worker });
    expect(decoder.engine).toBe("worker");
    expect(await decoder.decode(frame)).toBeNull();
  });

  it("falls back to the worker when asking the detector for its formats throws", async () => {
    class Broken {
      static getSupportedFormats = async () => {
        throw new Error("nope");
      };
    }
    const worker = fakeWorker(({ id }) => ({ id, hit: null }));
    const decoder = await createDecoder({ detector: Broken as unknown as DecoderDeps["detector"], createWorker: () => worker });
    expect(decoder.engine).toBe("worker");
  });

  it("a frame without a code is null, and the first detection wins", async () => {
    const empty = fakeDetector(ALL, []);
    expect(await (await createDecoder({ detector: empty.Detector, createWorker: vi.fn() })).decode(frame)).toBeNull();
    const two = fakeDetector(ALL, [
      { format: "code_128", rawValue: "A" },
      { format: "qr_code", rawValue: "B" },
    ]);
    expect(await (await createDecoder({ detector: two.Detector, createWorker: vi.fn() })).decode(frame)).toEqual({ format: "code_128", text: "A" });
  });

  it("a worker error rejects that frame and does not answer the next one with it", async () => {
    let n = 0;
    const worker = fakeWorker(({ id }) => (n++ === 0 ? { id, error: "boom" } : { id, hit: { format: "qr_code", text: "ok" } }));
    const decoder = await createDecoder({ detector: undefined, createWorker: () => worker });
    await expect(decoder.decode(frame)).rejects.toThrow("boom");
    expect(await decoder.decode(frame)).toEqual({ format: "qr_code", text: "ok" });
  });

  it("an error event from the worker rejects what is waiting", async () => {
    const worker = fakeWorker(() => ({ id: -1 }));
    worker.postMessage = function (message) {
      this.posted.push(message);
      queueMicrotask(() => this.onerror?.({ message: "load failed" }));
    };
    const decoder = await createDecoder({ detector: undefined, createWorker: () => worker });
    await expect(decoder.decode(frame)).rejects.toThrow("load failed");
  });
});
