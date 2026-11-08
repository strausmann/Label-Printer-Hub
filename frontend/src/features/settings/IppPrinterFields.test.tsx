import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderApp } from "../../test-utils";
import { ADMIN_PRINTER, apiErrorBody, mockApi, PAGE_PRINTER, respond } from "../test-api";
import { trayProblem, uriProblem, type TrayDraft } from "./IppPrinterFields";

// Typing an address key by key through the form is slow under coverage instrumentation.
vi.setConfig({ testTimeout: 20_000 });

afterEach(() => vi.unstubAllGlobals());

const URI = "ipp://192.0.2.50:631/ipp/print";
const PROBE = {
  accepting_jobs: true,
  color_modes: ["monochrome", "color"],
  ipp_versions: ["2.0"],
  make_and_model: "Example LaserJet 4000",
  margins_hmm: { bottom: 423, left: 423, right: 423, top: 423 },
  media_col_members: [],
  media_col_supported: true,
  media_sizes: ["iso_a4_210x297mm", "na_letter_8.5x11in"],
  media_sources: ["main-tray", "tray-2"],
  media_types: ["stationery", "labels"],
  monochrome_supported: true,
  one_sided_supported: true,
  pdf_supported: true,
  pdf_versions: ["1.4"],
  resolutions_dpi: [300, 600],
  scaling_none_supported: true,
  state: "idle",
};
const IPP_ADMIN = {
  ...ADMIN_PRINTER,
  id: PAGE_PRINTER.id,
  name: "Office laser",
  slug: "office-laser",
  model: "Example LaserJet 4000",
  backend: "ipp",
  connection: { uri: URI, tls_verify: true },
  cut_defaults: {},
  trays: [
    { key: "main-tray", label: "Main tray", load_hint: "face down", enabled: true, is_default: true },
    { key: "auto", label: "Automatic", load_hint: null, enabled: true, is_default: false },
  ],
};

const lastBody = (calls: { method: string; path: string; body: string | undefined }[], method: string, path: string) => {
  const call = [...calls].reverse().find((c) => c.method === method && c.path === path);
  return call?.body ? (JSON.parse(call.body) as Record<string, unknown>) : undefined;
};

async function openNewPagePrinter() {
  await renderApp({ path: "/settings/printers" });
  await userEvent.click(await screen.findByRole("button", { name: "Add printer" }));
  const form = screen.getByRole("form", { name: "Add a printer" });
  await userEvent.click(within(form).getByRole("button", { name: /Driver/ }));
  await userEvent.click(await screen.findByRole("option", { name: "Page printer (IPP)" }));
  return form;
}

async function fillAndRead(form: HTMLElement) {
  await userEvent.type(within(form).getByRole("textbox", { name: "Name" }), "Office laser");
  await userEvent.type(within(form).getByRole("textbox", { name: "Slug" }), "office-laser");
  await userEvent.type(within(form).getByRole("textbox", { name: "IPP address" }), URI);
  await userEvent.click(within(form).getByRole("button", { name: "Read printer" }));
}

describe("validators", () => {
  it("uriProblem accepts the four schemes and refuses user info and other schemes", () => {
    expect(uriProblem("ipp://host/ipp/print")).toBeNull();
    expect(uriProblem("ipps://host:631/x")).toBeNull();
    expect(uriProblem("http://host/ipp")).toBeNull();
    expect(uriProblem("https://host/ipp")).toBeNull();
    expect(uriProblem("ftp://host/x")).toBe("scheme");
    expect(uriProblem("host/ipp")).toBe("scheme");
    expect(uriProblem("ipp://user:pw@host/x")).toBe("userinfo");
    expect(uriProblem("ipp://user@host/x")).toBe("userinfo");
    expect(uriProblem("ipp:///x")).toBe("invalid");
    expect(uriProblem("ipp://host/" + "a".repeat(1100))).toBe("too_long");
  });

  const tray = (key: string, over: Partial<TrayDraft> = {}): TrayDraft => ({ key, label: key, loadHint: "", enabled: true, isDefault: false, ...over });
  it("trayProblem needs one enabled tray, exactly one default that is enabled, and a label each", () => {
    expect(trayProblem([tray("a", { isDefault: true }), tray("auto")])).toBeNull();
    expect(trayProblem([tray("a", { enabled: false, isDefault: true }), tray("auto", { enabled: false })])).toBe("none_enabled");
    expect(trayProblem([tray("a"), tray("auto")])).toBe("no_default");
    expect(trayProblem([tray("a", { enabled: false, isDefault: true }), tray("auto")])).toBe("default_disabled");
    expect(trayProblem([tray("a", { isDefault: true, label: "  " }), tray("auto")])).toBe("label");
  });
});

