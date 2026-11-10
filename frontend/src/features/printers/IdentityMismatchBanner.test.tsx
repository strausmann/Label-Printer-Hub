import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderApp, SIGNED_IN } from "../../test-utils";
import { mockApi, PAGE_PRINTER, PRINTER_A, respond, status } from "../test-api";

afterEach(() => vi.unstubAllGlobals());

const PRINT = { ...SIGNED_IN, scope: "print" as const };
const BANNER = "Different device detected at this address. Sheet printing and the calibration page are held until an admin confirms.";
const NOTE = "No hardware identity — device swaps are not detected";
const LONG_SERIAL = "SN-" + "0123456789abcdef".repeat(4).slice(0, 61); // 64 characters
const LONG_UUID = "urn:uuid:123e4567-e89b-42d3-a456-426614174000-aaaaaaaaaaaaaaaa";

const identity = (over: Record<string, unknown> = {}) => ({
  hardware_id: "SN-0001",
  hardware_id_kind: "serial",
  hardware_id_seen_at: "2026-11-09T09:00:00Z",
  observed_id: null,
  observed_kind: null,
  ...over,
});
const swapped = identity({ observed_id: "SN-0002", observed_kind: "serial" });

function routes(printer: Record<string, unknown> & { id: string }, flagged: boolean, extra: Record<string, unknown> = {}) {
  return {
    [`GET /api/v1/printers/${printer.id}`]: printer,
    [`GET /api/v1/printers/${printer.id}/status`]: status(printer.id, { identity_mismatch: flagged }),
    [`GET /api/v1/printers/${printer.id}/queue`]: [],
    ...extra,
  };
}
const page = (over: Record<string, unknown> = {}) => ({ ...PAGE_PRINTER, ...over });
const resolveUrl = (id: string) => `/api/v1/admin/printers/${id}/identity/resolve`;

