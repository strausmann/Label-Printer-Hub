import { I18nProvider } from "@lingui/react";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { i18n, initI18n } from "../../i18n";
import { CameraScanner, setScanDeps, type ScanDeps } from "./CameraScanner";
import type { Decoder, ScanHit } from "./decoder";

const track = { stop: vi.fn() };
const stream = { getTracks: () => [track] } as unknown as MediaStream;
const HIT: ScanHit = { format: "qr_code", text: "sheet:L4736-0002" };

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
  HTMLMediaElement.prototype.play = vi.fn(async () => {});
  Object.defineProperty(navigator, "mediaDevices", { value: { getUserMedia: vi.fn(async () => stream) }, configurable: true });
  Object.defineProperty(window, "isSecureContext", { value: true, configurable: true });
  Object.defineProperty(document, "hidden", { value: false, configurable: true });
});
afterEach(() => setScanDeps(null));

describe("CameraScanner", () => {
  it("hands a read code to the caller and goes no further", async () => {
    setScanDeps(deps([null, HIT]).deps);
    const onHit = vi.fn();
    render(ui({ onHit }));
    await waitFor(() => expect(onHit).toHaveBeenCalledWith(HIT));
    expect(onHit).toHaveBeenCalledTimes(1);
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
});
