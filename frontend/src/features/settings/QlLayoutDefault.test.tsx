import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderApp } from "../../test-utils";
import { ADMIN_PRINTER, mockApi, PRINTER_B, type Call } from "../test-api";

afterEach(() => vi.unstubAllGlobals());

const QL_PRINTER = (layout_defaults: Record<string, unknown> = {}) => ({
  ...ADMIN_PRINTER,
  id: PRINTER_B.id,
  name: PRINTER_B.name,
  slug: "office-ql",
  model: "QL-820NWB",
  backend: "brother_ql",
  layout_defaults,
});
const lastPut = (calls: Call[]) => JSON.parse(calls.filter((c) => c.method === "PUT").at(-1)!.body!) as Record<string, unknown>;

describe("QL printer form", () => {
  it("has no half-cut control: a QL printer always cuts fully", async () => {
    mockApi({ "GET /api/v1/admin/printers": [QL_PRINTER()] });
    await renderApp({ path: "/settings/printers" });
    await userEvent.click(await screen.findByRole("button", { name: "Edit Office QL-820NWB" }));
    expect(screen.queryByRole("switch", { name: "Half cut by default" })).toBeNull();
  });

  it("QL form does not send half_cut", async () => {
    const { calls } = mockApi({
      "GET /api/v1/admin/printers": [QL_PRINTER({ "62": { orientation: "along" } })],
      "PUT /api/v1/admin/printers/office-ql": QL_PRINTER(),
    });
    await renderApp({ path: "/settings/printers" });
    await userEvent.click(await screen.findByRole("button", { name: "Edit Office QL-820NWB" }));
    await userEvent.click(screen.getByRole("button", { name: "Save printer" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    const sent = calls.filter((c) => c.method === "PUT").at(-1)!.body!;
    expect(sent).not.toContain("half_cut");
    expect(sent).not.toContain("cut_defaults");
  });

  it("QL form does not send half_cut on create either", async () => {
    const { calls } = mockApi({
      "GET /api/v1/admin/printers": [],
      "POST /api/v1/admin/printers": QL_PRINTER(),
    });
    await renderApp({ path: "/settings/printers" });
    await userEvent.click(await screen.findByRole("button", { name: "Add printer" }));
    await userEvent.click(screen.getByRole("button", { name: /Driver/ }));
    await userEvent.click(await screen.findByRole("option", { name: "Brother QL" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Name" }), "Office QL-820NWB");
    await userEvent.type(screen.getByRole("textbox", { name: "Slug" }), "office-ql");
    await userEvent.type(screen.getByRole("textbox", { name: "Host" }), "192.0.2.11");
    await userEvent.click(screen.getByRole("button", { name: "Create printer" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    const sent = calls.filter((c) => c.method === "POST").at(-1)!.body!;
    expect(JSON.parse(sent)).toMatchObject({ backend: "brother_ql", slug: "office-ql" });
    expect(sent).not.toContain("half_cut");
    expect(sent).not.toContain("cut_defaults");
  });

  it("a P-touch printer keeps the half-cut control", async () => {
    mockApi({ "GET /api/v1/admin/printers": [ADMIN_PRINTER] });
    await renderApp({ path: "/settings/printers" });
    await userEvent.click(await screen.findByRole("button", { name: "Edit Workshop PT-P750W" }));
    expect(screen.getByRole("switch", { name: "Half cut by default" })).toBeVisible();
    expect(screen.queryByRole("radiogroup", { name: "Direction" })).toBeNull();
  });

  it("shows the stored default for 62 mm and saves a change, keeping the other widths", async () => {
    const stored = { "62": { orientation: "across", preset: "small_qr" }, "12": { orientation: "along", preset: null } };
    const { calls } = mockApi({
      "GET /api/v1/admin/printers": [QL_PRINTER(stored)],
      "PUT /api/v1/admin/printers/office-ql": QL_PRINTER(stored),
    });
    await renderApp({ path: "/settings/printers" });
    await userEvent.click(await screen.findByRole("button", { name: "Edit Office QL-820NWB" }));
    expect(screen.getByRole("radio", { name: "Small QR" })).toBeChecked();
    await userEvent.click(screen.getByRole("radio", { name: "Standard" }));
    await userEvent.click(screen.getByRole("button", { name: "Save printer" }));
    await waitFor(() =>
      expect(lastPut(calls).layout_defaults).toEqual({
        "62": { orientation: "across", preset: "standard" },
        "12": { orientation: "along", preset: null },
      }),
    );
  });

  it("saves along without a preset", async () => {
    const { calls } = mockApi({
      "GET /api/v1/admin/printers": [QL_PRINTER()],
      "PUT /api/v1/admin/printers/office-ql": QL_PRINTER(),
    });
    await renderApp({ path: "/settings/printers" });
    await userEvent.click(await screen.findByRole("button", { name: "Edit Office QL-820NWB" }));
    expect(screen.getByRole("radio", { name: "Compact" })).toBeChecked();
    await userEvent.click(screen.getByRole("radio", { name: "Along" }));
    await userEvent.click(screen.getByRole("button", { name: "Save printer" }));
    await waitFor(() => expect(lastPut(calls).layout_defaults).toEqual({ "62": { orientation: "along" } }));
  });

  it("leaves the stored defaults alone when the default was not touched", async () => {
    const { calls } = mockApi({
      "GET /api/v1/admin/printers": [QL_PRINTER({ "62": { orientation: "along" } })],
      "PUT /api/v1/admin/printers/office-ql": QL_PRINTER(),
    });
    await renderApp({ path: "/settings/printers" });
    await userEvent.click(await screen.findByRole("button", { name: "Edit Office QL-820NWB" }));
    await userEvent.click(screen.getByRole("button", { name: "Save printer" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    expect(lastPut(calls)).not.toHaveProperty("layout_defaults");
  });
});