describe("IPP page printer form", () => {
  it("keeps Save disabled until a probe succeeded, shows the summary and the tray table", async () => {
    const { calls } = mockApi({ "GET /api/v1/admin/printers": [], "POST /api/v1/admin/printers/ipp/probe": PROBE });
    const form = await openNewPagePrinter();
    // No tape fields, no model field.
    expect(within(form).queryByRole("textbox", { name: "Host" })).toBeNull();
    expect(within(form).queryByRole("textbox", { name: "Model" })).toBeNull();
    expect(within(form).queryByRole("switch", { name: "Half cut by default" })).toBeNull();
    expect(within(form).getByRole("button", { name: "Create printer" })).toBeDisabled();
    await fillAndRead(form);
    const summary = await within(form).findByRole("region", { name: "What the printer reports" });
    expect(lastBody(calls, "POST", "/api/v1/admin/printers/ipp/probe")).toEqual({ uri: URI, tls_verify: true });
    expect(within(summary).getByText("Example LaserJet 4000")).toBeVisible();
    expect(within(summary).getByText("300, 600 dpi")).toBeVisible();
    expect(within(summary).getByText("iso_a4_210x297mm")).toBeVisible();
    expect(within(summary).getByText("labels")).toBeVisible();
    // 423 hundredths of a millimetre are 4.23 mm.
    expect(within(summary).getByText(/4\.23 mm/)).toBeVisible();
    expect(within(summary).getByText("idle")).toBeVisible();
    // One card per reported tray plus the automatic choice, one default.
    expect(within(form).getByRole("group", { name: "main-tray" })).toBeVisible();
    expect(within(form).getByRole("group", { name: "tray-2" })).toBeVisible();
    expect(within(form).getByRole("group", { name: "auto" })).toBeVisible();
    expect(within(form).getByRole("radio", { name: "Default: main-tray" })).toBeChecked();
    expect(within(form).getByRole("button", { name: "Create printer" })).toBeEnabled();
  });

  it("changing the address after a probe asks for a new probe", async () => {
    mockApi({ "GET /api/v1/admin/printers": [], "POST /api/v1/admin/printers/ipp/probe": PROBE });
    const form = await openNewPagePrinter();
    await fillAndRead(form);
    await within(form).findByRole("region", { name: "What the printer reports" });
    await userEvent.type(within(form).getByRole("textbox", { name: "IPP address" }), "x");
    expect(within(form).getByRole("button", { name: "Create printer" })).toBeDisabled();
  });

  it("warns when TLS verification is off", async () => {
    mockApi({ "GET /api/v1/admin/printers": [] });
    const form = await openNewPagePrinter();
    expect(within(form).queryByText(/not checked/i)).toBeNull();
    await userEvent.click(within(form).getByRole("switch", { name: "Verify the printer certificate" }));
    expect(within(form).getByText(/certificate is not checked/i)).toBeVisible();
  });

  it("refuses a bad address before any request and says why", async () => {
    const { calls } = mockApi({ "GET /api/v1/admin/printers": [] });
    const form = await openNewPagePrinter();
    const uri = within(form).getByRole("textbox", { name: "IPP address" });
    await userEvent.type(uri, "ftp://192.0.2.50/x");
    expect(within(form).getByText(/must start with ipp:\/\//i)).toBeVisible();
    expect(within(form).getByRole("button", { name: "Read printer" })).toBeDisabled();
    await userEvent.clear(uri);
    await userEvent.type(uri, "ipp://admin:secret@192.0.2.50/x");
    expect(within(form).getByText(/user name or password/i)).toBeVisible();
    expect(calls.some((c) => c.path.endsWith("/ipp/probe"))).toBe(false);
  });

  it("mirrors the field caps of the server", async () => {
    mockApi({ "GET /api/v1/admin/printers": [], "POST /api/v1/admin/printers/ipp/probe": PROBE });
    const form = await openNewPagePrinter();
    await fillAndRead(form);
    const tray = await within(form).findByRole("group", { name: "main-tray" });
    expect(within(form).getByRole("textbox", { name: "IPP address" })).toHaveAttribute("maxlength", "1023");
    expect(within(tray).getByRole("textbox", { name: "Label" })).toHaveAttribute("maxlength", "60");
    expect(within(tray).getByRole("textbox", { name: "Load hint" })).toHaveAttribute("maxlength", "200");
  });

  it("enforces the tray rules before saving", async () => {
    const { calls } = mockApi({ "GET /api/v1/admin/printers": [], "POST /api/v1/admin/printers/ipp/probe": PROBE });
    const form = await openNewPagePrinter();
    await fillAndRead(form);
    await within(form).findByRole("region", { name: "What the printer reports" });
    for (const key of ["main-tray", "tray-2", "auto"]) {
      await userEvent.click(within(form).getByRole("switch", { name: `Enabled: ${key}` }));
    }
    await userEvent.click(within(form).getByRole("button", { name: "Create printer" }));
    expect(await within(form).findByRole("alert")).toHaveTextContent("Enable at least one tray.");
    await userEvent.click(within(form).getByRole("switch", { name: "Enabled: tray-2" }));
    await userEvent.click(within(form).getByRole("button", { name: "Create printer" }));
    expect(await within(form).findByRole("alert")).toHaveTextContent("The default tray must be one of the enabled trays.");
    expect(calls.some((c) => c.method === "POST" && c.path === "/api/v1/admin/printers")).toBe(false);
  });

  it("creates the printer with the trays and says it is ready after a restart", async () => {
    let printers: unknown[] = [];
    const { calls } = mockApi({
      "GET /api/v1/admin/printers": () => printers,
      "POST /api/v1/admin/printers/ipp/probe": PROBE,
      "POST /api/v1/admin/printers": () => {
        printers = [IPP_ADMIN];
        return IPP_ADMIN;
      },
    });
    const form = await openNewPagePrinter();
    await fillAndRead(form);
    await within(form).findByRole("region", { name: "What the printer reports" });
    await userEvent.click(within(form).getByRole("radio", { name: "Default: tray-2" }));
    await userEvent.click(within(form).getByRole("button", { name: "Create printer" }));
    await waitFor(() => expect(lastBody(calls, "POST", "/api/v1/admin/printers")).toBeDefined());
    const body = lastBody(calls, "POST", "/api/v1/admin/printers")!;
    expect(body).toMatchObject({
      name: "Office laser",
      slug: "office-laser",
      backend: "ipp",
      connection: { uri: URI, tls_verify: true },
      enabled: true,
    });
    expect(body).not.toHaveProperty("model");
    expect(body).not.toHaveProperty("cut_defaults");
    expect(body.trays).toEqual([
      { key: "main-tray", label: "main-tray", load_hint: null, enabled: true, is_default: false },
      { key: "tray-2", label: "tray-2", load_hint: null, enabled: true, is_default: true },
      { key: "auto", label: "auto", load_hint: null, enabled: true, is_default: false },
    ]);
    expect(await screen.findByText("The printer is ready after the hub restarts.")).toBeVisible();
    expect(await screen.findByText("Office laser")).toBeVisible();
  });

  it("a printer that reports no trays offers the automatic choice only", async () => {
    mockApi({ "GET /api/v1/admin/printers": [], "POST /api/v1/admin/printers/ipp/probe": { ...PROBE, media_sources: [] } });
    const form = await openNewPagePrinter();
    await fillAndRead(form);
    await within(form).findByRole("region", { name: "What the printer reports" });
    expect(within(form).getAllByRole("group", { name: /^(?!.*address)/ }).filter((g) => g.tagName === "FIELDSET")).toHaveLength(1);
    expect(within(form).getByRole("radio", { name: "Default: auto" })).toBeChecked();
  });

  it("lists at most 16 trays and says when it left some out", async () => {
    const sources = Array.from({ length: 20 }, (_, i) => `tray-${i + 1}`);
    mockApi({ "GET /api/v1/admin/printers": [], "POST /api/v1/admin/printers/ipp/probe": { ...PROBE, media_sources: sources } });
    const form = await openNewPagePrinter();
    await fillAndRead(form);
    await within(form).findByRole("region", { name: "What the printer reports" });
    expect(within(form).getByRole("group", { name: "auto" })).toBeVisible();
    expect(within(form).getByRole("group", { name: "tray-15" })).toBeVisible();
    expect(within(form).queryByRole("group", { name: "tray-16" })).toBeNull();
    expect(within(form).getByText(/first 15 of 20 trays/i)).toBeVisible();
  });

  it.each([
    ["ipp_unreachable", 502, undefined, /cannot be reached at that address/i],
    ["ipp_rejected", 502, { ipp_status: "server-error-busy" }, /refused the request \(server-error-busy\)/i],
    ["ipp_bad_response", 502, undefined, /did not answer like an IPP printer/i],
    ["invalid_connection", 422, undefined, /address or the certificate setting is not valid/i],
  ])("the probe error %s is shown as words", async (code, status, detail, words) => {
    mockApi({ "GET /api/v1/admin/printers": [], "POST /api/v1/admin/printers/ipp/probe": () => respond(status, apiErrorBody(code, "raw text", detail)) });
    const form = await openNewPagePrinter();
    await fillAndRead(form);
    const alert = await within(form).findByRole("alert");
    expect(alert).toHaveTextContent(words);
    expect(alert).not.toHaveTextContent(code);
    expect(within(form).getByRole("button", { name: "Create printer" })).toBeDisabled();
  });

  it("the probe reports a network error", async () => {
    mockApi({ "GET /api/v1/admin/printers": [] });
    const form = await openNewPagePrinter();
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).includes("/ipp/probe")) throw new TypeError("offline");
      return new Response("[]", { status: 200, headers: { "Content-Type": "application/json" } });
    }));
    await fillAndRead(form);
    expect(await within(form).findByRole("alert")).toHaveTextContent("The server cannot be reached.");
  });

  it("says that a printer without PDF support is not usable", async () => {
    mockApi({ "GET /api/v1/admin/printers": [], "POST /api/v1/admin/printers/ipp/probe": { ...PROBE, pdf_supported: false } });
    const form = await openNewPagePrinter();
    await fillAndRead(form);
    const summary = await within(form).findByRole("region", { name: "What the printer reports" });
    expect(within(summary).getByText("PDF printing")).toBeVisible();
    expect(within(summary).getByText(/No\b/)).toBeVisible();
  });

  it.each([
    ["ipp_pdf_unsupported", 409, /cannot print PDF/i],
    ["ipp_unreachable", 409, /cannot be reached at that address/i],
    ["tray_unknown", 422, /that the printer does not report/i],
    ["ipp_bad_response", 502, /did not answer like an IPP printer/i],
    ["invalid_connection", 422, /address or the certificate setting is not valid/i],
  ])("the save error %s is shown as words", async (code, status, words) => {
    mockApi({
      "GET /api/v1/admin/printers": [],
      "POST /api/v1/admin/printers/ipp/probe": PROBE,
      "POST /api/v1/admin/printers": () => respond(status, apiErrorBody(code, "raw text")),
    });
    const form = await openNewPagePrinter();
    await fillAndRead(form);
    await within(form).findByRole("region", { name: "What the printer reports" });
    await userEvent.click(within(form).getByRole("button", { name: "Create printer" }));
    const alert = await within(form).findByRole("alert");
    expect(alert).toHaveTextContent(words);
    expect(alert).not.toHaveTextContent(code);
    expect(screen.queryByText("The printer is ready after the hub restarts.")).toBeNull();
  });

  it("the save error ipp_rejected names the IPP status", async () => {
    mockApi({
      "GET /api/v1/admin/printers": [],
      "POST /api/v1/admin/printers/ipp/probe": PROBE,
      "POST /api/v1/admin/printers": () => respond(502, apiErrorBody("ipp_rejected", "raw", { ipp_status: "client-error-not-possible" })),
    });
    const form = await openNewPagePrinter();
    await fillAndRead(form);
    await within(form).findByRole("region", { name: "What the printer reports" });
    await userEvent.click(within(form).getByRole("button", { name: "Create printer" }));
    expect(await within(form).findByRole("alert")).toHaveTextContent("client-error-not-possible");
  });

  it("the save reports a network error", async () => {
    mockApi({ "GET /api/v1/admin/printers": [], "POST /api/v1/admin/printers/ipp/probe": PROBE });
    const form = await openNewPagePrinter();
    await fillAndRead(form);
    await within(form).findByRole("region", { name: "What the printer reports" });
    const ok = (globalThis.fetch as unknown as (i: RequestInfo | URL, init?: RequestInit) => Promise<Response>);
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if ((init?.method ?? "GET") === "POST" && new URL(String(input), "http://localhost").pathname === "/api/v1/admin/printers") throw new TypeError("offline");
      return ok(input, init);
    }));
    await userEvent.click(within(form).getByRole("button", { name: "Create printer" }));
    expect(await within(form).findByRole("alert")).toHaveTextContent("The server cannot be reached.");
  });
});

