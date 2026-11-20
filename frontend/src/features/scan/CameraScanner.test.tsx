// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { I18nProvider } from "@lingui/react";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { i18n, initI18n } from "../../i18n";
import { CameraScanner, setScanDeps, type ScanDeps } from "./CameraScanner";
import type { Decoder, ScanHit } from "./decoder";

const track = { stop: vi.fn() };
const track2 = { stop: vi.fn() };
const stream = { getTracks: () => [track, track2] } as unknown as MediaStream;
const HIT: ScanHit = { format: "qr_code", text: "sheet:L4736-0002" };
const ITEM: ScanHit = { format: "qr_code", text: "https://hub.example.invalid/asset/42" };
const OTHER: ScanHit = { format: "qr_code", text: "hello" };

function deps(hits: Array<ScanHit | null>): { deps: ScanDeps; decode: ReturnType<typeof vi.fn> } {
  const queue = [...hits];
  const decode = vi.fn(async () => queue.shift() ?? null);
  const decoder: Decoder = { engine: "native", decode, close: vi.fn() };
  return { deps: { createDecoder: async () => decoder, grabFrame: async () => ({ close() {} }) as unknown as ImageBitmap, intervalMs: 5 }, decode };
}

const ui = (props: Parameters<typeof CameraScanner>[0]) => (
  <I18nProvider i18n={i18n}>
    <CameraScanner {...props} />
  </I18nProvider>
);

beforeEach(async () => {
  await initI18n("en");
  track.stop.mockClear();
  track2.stop.mockClear();
  HTMLMediaElement.prototype.play = vi.fn(async () => {});
  Object.defineProperty(navigator, "mediaDevices", { value: { getUserMedia: vi.fn(async () => stream) }, configurable: true });
  Object.defineProperty(window, "isSecureContext", { value: true, configurable: true });
  Object.defineProperty(document, "hidden", { value: false, configurable: true });
});
afterEach(() => {
  setScanDeps(null);
  Reflect.deleteProperty(navigator, "vibrate");
});