describe("IdentityMismatchBanner", () => {
  it("is not there while the device is the stored one", async () => {
    mockApi(routes(page(identity()), false));
    await renderApp({ path: `/printers/${PAGE_PRINTER.id}` });
    await screen.findByRole("heading", { level: 1, name: PAGE_PRINTER.name });
    expect(screen.queryByText(BANNER)).toBeNull();
  });

  it("tells every key about the swap, and shows a key below admin neither value nor buttons", async () => {
    mockApi(routes(page({ hardware_id: null, hardware_id_kind: null, hardware_id_seen_at: null, observed_id: null, observed_kind: null }), true));
    await renderApp({ path: `/printers/${PAGE_PRINTER.id}`, session: PRINT });
    expect(await screen.findByText(BANNER)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Same device" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Device replaced" })).toBeNull();
    expect(screen.queryByText("Stored")).toBeNull();
    const connection = await screen.findByRole("region", { name: "Connection" });
    expect(within(connection).queryByText("Serial number")).toBeNull();
    expect(screen.queryByText(NOTE)).toBeNull();
  });

  it("a key below admin never renders an identity the API sent anyway (stale cache, future backend change)", async () => {
    mockApi(routes(page(identity({ hardware_id: "LEAK-STORED", observed_id: "LEAK-OBSERVED", observed_kind: "serial" })), true));
    await renderApp({ path: `/printers/${PAGE_PRINTER.id}`, session: PRINT });
    expect(await screen.findByText(BANNER)).toBeVisible();
    const connection = await screen.findByRole("region", { name: "Connection" });
    expect(within(connection).getByText("Backend")).toBeVisible();
    expect(screen.queryByText(/LEAK-/)).toBeNull();
    expect(screen.queryByText("Stored")).toBeNull();
    expect(screen.queryByText("Now at this address")).toBeNull();
    expect(screen.queryByRole("button", { name: "Same device" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Device replaced" })).toBeNull();
    expect(within(connection).queryByText("Serial number")).toBeNull();
  });

  it("holds only the sentence in the live region; identities and buttons sit beside it", async () => {
    mockApi(routes(page(swapped), true));
    await renderApp({ path: `/printers/${PAGE_PRINTER.id}` });
    const banner = await screen.findByRole("region", { name: "Device swap" });
    const alert = within(banner).getByRole("alert");
    expect(alert).toHaveTextContent(BANNER);
    expect(within(alert).queryByRole("button")).toBeNull();
    expect(within(alert).queryByText("SN-0001")).toBeNull();
    expect(within(banner).getByRole("button", { name: "Same device" })).toBeVisible();
  });

  it("a 409 'settled already' stays readable after the banner has gone", async () => {
    let flagged = true;
    mockApi({
      ...routes(page(swapped), true),
      [`GET /api/v1/printers/${PAGE_PRINTER.id}/status`]: () => status(PAGE_PRINTER.id, { identity_mismatch: flagged }),
      [`POST ${resolveUrl(PAGE_PRINTER.id)}`]: () => {
        flagged = false;
        return respond(409, { type: "no-identity-mismatch", title: "x", status: 409, detail: "x" });
      },
    });
    await renderApp({ path: `/printers/${PAGE_PRINTER.id}` });
    await userEvent.click(await screen.findByRole("button", { name: "Same device" }));
    await waitFor(() => expect(screen.queryByText(BANNER)).toBeNull());
    expect(await screen.findByText("Someone has settled this already. The page shows the current state.")).toBeVisible();
  });

  it("shows an admin both identities, so the decision is informed", async () => {
    mockApi(routes(page(swapped), true));
    await renderApp({ path: `/printers/${PAGE_PRINTER.id}` });
    const banner = await screen.findByRole("region", { name: "Device swap" });
    expect(within(banner).getByText(BANNER)).toBeVisible();
    expect(within(banner).getByText("Stored")).toBeVisible();
    expect(within(banner).getByText("SN-0001")).toBeVisible();
    expect(within(banner).getByText("Now at this address")).toBeVisible();
    expect(within(banner).getByText("SN-0002")).toBeVisible();
    expect(within(banner).getAllByText("Serial number")).toHaveLength(2);
  });

  it("lets a 64-character serial and a long UUID wrap instead of pushing the page wide", async () => {
    mockApi(routes(page(identity({ hardware_id: LONG_SERIAL, observed_id: LONG_UUID, observed_kind: "ipp_uuid" })), true));
    await renderApp({ path: `/printers/${PAGE_PRINTER.id}` });
    const banner = await screen.findByRole("region", { name: "Device swap" });
    for (const value of [LONG_SERIAL, LONG_UUID]) {
      expect(within(banner).getByText(value).className).toContain("[overflow-wrap:anywhere]");
    }
    expect(within(banner).getByText("IPP UUID")).toBeVisible();
  });

  it("Same device posts the resolution with the values the admin saw", async () => {
    const { calls } = mockApi(routes(page(swapped), true, { [`POST ${resolveUrl(PAGE_PRINTER.id)}`]: page(identity()) }));
    await renderApp({ path: `/printers/${PAGE_PRINTER.id}` });
    await userEvent.click(await screen.findByRole("button", { name: "Same device" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    const post = calls.find((c) => c.method === "POST")!;
    expect(post.path).toBe(resolveUrl(PAGE_PRINTER.id));
    expect(post.headers.get("X-CSRF-Token")).toBe("csrf-test");
    expect(JSON.parse(post.body ?? "{}")).toEqual({ resolution: "same_device", expected_observed_id: "SN-0002", expected_observed_kind: "serial" });
  });

  it("Device replaced asks first and names the calibration reset; nothing is sent before the confirm", async () => {
    const { calls } = mockApi(routes(page(swapped), true, { [`POST ${resolveUrl(PAGE_PRINTER.id)}`]: page(identity()) }));
    await renderApp({ path: `/printers/${PAGE_PRINTER.id}` });
    await userEvent.click(await screen.findByRole("button", { name: "Device replaced" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText(/calibration of every tray/)).toBeVisible();
    expect(calls.some((c) => c.method === "POST")).toBe(false);
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(calls.some((c) => c.method === "POST")).toBe(false);

    await userEvent.click(screen.getByRole("button", { name: "Device replaced" }));
    await userEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Reset calibration and accept" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    expect(JSON.parse(calls.find((c) => c.method === "POST")!.body ?? "{}")).toEqual({
      resolution: "replaced",
      expected_observed_id: "SN-0002",
      expected_observed_kind: "serial",
    });
  });

  it("the banner goes once the status no longer reports the swap", async () => {
    let flagged = true;
    mockApi({
      ...routes(page(swapped), true),
      [`GET /api/v1/printers/${PAGE_PRINTER.id}/status`]: () => status(PAGE_PRINTER.id, { identity_mismatch: flagged }),
      [`POST ${resolveUrl(PAGE_PRINTER.id)}`]: () => {
        flagged = false;
        return page(identity());
      },
    });
    await renderApp({ path: `/printers/${PAGE_PRINTER.id}` });
    await userEvent.click(await screen.findByRole("button", { name: "Same device" }));
    await waitFor(() => expect(screen.queryByText(BANNER)).toBeNull());
  });

  it("identity-changed: tells the admin, closes the dialog and reads the printer again", async () => {
    let reads = 0;
    mockApi({
      ...routes(page(swapped), true),
      [`GET /api/v1/printers/${PAGE_PRINTER.id}`]: () => {
        reads += 1;
        return page(reads > 1 ? identity({ observed_id: "SN-0003", observed_kind: "serial" }) : swapped);
      },
      [`POST ${resolveUrl(PAGE_PRINTER.id)}`]: () => respond(409, { type: "identity-changed", title: "Changed", status: 409, detail: "changed" }),
    });
    await renderApp({ path: `/printers/${PAGE_PRINTER.id}` });
    await userEvent.click(await screen.findByRole("button", { name: "Device replaced" }));
    await userEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Reset calibration and accept" }));
    expect(await screen.findByText("The device at this address changed while you were looking. Check the values shown now before you decide.")).toBeVisible();
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(await screen.findByText("SN-0003")).toBeVisible();
  });

  it.each([
    [403, "printer_not_allowed", "This key may not settle a device swap."],
    [500, null, "The decision could not be saved. Try again."],
  ])("an answer of %s is said in words", async (code, type, words) => {
    mockApi(
      routes(page(swapped), true, {
        [`POST ${resolveUrl(PAGE_PRINTER.id)}`]: () => respond(code, type ? { type, title: "x", status: code, detail: "x" } : { detail: "boom" }),
      }),
    );
    await renderApp({ path: `/printers/${PAGE_PRINTER.id}` });
    await userEvent.click(await screen.findByRole("button", { name: "Same device" }));
    expect(await screen.findByText(words)).toBeVisible();
  });
});

describe("hardware identity in the connection section", () => {
  it.each([
    ["serial", "Serial number"],
    ["ipp_uuid", "IPP UUID"],
    ["mac", "MAC address"],
  ])("an admin sees a %s as “%s”", async (kind, label) => {
    mockApi(routes(page(identity({ hardware_id: "VALUE-1", hardware_id_kind: kind })), false));
    await renderApp({ path: `/printers/${PAGE_PRINTER.id}` });
    const connection = await screen.findByRole("region", { name: "Connection" });
    expect(within(connection).getByText(label)).toBeVisible();
    expect(within(connection).getByText("VALUE-1")).toBeVisible();
    expect(within(connection).queryByText(NOTE)).toBeNull();
  });

  it("an admin viewing a printer without an identity is told that swaps are not detected", async () => {
    mockApi(routes(page(identity({ hardware_id: null, hardware_id_kind: null, hardware_id_seen_at: null })), false));
    await renderApp({ path: `/printers/${PAGE_PRINTER.id}` });
    const connection = await screen.findByRole("region", { name: "Connection" });
    expect(within(connection).getByText(NOTE)).toBeVisible();
  });

  it("a key below admin sees neither the identity nor the note", async () => {
    mockApi(routes(page(identity({ hardware_id: null, hardware_id_kind: null })), false));
    await renderApp({ path: `/printers/${PAGE_PRINTER.id}`, session: PRINT });
    const connection = await screen.findByRole("region", { name: "Connection" });
    expect(within(connection).queryByText(NOTE)).toBeNull();
    expect(within(connection).queryByText("Serial number")).toBeNull();
  });

  it("a tape printer shows it too", async () => {
    mockApi(routes({ ...PRINTER_A, ...identity({ hardware_id: "TAPE-9", hardware_id_kind: "serial" }) }, false));
    await renderApp({ path: `/printers/${PRINTER_A.id}` });
    const connection = await screen.findByRole("region", { name: "Connection" });
    expect(within(connection).getByText("TAPE-9")).toBeVisible();
  });
});

describe("the printer card", () => {
  it("warns with “Different device” while the swap is pending, and only then", async () => {
    mockApi({
      "GET /api/v1/printers": [PRINTER_A, PAGE_PRINTER],
      [`GET /api/v1/printers/${PRINTER_A.id}/status`]: status(PRINTER_A.id),
      [`GET /api/v1/printers/${PAGE_PRINTER.id}/status`]: status(PAGE_PRINTER.id, { identity_mismatch: true }),
    });
    await renderApp({ path: "/printers" });
    const flagged = (await screen.findByText(PAGE_PRINTER.name)).closest("a")!;
    expect(within(flagged).getByText("Different device")).toBeVisible();
    const other = screen.getByText(PRINTER_A.name).closest("a")!;
    expect(within(other).queryByText("Different device")).toBeNull();
  });
});