describe("editing an IPP page printer", () => {
  async function openEdit() {
    await renderApp({ path: "/settings/printers" });
    await userEvent.click(await screen.findByRole("button", { name: "Edit Office laser" }));
    return screen.getByRole("form", { name: "Edit Office laser" });
  }

  it("shows the stored address and trays and saves without a new probe when the address is unchanged", async () => {
    const { calls } = mockApi({ "GET /api/v1/admin/printers": [IPP_ADMIN], "PUT /api/v1/admin/printers/office-laser": IPP_ADMIN });
    const form = await openEdit();
    expect(within(form).getByRole("textbox", { name: "IPP address" })).toHaveValue(URI);
    expect(within(form).queryByRole("textbox", { name: "Slug" })).toBeNull();
    expect(within(within(form).getByRole("group", { name: "main-tray" })).getByRole("textbox", { name: "Load hint" })).toHaveValue("face down");
    await userEvent.click(within(form).getByRole("button", { name: "Save printer" }));
    await waitFor(() => expect(lastBody(calls, "PUT", "/api/v1/admin/printers/office-laser")).toBeDefined());
    expect(lastBody(calls, "PUT", "/api/v1/admin/printers/office-laser")).toMatchObject({
      connection: { uri: URI, tls_verify: true },
      enabled: true,
      trays: [
        { key: "main-tray", label: "Main tray", load_hint: "face down", enabled: true, is_default: true },
        { key: "auto", label: "Automatic", load_hint: null, enabled: true, is_default: false },
      ],
    });
    // Nothing that needs a restart changed.
    expect(screen.queryByText("The printer is ready after the hub restarts.")).toBeNull();
  });

  it("a changed address needs a new probe and then says it applies after a restart", async () => {
    const { calls } = mockApi({
      "GET /api/v1/admin/printers": [IPP_ADMIN],
      "POST /api/v1/admin/printers/ipp/probe": PROBE,
      "PUT /api/v1/admin/printers/office-laser": IPP_ADMIN,
    });
    const form = await openEdit();
    await userEvent.type(within(form).getByRole("textbox", { name: "IPP address" }), "2");
    expect(within(form).getByRole("button", { name: "Save printer" })).toBeDisabled();
    await userEvent.click(within(form).getByRole("button", { name: "Read printer" }));
    await within(form).findByRole("region", { name: "What the printer reports" });
    // The stored labels and the load hint survive the new probe.
    expect(within(within(form).getByRole("group", { name: "main-tray" })).getByRole("textbox", { name: "Load hint" })).toHaveValue("face down");
    await userEvent.click(within(form).getByRole("button", { name: "Save printer" }));
    await waitFor(() => expect(lastBody(calls, "PUT", "/api/v1/admin/printers/office-laser")).toBeDefined());
    expect(await screen.findByText("The printer is ready after the hub restarts.")).toBeVisible();
  });

  it("switching the printer off or on says the same", async () => {
    mockApi({
      "GET /api/v1/admin/printers": [IPP_ADMIN],
      "POST /api/v1/admin/printers/office-laser/disable": { ...IPP_ADMIN, enabled: false },
    });
    await renderApp({ path: "/settings/printers" });
    await userEvent.click(await screen.findByRole("button", { name: "Disable Office laser" }));
    expect(await screen.findByText("The printer is ready after the hub restarts.")).toBeVisible();
  });

  it("lists the address of a page printer instead of host and port", async () => {
    mockApi({ "GET /api/v1/admin/printers": [IPP_ADMIN] });
    await renderApp({ path: "/settings/printers" });
    expect(await screen.findByText(URI)).toBeVisible();
  });
});

