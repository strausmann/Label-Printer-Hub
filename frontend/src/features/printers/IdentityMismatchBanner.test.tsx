import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderApp, SIGNED_IN } from "../../test-utils";
import { mockApi, PAGE_PRINTER, PRINTER_A, pageStatus, respond, status } from "../test-api";

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

  it("settled notice resets: a swap that comes back is not answered with the note of the last one", async () => {
    let flagged = true;
    let posts = 0;
    mockApi({
      ...routes(page(swapped), true),
      [`GET /api/v1/printers/${PAGE_PRINTER.id}/status`]: () => status(PAGE_PRINTER.id, { identity_mismatch: flagged }),
      [`POST ${resolveUrl(PAGE_PRINTER.id)}`]: () => {
        posts += 1;
        flagged = false;
        return posts === 1 ? respond(409, { type: "no-identity-mismatch", title: "x", status: 409, detail: "x" }) : page(identity());
      },
    });
    const { queryClient } = await renderApp({ path: `/printers/${PAGE_PRINTER.id}` });
    const NOTE_SETTLED = "Someone has settled this already. The page shows the current state.";
    await userEvent.click(await screen.findByRole("button", { name: "Same device" }));
    expect(await screen.findByText(NOTE_SETTLED)).toBeVisible();

    // The swap comes back: the banner replaces the note …
    flagged = true;
    await act(async () => {
      await queryClient.invalidateQueries({ queryKey: ["printers", PAGE_PRINTER.id, "status"] });
    });
    expect(await screen.findByText(BANNER)).toBeVisible();
    expect(screen.queryByText(NOTE_SETTLED)).toBeNull();

    // … and when this one is settled properly, the old note stays away.
    await userEvent.click(screen.getByRole("button", { name: "Same device" }));
    await waitFor(() => expect(screen.queryByText(BANNER)).toBeNull());
    expect(screen.queryByText(NOTE_SETTLED)).toBeNull();
  });

  it("the note does not follow the admin to another printer", async () => {
    let flagged = true;
    const other = { ...PRINTER_A, backend: "ipp", observed_id: null };
    mockApi({
      ...routes(page(swapped), true),
      [`GET /api/v1/printers/${PAGE_PRINTER.id}/status`]: () => status(PAGE_PRINTER.id, { identity_mismatch: flagged }),
      [`POST ${resolveUrl(PAGE_PRINTER.id)}`]: () => {
        flagged = false;
        return respond(409, { type: "no-identity-mismatch", title: "x", status: 409, detail: "x" });
      },
      ...routes(other, false),
    });
    const { router } = await renderApp({ path: `/printers/${PAGE_PRINTER.id}` });
    await userEvent.click(await screen.findByRole("button", { name: "Same device" }));
    expect(await screen.findByText("Someone has settled this already. The page shows the current state.")).toBeVisible();
    await act(async () => {
      await router.navigate({ to: "/printers/$printerId", params: { printerId: other.id } });
    });
    expect(await screen.findByRole("heading", { level: 1, name: other.name })).toBeVisible();
    expect(screen.queryByText("Someone has settled this already. The page shows the current state.")).toBeNull();
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
      [`POST ${resolveUrl(PAGE_PRINTER.id)}`]: () => respond(409, { detail: { error_code: "identity-changed", error_message: "changed" } }),
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

describe("a held printer (263-51)", () => {
  const P = PAGE_PRINTER.id;
  const heldRoutes = (held: boolean) => ({
    "GET /api/v1/printers": [page(identity())],
    [`GET /api/v1/printers/${P}`]: page(identity(held ? { observed_id: "SN-0002", observed_kind: "serial" } : {})),
    [`GET /api/v1/printers/${P}/status`]: pageStatus(P, { identity_mismatch: held }),
    [`GET /api/v1/printers/${P}/queue`]: [],
    [`GET /api/v1/printers/${P}/calibration`]: [
      { tray: "main", offset_x_mm: 0.4, offset_y_mm: -0.2, scale_x: 1, scale_y: 1, rotation_deg: 0.1, method: "manual", updated_at: "2026-11-03T10:00:00Z", measured_on: null },
    ],
    "GET /api/v1/jobs": [],
  });

  it("hold shapes headline: the card and the detail page say Different device, not Ready", async () => {
    mockApi(heldRoutes(true));
    const list = await renderApp({ path: "/printers" });
    const card = (await screen.findByRole("link", { name: new RegExp(PAGE_PRINTER.name) })) as HTMLElement;
    expect(await within(card).findByText("Different device")).toBeVisible();
    // One badge, not a second one next to "Ready".
    expect(within(card).getAllByText("Different device")).toHaveLength(1);
    expect(within(card).queryByText("Ready")).toBeNull();
    list.unmount();

    await renderApp({ path: `/printers/${P}` });
    const header = (await screen.findByRole("heading", { level: 1, name: PAGE_PRINTER.name })).closest("header")!;
    expect(await within(header).findByText("Different device")).toBeVisible();
    expect(within(header).queryByText("Ready")).toBeNull();
  });

  it("an ordinary printer still reads Ready", async () => {
    mockApi(heldRoutes(false));
    await renderApp({ path: `/printers/${P}` });
    const header = (await screen.findByRole("heading", { level: 1, name: PAGE_PRINTER.name })).closest("header")!;
    expect(await within(header).findByText("Ready")).toBeVisible();
  });

  it("calibrate disabled while held: the buttons are off and the reason stands beside them", async () => {
    mockApi(heldRoutes(true));
    await renderApp({ path: `/printers/${P}`, info: { features: { calibration: true } } });
    const section = await screen.findByRole("region", { name: "Calibration" });
    const button = await within(section).findByRole("button", { name: "Calibrate Main tray" });
    expect(button).toBeDisabled();
    expect(within(section).queryByRole("link", { name: "Calibrate Main tray" })).toBeNull();
    expect(within(section).getByText("Calibration is held until an admin settles the device swap.")).toBeVisible();
    expect(button).toHaveAccessibleDescription("Calibration is held until an admin settles the device swap.");
  });

  it("calibrate stays a link when the printer is not held", async () => {
    mockApi(heldRoutes(false));
    await renderApp({ path: `/printers/${P}`, info: { features: { calibration: true } } });
    const section = await screen.findByRole("region", { name: "Calibration" });
    expect(await within(section).findByRole("link", { name: "Calibrate Main tray" })).toBeVisible();
    expect(within(section).queryByText(/held/)).toBeNull();
  });
});
