import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderApp, SIGNED_IN } from "../../test-utils";
import { GEOMETRY_L4736, mockApi, SHEET_TYPE } from "../test-api";
import { FEEDBACK_BASE } from "./feedbackLink";

const PRINT_SESSION = { ...SIGNED_IN, scope: "print" as const };
const VERSION = {
  version: 1,
  change_note: null as string | null,
  created_at: "2026-11-01T08:00:00Z",
  geometry: GEOMETRY_L4736,
  geometry_hash: "abc",
  sheets: 3,
};
const unverified = { ...SHEET_TYPE, verified: false, sheets_in_use: 3, versions: [VERSION] };
const verified = { ...unverified, verified: true };
const path = "/sheets/archive?type=L4736REV";
const routes = (detail: object) => ({
  "GET /api/v1/sheet-types": [SHEET_TYPE],
  "GET /api/v1/sheet-types/L4736REV": detail,
});

afterEach(() => vi.unstubAllGlobals());

describe("sheet type feedback links", () => {
  it("every role sees both links, opening the pre-filled issue in a new tab", async () => {
    mockApi(routes(unverified));
    await renderApp({ path, session: PRINT_SESSION });
    const report = await screen.findByRole("link", { name: "Report a problem with the dimensions" });
    const confirm = screen.getByRole("link", { name: "Confirm the dimensions" });
    for (const link of [report, confirm]) {
      expect(link.getAttribute("href")!.startsWith(FEEDBACK_BASE)).toBe(true);
      expect(link).toHaveAttribute("target", "_blank");
      expect(link).toHaveAttribute("rel", "noopener noreferrer");
    }
    const wrong = new URL(report.getAttribute("href")!).searchParams;
    expect(wrong.get("title")).toBe("[sheet type] L4736REV v1: dimensions wrong");
    expect(wrong.get("labels")).toBe("area:sheets,type:bug");
    expect(wrong.get("hub_version")).toBe("0.0.0-test");
    expect(wrong.get("scheme")).toBe("http");
    expect(new URL(confirm.getAttribute("href")!).searchParams.get("labels")).toBe("area:sheets,type:feedback");
  });

  it("nothing of the page travels in the address", async () => {
    mockApi(routes(unverified));
    await renderApp({ path, session: PRINT_SESSION });
    const report = await screen.findByRole("link", { name: "Report a problem with the dimensions" });
    const text = decodeURIComponent(report.getAttribute("href")!);
    expect(text).not.toContain(window.location.host || "localhost");
    expect(text).not.toContain("csrf");
  });

  it("the verify action is for admins only", async () => {
    mockApi(routes(unverified));
    await renderApp({ path, session: PRINT_SESSION });
    await screen.findByRole("link", { name: "Confirm the dimensions" });
    expect(screen.queryByRole("button", { name: "Mark as verified locally" })).toBeNull();
  });

  it("an already verified type offers no verify action", async () => {
    mockApi(routes(verified));
    await renderApp({ path });
    await screen.findByRole("link", { name: "Confirm the dimensions" });
    expect(screen.queryByRole("button", { name: "Mark as verified locally" })).toBeNull();
  });

  it("sends the PATCH only after the confirm dialog, and never from a link", async () => {
    const { calls } = mockApi({ ...routes(unverified), "PATCH /api/v1/sheet-types/L4736REV": { ...SHEET_TYPE, verified: true } });
    await renderApp({ path });
    await userEvent.click(await screen.findByRole("link", { name: "Confirm the dimensions" }));
    expect(calls.some((c) => c.method === "PATCH")).toBe(false);

    await userEvent.click(screen.getByRole("button", { name: "Mark as verified locally" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(calls.some((c) => c.method === "PATCH")).toBe(false);

    // Cancel sends nothing.
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(calls.some((c) => c.method === "PATCH")).toBe(false);

    await userEvent.click(screen.getByRole("button", { name: "Mark as verified locally" }));
    await userEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Mark as verified" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "PATCH")).toHaveLength(1));
    const patch = calls.find((c) => c.method === "PATCH")!;
    expect(patch.path).toBe("/api/v1/sheet-types/L4736REV");
    expect(JSON.parse(patch.body!)).toEqual({ verified: true });
  });

  it("speaks German with real umlauts", async () => {
    mockApi(routes(unverified));
    await renderApp({ path, language: "de" });
    expect(await screen.findByRole("link", { name: "Ein Problem mit den Maßen melden" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Die Maße bestätigen" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Lokal als geprüft markieren" })).toBeVisible();
  });
});