describe("tape printers stay as they were", () => {
  it("the driver list offers the page printer next to the two tape drivers", async () => {
    mockApi({ "GET /api/v1/admin/printers": [] });
    await renderApp({ path: "/settings/printers" });
    await userEvent.click(await screen.findByRole("button", { name: "Add printer" }));
    await userEvent.click(screen.getByRole("button", { name: /Driver/ }));
    expect(screen.getAllByRole("option").map((o) => o.textContent)).toEqual(["P-touch (PT)", "Brother QL", "Page printer (IPP)"]);
  });
});

describe("worst-case printer data (break-ui)", () => {
  it("40 media sizes show the first eight and the rest on request", async () => {
    const sizes = Array.from({ length: 40 }, (_, i) => `custom_size-${i + 1}_${100 + i}x${200 + i}mm`);
    mockApi({ "GET /api/v1/admin/printers": [], "POST /api/v1/admin/printers/ipp/probe": { ...PROBE, media_sizes: sizes } });
    const form = await openNewPagePrinter();
    await fillAndRead(form);
    const summary = await within(form).findByRole("region", { name: "What the printer reports" });
    expect(within(summary).getByText(sizes[7]!)).toBeVisible();
    expect(within(summary).queryByText(sizes[8]!)).toBeNull();
    await userEvent.click(within(summary).getByRole("button", { name: "Show all 40" }));
    expect(within(summary).getByText(sizes[39]!)).toBeVisible();
    expect(within(summary).queryByRole("button", { name: "Show all 40" })).toBeNull();
  });

  it("a very long make and model, missing margins and an odd state keyword are shown as they come", async () => {
    const make = "Example Industries Professional Colour Laser Multifunction Printer ".repeat(4).trim();
    mockApi({
      "GET /api/v1/admin/printers": [],
      "POST /api/v1/admin/printers/ipp/probe": { ...PROBE, make_and_model: make, margins_hmm: null, state: "processing-stopped-x" },
    });
    const form = await openNewPagePrinter();
    await fillAndRead(form);
    const summary = await within(form).findByRole("region", { name: "What the printer reports" });
    expect(within(summary).getByText(make)).toBeVisible();
    expect(within(summary).getByText("processing-stopped-x")).toBeVisible();
    expect(within(summary).getByText("Not reported")).toBeVisible();
  });
});
