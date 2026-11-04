import { createMemoryHistory } from "@tanstack/react-router";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../../App";
import { createQueryClient } from "../../app/queryClient";
import { createAppRouter } from "../../app/router";
import { INFO_KEY, SESSION_KEY } from "../../app/session";
import { initI18n } from "../../i18n";
import { INFO, SIGNED_IN } from "../../test-utils";
import { mockApi } from "../test-api";
import type { Decoder, ScanHit } from "./decoder";
import { setScanDeps, type ScanDeps } from "./ScanScreen";

const setSecure = (value: boolean) => Object.defineProperty(window, "isSecureContext", { value, configurable: true });

const track = { stop: vi.fn() };
const stream = { getTracks: () => [track] } as unknown as MediaStream;
const setHidden = (hidden: boolean) => {
  Object.defineProperty(document, "hidden", { value: hidden, configurable: true });
  document.dispatchEvent(new Event("visibilitychange"));
};

function deps(hits: Array<ScanHit | null>, over: Partial<ScanDeps> = {}): ScanDeps {
  const queue = [...hits];
  const decoder: Decoder = { engine: "native", decode: vi.fn(async () => queue.shift() ?? null), close: vi.fn() };
  return {
    createDecoder: async () => decoder,
    grabFrame: async () => ({ close() {} }) as unknown as ImageBitmap,
    intervalMs: 5,
    ...over,
  };
}

/** The real shell and router, with the scan route's screen swapped for one with fake plumbing. */
async function mount(d: ScanDeps) {
  await initI18n("en");
  const queryClient = createQueryClient();
  queryClient.setQueryData(INFO_KEY, INFO);
  queryClient.setQueryData(SESSION_KEY, SIGNED_IN);
  const router = createAppRouter({ history: createMemoryHistory({ initialEntries: ["/scan"] }) });
  setScanDeps(d);
  render(<App queryClient={queryClient} router={router} />);
  await act(async () => {
    await router.load();
  });
  return router;
}

beforeEach(() => {
  mockApi({});
  track.stop.mockClear();
  HTMLMediaElement.prototype.play = vi.fn(async () => {});
  Object.defineProperty(navigator, "mediaDevices", { value: { getUserMedia: vi.fn(async () => stream) }, configurable: true });
  setSecure(true);
  Object.defineProperty(document, "hidden", { value: false, configurable: true });
});
afterEach(() => {
  vi.unstubAllGlobals();
  setScanDeps(null);
});

const getUserMedia = () => navigator.mediaDevices.getUserMedia as ReturnType<typeof vi.fn>;

describe("ScanScreen", () => {
  it("insecure context shows the HTTPS message", async () => {
    setSecure(false);
    await mount(deps([]));
    expect(await screen.findByRole("heading", { level: 1, name: "Scan" })).toBeVisible();
    expect(screen.getByText(/needs a secure connection \(HTTPS\) or localhost/)).toBeVisible();
    expect(getUserMedia()).not.toHaveBeenCalled();
    // A photo of the code still works without a camera stream.
    expect(screen.getByLabelText("Choose a photo of a code")).toBeInTheDocument();
  });

  it("explains how to allow the camera when it was denied", async () => {
    getUserMedia().mockRejectedValueOnce(Object.assign(new Error("denied"), { name: "NotAllowedError" }));
    await mount(deps([]));
    expect(await screen.findByText(/blocked the camera/)).toBeVisible();
    expect(screen.getByText(/site settings/i)).toBeVisible();
    expect(screen.getByRole("button", { name: "Try again" })).toBeVisible();
  });

  it("says so when there is no camera", async () => {
    getUserMedia().mockRejectedValueOnce(Object.assign(new Error("none"), { name: "NotFoundError" }));
    await mount(deps([]));
    expect(await screen.findByText(/No camera was found/)).toBeVisible();
  });

  it("a printed asset label leads straight to its item and stops the camera", async () => {
    const router = await mount(deps([null, { format: "qr_code", text: "https://hub.example.invalid/asset/42" }]));
    await waitFor(() => expect(router.state.location.pathname).toBe("/asset/42"));
    expect(track.stop).toHaveBeenCalled();
  });

  it("an unknown code is shown in the code font with a copy button, and scanning can resume", async () => {
    const writeText = vi.fn(async () => {});
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    const router = await mount(deps([{ format: "qr_code", text: "WIFI:S:guest;T:WPA;P:fake;;" }, { format: "code_128", text: "HH-0042" }]));
    expect(await screen.findByRole("heading", { name: "Unknown code" })).toBeVisible();
    const code = screen.getByText("WIFI:S:guest;T:WPA;P:fake;;");
    expect(code.tagName).toBe("CODE");
    expect(router.state.location.pathname).toBe("/scan");
    await userEvent.click(screen.getByRole("button", { name: "Copy" }));
    expect(writeText).toHaveBeenCalledWith("WIFI:S:guest;T:WPA;P:fake;;");
    expect(await screen.findByRole("button", { name: "Copied" })).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Scan again" }));
    expect(await screen.findByText("HH-0042")).toBeVisible();
  });

  it("a photo of a code is decoded like a camera frame, also without a secure connection", async () => {
    setSecure(false);
    const router = await mount(deps([{ format: "data_matrix", text: "https://hub.example.invalid/spool/5" }]));
    const input = await screen.findByLabelText("Choose a photo of a code");
    await userEvent.upload(input, new File([new Uint8Array([137, 80, 78, 71])], "label.png", { type: "image/png" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/spool/5"));
  });

  it("a photo without a readable code says so", async () => {
    setSecure(false);
    await mount(deps([null]));
    await userEvent.upload(await screen.findByLabelText("Choose a photo of a code"), new File([new Uint8Array([1])], "x.png", { type: "image/png" }));
    expect(await screen.findByText(/No code found in this photo/)).toBeVisible();
  });

  it("stops the camera when the screen is left", async () => {
    const router = await mount(deps([]));
    await waitFor(() => expect(getUserMedia()).toHaveBeenCalled());
    await act(async () => {
      await router.navigate({ to: "/jobs" });
    });
    await waitFor(() => expect(track.stop).toHaveBeenCalled());
  });

  it("releases the camera while the tab is hidden and takes it again when it is shown", async () => {
    const decode = vi.fn(async () => null);
    const router = await mount(
      deps([], { createDecoder: async () => ({ engine: "native", decode, close: vi.fn() }) }),
    );
    await waitFor(() => expect(getUserMedia()).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(decode).toHaveBeenCalled());
    expect(track.stop).not.toHaveBeenCalled();

    await act(async () => setHidden(true));
    expect(track.stop).toHaveBeenCalledTimes(1);
    // The read loop is quiet while hidden.
    const reads = decode.mock.calls.length;
    await new Promise((r) => setTimeout(r, 40));
    expect(decode.mock.calls.length).toBe(reads);
    expect(getUserMedia()).toHaveBeenCalledTimes(1);

    await act(async () => setHidden(false));
    await waitFor(() => expect(getUserMedia()).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(decode.mock.calls.length).toBeGreaterThan(reads));

    await act(async () => {
      await router.navigate({ to: "/jobs" });
    });
    await waitFor(() => expect(track.stop).toHaveBeenCalledTimes(2));
  });

  it("does not open the camera when the screen is opened in a hidden tab", async () => {
    Object.defineProperty(document, "hidden", { value: true, configurable: true });
    await mount(deps([]));
    await new Promise((r) => setTimeout(r, 30));
    expect(getUserMedia()).not.toHaveBeenCalled();
  });
});