describe("CameraScanner", () => {
  it("hands a read code to the caller and goes no further", async () => {
    setScanDeps(deps([null, HIT]).deps);
    const onHit = vi.fn();
    render(ui({ onHit }));
    await waitFor(() => expect(onHit).toHaveBeenCalledWith(HIT));
    expect(onHit).toHaveBeenCalledTimes(1);
  });

  it("a refused hit neither stops the loop nor vibrates", async () => {
    const vibrate = vi.fn();
    Object.defineProperty(navigator, "vibrate", { value: vibrate, configurable: true });
    const d = deps([ITEM, ITEM, HIT]);
    setScanDeps(d.deps);
    const onHit = vi.fn();
    render(ui({ onHit, accept: (hit) => hit.text === HIT.text }));
    await waitFor(() => expect(onHit).toHaveBeenCalledWith(HIT));
    // Both refused reads were consumed first, and only the accepted one buzzed.
    expect(d.decode.mock.calls.length).toBeGreaterThanOrEqual(3);
    expect(onHit).toHaveBeenCalledTimes(1);
    expect(vibrate).toHaveBeenCalledTimes(1);
  });

  it("the same refused text is reported once", async () => {
    const d = deps([ITEM, ITEM, ITEM, OTHER, HIT]);
    setScanDeps(d.deps);
    const onHit = vi.fn();
    const onReject = vi.fn();
    render(ui({ onHit, onReject, accept: (hit) => hit.text === HIT.text }));
    await waitFor(() => expect(onHit).toHaveBeenCalledWith(HIT));
    expect(onReject.mock.calls.map(([hit]) => (hit as ScanHit).text)).toEqual([ITEM.text, OTHER.text]);
  });

  it("a refused photo without a reject handler gets the no-code feedback", async () => {
    const d = deps([ITEM]);
    setScanDeps({ ...d.deps, grabFrame: async (source) => (source instanceof Blob ? ({ close() {} } as unknown as ImageBitmap) : null) });
    const onHit = vi.fn();
    render(ui({ onHit, accept: () => false }));
    await userEvent.upload(screen.getByLabelText("Choose a photo of a code"), new File(["x"], "code.png", { type: "image/png" }));
    expect(await screen.findByText(/No code found in this photo/)).toBeVisible();
    expect(onHit).not.toHaveBeenCalled();
  });

  it("without accept every hit goes through, as before", async () => {
    setScanDeps(deps([ITEM]).deps);
    const onHit = vi.fn();
    const onReject = vi.fn();
    render(ui({ onHit, onReject }));
    await waitFor(() => expect(onHit).toHaveBeenCalledWith(ITEM));
    expect(onReject).not.toHaveBeenCalled();
  });

  it("a refused photo is reported and is not taken as a hit", async () => {
    const d = deps([ITEM]);
    setScanDeps({ ...d.deps, grabFrame: async (source) => (source instanceof Blob ? ({ close() {} } as unknown as ImageBitmap) : null) });
    const onHit = vi.fn();
    const onReject = vi.fn();
    render(ui({ onHit, onReject, accept: () => false }));
    await userEvent.upload(screen.getByLabelText("Choose a photo of a code"), new File(["x"], "code.png", { type: "image/png" }));
    await waitFor(() => expect(onReject).toHaveBeenCalledWith(ITEM));
    expect(onHit).not.toHaveBeenCalled();
    expect(screen.queryByText(/No code found/)).toBeNull();
  });

  it("reads no frames while paused and carries on when resumed", async () => {
    const d = deps([HIT]);
    setScanDeps(d.deps);
    const onHit = vi.fn();
    const view = render(ui({ onHit, paused: true }));
    await screen.findByText("Starting the camera…").catch(() => undefined);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 60));
    });
    expect(d.decode).not.toHaveBeenCalled();
    expect(onHit).not.toHaveBeenCalled();
    view.rerender(ui({ onHit, paused: false }));
    await waitFor(() => expect(onHit).toHaveBeenCalledWith(HIT));
  });

  it("shows its own result slot and a Close button only when asked to", async () => {
    setScanDeps(deps([]).deps);
    const onClose = vi.fn();
    const view = render(ui({ onHit: vi.fn(), onClose, children: <p>slot content</p> }));
    expect(await screen.findByText("slot content")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalledTimes(1);
    view.rerender(ui({ onHit: vi.fn() }));
    expect(screen.queryByRole("button", { name: "Close" })).toBeNull();
  });

  it("reads a chosen photo and reports a photo without a code", async () => {
    const d = deps([null, HIT]);
    setScanDeps({ ...d.deps, grabFrame: async (source) => (source instanceof Blob ? ({ close() {} } as unknown as ImageBitmap) : null) });
    const onHit = vi.fn();
    render(ui({ onHit }));
    const input = screen.getByLabelText("Choose a photo of a code");
    await userEvent.upload(input, new File(["x"], "a.png", { type: "image/png" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("No code found in this photo");
    await userEvent.upload(input, new File(["x"], "b.png", { type: "image/png" }));
    await waitFor(() => expect(onHit).toHaveBeenCalledWith(HIT));
  });

  it("explains a blocked camera and offers the photo", async () => {
    (navigator.mediaDevices.getUserMedia as ReturnType<typeof vi.fn>).mockRejectedValueOnce(Object.assign(new Error("denied"), { name: "NotAllowedError" }));
    setScanDeps(deps([]).deps);
    render(ui({ onHit: vi.fn() }));
    expect(await screen.findByText(/blocked the camera/)).toBeVisible();
    expect(screen.getByLabelText("Choose a photo of a code")).toBeInTheDocument();
  });

  it("reader failure stops the camera tracks (frame loop)", async () => {
    const decoder: Decoder = { engine: "native", decode: vi.fn(async () => { throw new Error("boom"); }), close: vi.fn() };
    setScanDeps({ createDecoder: async () => decoder, grabFrame: async () => ({ close() {} }) as unknown as ImageBitmap, intervalMs: 5 });
    const view = render(ui({ onHit: vi.fn() }));
    const element = view.container.querySelector("video")!;
    await waitFor(() => expect(track.stop).toHaveBeenCalledTimes(1));
    await act(async () => {
      await new Promise((r) => setTimeout(r, 30));
    });
    view.unmount();
    expect(track.stop).toHaveBeenCalledTimes(1);
    expect(track2.stop).toHaveBeenCalledTimes(1);
    expect(element.srcObject).toBeNull();
  });

  it("reader failure stops the camera tracks (photo path)", async () => {
    const decoder: Decoder = { engine: "native", decode: vi.fn(async () => { throw new Error("boom"); }), close: vi.fn() };
    setScanDeps({ createDecoder: async () => decoder, grabFrame: async (source) => (source instanceof Blob ? ({ close() {} } as unknown as ImageBitmap) : null), intervalMs: 5 });
    const view = render(ui({ onHit: vi.fn() }));
    const element = view.container.querySelector("video")!;
    await waitFor(() => expect(element.srcObject).toBe(stream));
    expect(track.stop).not.toHaveBeenCalled();
    await userEvent.upload(screen.getByLabelText("Choose a photo of a code"), new File(["x"], "a.png", { type: "image/png" }));
    await waitFor(() => expect(track.stop).toHaveBeenCalledTimes(1));
    expect(track2.stop).toHaveBeenCalledTimes(1);
    expect(element.srcObject).toBeNull();
  });

  const failingDeps = (): ScanDeps => {
    const decoder: Decoder = { engine: "native", decode: vi.fn(async () => { throw new Error("boom"); }), close: vi.fn() };
    return { createDecoder: async () => decoder, grabFrame: async () => ({ close() {} }) as unknown as ImageBitmap, intervalMs: 5 };
  };

  it("after a reader failure, hiding and showing the tab does not reopen the camera", async () => {
    setScanDeps(failingDeps());
    render(ui({ onHit: vi.fn() }));
    await waitFor(() => expect(track.stop).toHaveBeenCalledTimes(1));
    const getUserMedia = navigator.mediaDevices.getUserMedia as ReturnType<typeof vi.fn>;
    expect(getUserMedia).toHaveBeenCalledTimes(1);
    for (const hidden of [true, false]) {
      Object.defineProperty(document, "hidden", { value: hidden, configurable: true });
      await act(async () => {
        document.dispatchEvent(new Event("visibilitychange"));
      });
    }
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(getUserMedia).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("heading", { name: "The code reader did not start" })).toBeVisible();
  });

  it("a photo failure while the camera is still starting does not let the camera open afterwards", async () => {
    let release: (value: MediaStream) => void = () => {};
    (navigator.mediaDevices.getUserMedia as ReturnType<typeof vi.fn>).mockImplementationOnce(() => new Promise<MediaStream>((r) => (release = r)));
    setScanDeps({ ...failingDeps(), grabFrame: async (source) => (source instanceof Blob ? ({ close() {} } as unknown as ImageBitmap) : null) });
    const view = render(ui({ onHit: vi.fn() }));
    const element = view.container.querySelector("video");
    await userEvent.upload(screen.getByLabelText("Choose a photo of a code"), new File(["x"], "a.png", { type: "image/png" }));
    await screen.findByRole("heading", { name: "The code reader did not start" });
    await act(async () => {
      release(stream);
    });
    expect(track.stop).toHaveBeenCalledTimes(1);
    expect(track2.stop).toHaveBeenCalledTimes(1);
    expect(element?.srcObject ?? null).toBeNull();
  });
});
