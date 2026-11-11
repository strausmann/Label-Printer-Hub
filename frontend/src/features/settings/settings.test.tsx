import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderApp, SIGNED_IN } from "../../test-utils";
import { ADMIN_PRINTER, KEY_ADMIN, KEY_KEPT, mockApi, PRINTER_A, respond, settingsList } from "../test-api";

afterEach(() => vi.unstubAllGlobals());

const lastBody = (calls: { method: string; path: string; body: string | undefined }[], method: string, path: string) => {
  const call = [...calls].reverse().find((c) => c.method === method && c.path === path);
  return call?.body ? (JSON.parse(call.body) as Record<string, unknown>) : undefined;
};

describe("Settings", () => {
  it("tells a non-admin they need an admin key", async () => {
    mockApi({});
    await renderApp({ path: "/settings", session: { ...SIGNED_IN, scope: "print" } });
    expect(await screen.findByRole("heading", { level: 1, name: "You need an admin key" })).toBeVisible();
    expect(screen.queryByRole("navigation", { name: "Settings sections" })).toBeNull();
  });

  it("offers the six sections and hides sheets and notifications", async () => {
    mockApi({ "GET /api/v1/settings": settingsList() });
    await renderApp({ path: "/settings" });
    const nav = await screen.findByRole("navigation", { name: "Settings sections" });
    expect(within(nav).getAllByRole("link").map((a) => a.textContent)).toEqual([
      "General",
      "Printers",
      "Integrations",
      "Access and keys",
      "Jobs",
      "System",
    ]);
    expect(within(nav).getByRole("link", { name: "Integrations" })).toHaveAttribute("href", "/settings/integrations");
  });

  it("General saves only what changed and refreshes the sidebar info", async () => {
    const { calls } = mockApi({
      "GET /api/v1/settings": settingsList(),
      "PUT /api/v1/settings": settingsList({ "general.display_name": { value: "Workshop Hub" } }),
    });
    const { queryClient } = await renderApp({ path: "/settings" });
    const name = await screen.findByRole("textbox", { name: "Display name" });
    await userEvent.clear(name);
    await userEvent.type(name, "Workshop Hub");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(lastBody(calls, "PUT", "/api/v1/settings")).toEqual({ values: { "general.display_name": "Workshop Hub" } }));
    expect(await screen.findByText("Saved")).toBeVisible();
    expect(queryClient.getQueryState(["info"])?.isInvalidated).toBe(true);
    // The public URL is set by the container: read-only.
    expect(screen.getByRole("textbox", { name: "Public URL" })).toHaveAttribute("readonly");
  });

  it("Jobs offers retention only, no part size or half cut (D11)", async () => {
    mockApi({ "GET /api/v1/settings": settingsList() });
    await renderApp({ path: "/settings/jobs" });
    expect(await screen.findByRole("textbox", { name: "Keep finished jobs for (days)" })).toHaveValue("30");
    expect(screen.queryByText(/part size/i)).toBeNull();
    expect(screen.queryByText(/half cut/i)).toBeNull();
  });
});

describe("Integrations", () => {
  it("test connection sends unsaved values", async () => {
    const { calls } = mockApi({
      "GET /api/v1/settings": settingsList(),
      "GET /api/v1/admin/api-keys": [KEY_ADMIN],
      "POST /api/v1/settings/integrations/grocy/test": { ok: true, status: 200, detail: "Grocy 4.2 answered" },
    });
    await renderApp({ path: "/settings/integrations" });
    const grocy = await screen.findByRole("group", { name: "Grocy" });
    await userEvent.type(within(grocy).getByRole("textbox", { name: "URL" }), "https://grocy.example.invalid");
    await userEvent.type(within(grocy).getByLabelText("API key"), "fake-key-for-tests");
    await userEvent.click(within(grocy).getByRole("button", { name: "Test connection" }));
    expect(await within(grocy).findByText("Works")).toBeVisible();
    expect(within(grocy).queryByText(/HTTP 200|Grocy 4.2 answered/)).toBeNull();
    expect(lastBody(calls, "POST", "/api/v1/settings/integrations/grocy/test")).toEqual({
      values: { "integrations.grocy.url": "https://grocy.example.invalid", "integrations.grocy.api_key": "fake-key-for-tests" },
    });
    // Nothing was saved by testing.
    expect(calls.some((c) => c.method === "PUT")).toBe(false);
  });

  it("shows a failed test as a problem", async () => {
    mockApi({
      "GET /api/v1/settings": settingsList(),
      "GET /api/v1/admin/api-keys": [],
      "POST /api/v1/settings/integrations/spoolman/test": { ok: false, status: null, detail: "connection refused" },
    });
    await renderApp({ path: "/settings/integrations" });
    const spoolman = await screen.findByRole("group", { name: "Spoolman" });
    await userEvent.click(within(spoolman).getByRole("button", { name: "Test connection" }));
    expect(await within(spoolman).findByText(/connection refused/)).toBeVisible();
    expect(within(spoolman).getByText("Failed")).toBeVisible();
  });

  it("a changed URL makes the saved secret required in the same save", async () => {
    const { calls } = mockApi({
      "GET /api/v1/settings": settingsList(),
      "GET /api/v1/admin/api-keys": [],
      "PUT /api/v1/settings": settingsList(),
    });
    await renderApp({ path: "/settings/integrations" });
    const snipe = await screen.findByRole("group", { name: "Snipe-IT" });
    const save = within(snipe).getByRole("button", { name: "Save" });
    const url = within(snipe).getByRole("textbox", { name: "URL" });
    await userEvent.clear(url);
    await userEvent.type(url, "https://other.example.invalid");
    expect(within(snipe).getByLabelText(/API key/)).toBeRequired();
    expect(save).toBeDisabled();
    await userEvent.type(within(snipe).getByLabelText(/API key/), "fake-key-for-tests");
    expect(save).toBeEnabled();
    await userEvent.click(save);
    await waitFor(() =>
      expect(lastBody(calls, "PUT", "/api/v1/settings")).toEqual({
        values: { "integrations.snipeit.url": "https://other.example.invalid", "integrations.snipeit.api_key": "fake-key-for-tests" },
      }),
    );
  });

  it("explains a secret_required_for_new_url answer", async () => {
    mockApi({
      "GET /api/v1/settings": settingsList(),
      "GET /api/v1/admin/api-keys": [],
      "PUT /api/v1/settings": () => respond(422, { detail: { error_code: "secret_required_for_new_url", error_message: "x", keys: [] } }),
    });
    await renderApp({ path: "/settings/integrations" });
    const grocy = await screen.findByRole("group", { name: "Grocy" });
    await userEvent.type(within(grocy).getByRole("textbox", { name: "URL" }), "https://grocy.example.invalid");
    await userEvent.click(within(grocy).getByRole("button", { name: "Save" }));
    expect(await within(grocy).findByRole("alert")).toHaveTextContent(/enter the secret again/i);
  });

  it("lists the clients by their API keys, with scope and last use", async () => {
    mockApi({ "GET /api/v1/settings": settingsList(), "GET /api/v1/admin/api-keys": [KEY_ADMIN, KEY_KEPT] });
    await renderApp({ path: "/settings/integrations" });
    const clients = await screen.findByRole("region", { name: "Clients" });
    expect(await within(clients).findByText("Kept")).toBeVisible();
    expect(within(clients).getByText("print")).toBeVisible();
    expect(within(clients).getByText("Never used")).toBeVisible();
    expect(within(clients).queryByText("First admin key")).toBeNull();
  });
});

describe("Printers", () => {
  it("create then disable a printer", async () => {
    let printers = [ADMIN_PRINTER];
    const { calls } = mockApi({
      "GET /api/v1/admin/printers": () => printers,
      "POST /api/v1/admin/printers": (init: RequestInit) => {
        const body = JSON.parse(String(init.body)) as Record<string, unknown>;
        const created = { ...ADMIN_PRINTER, ...body, id: "33333333-3333-4333-8333-333333333333" };
        printers = [...printers, created as typeof ADMIN_PRINTER];
        return created;
      },
      "POST /api/v1/admin/printers/office-ql/disable": () => {
        printers = printers.map((p) => (p.slug === "office-ql" ? { ...p, enabled: false } : p));
        return printers[1];
      },
    });
    await renderApp({ path: "/settings/printers" });
    expect(await screen.findByText(PRINTER_A.name)).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Add printer" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Name" }), "Office QL-820NWB");
    await userEvent.type(screen.getByRole("textbox", { name: "Slug" }), "office-ql");
    await userEvent.type(screen.getByRole("textbox", { name: "Host" }), "192.0.2.11");
    await userEvent.click(screen.getByRole("button", { name: "Create printer" }));
    await waitFor(() => expect(lastBody(calls, "POST", "/api/v1/admin/printers")).toMatchObject({
      name: "Office QL-820NWB",
      slug: "office-ql",
      backend: "ptouch",
      connection: { host: "192.0.2.11", port: 9100 },
      cut_defaults: { half_cut: false },
      enabled: true,
    }));
    const row = (await screen.findByText("Office QL-820NWB")).closest("li") as HTMLElement;
    await userEvent.click(within(row).getByRole("button", { name: "Disable Office QL-820NWB" }));
    expect(await within(row).findByText("Disabled")).toBeVisible();
    expect(within(row).getByRole("button", { name: "Enable Office QL-820NWB" })).toBeVisible();
  });

  it("editing keeps slug and model fixed and sends the half cut default", async () => {
    const { calls } = mockApi({
      "GET /api/v1/admin/printers": [ADMIN_PRINTER],
      "PUT /api/v1/admin/printers/workshop-pt": ADMIN_PRINTER,
    });
    await renderApp({ path: "/settings/printers" });
    await userEvent.click(await screen.findByRole("button", { name: "Edit Workshop PT-P750W" }));
    expect(screen.queryByRole("textbox", { name: "Slug" })).toBeNull();
    await userEvent.click(screen.getByRole("switch", { name: "Half cut by default" }));
    await userEvent.click(screen.getByRole("button", { name: "Save printer" }));
    await waitFor(() =>
      expect(lastBody(calls, "PUT", "/api/v1/admin/printers/workshop-pt")).toMatchObject({
        cut_defaults: { half_cut: true },
        connection: { host: "192.0.2.10", port: 9100, snmp: { discover: false } },
      }),
    );
  });

  it("explains a duplicate slug", async () => {
    mockApi({
      "GET /api/v1/admin/printers": [],
      "POST /api/v1/admin/printers": () => respond(409, { detail: { error_code: "duplicate_slug", error_message: "taken" } }),
    });
    await renderApp({ path: "/settings/printers" });
    await userEvent.click(await screen.findByRole("button", { name: "Add printer" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Name" }), "Office");
    await userEvent.type(screen.getByRole("textbox", { name: "Slug" }), "office-ql");
    await userEvent.type(screen.getByRole("textbox", { name: "Host" }), "192.0.2.11");
    await userEvent.click(screen.getByRole("button", { name: "Create printer" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/slug is already used/i);
  });
});

describe("AccessKeys", () => {
  it("new key shown once and gone after closing", async () => {
    let keys = [KEY_ADMIN];
    const { calls } = mockApi({
      "GET /api/v1/settings": settingsList(),
      "GET /api/v1/admin/api-keys": () => keys,
      "POST /api/v1/admin/api-keys": () => {
        keys = [...keys, KEY_KEPT];
        return { key_id: KEY_KEPT.id, name: "Kept", plaintext: "lph_fake-plaintext-for-tests", prefix: "lph_kept", scopes: ["print"] };
      },
    });
    await renderApp({ path: "/settings/access" });
    await userEvent.type(await screen.findByRole("textbox", { name: "Key name" }), "Kept");
    await userEvent.click(screen.getByRole("checkbox", { name: "print" }));
    await userEvent.click(screen.getByRole("checkbox", { name: "read" }));
    await userEvent.click(screen.getByRole("button", { name: "Create key" }));
    const dialog = await screen.findByRole("dialog", { name: "Your new key" });
    expect(within(dialog).getByLabelText("Key")).toHaveValue("lph_fake-plaintext-for-tests");
    expect(lastBody(calls, "POST", "/api/v1/admin/api-keys")).toMatchObject({ name: "Kept", scopes: ["print"] });
    await userEvent.click(within(dialog).getByRole("button", { name: "Done" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(document.body.innerHTML).not.toContain("lph_fake-plaintext-for-tests");
    // The list shows the prefix only.
    expect(await screen.findByText("lph_kept…")).toBeVisible();
  });

  it("revokes a key after a confirmation", async () => {
    const { calls } = mockApi({
      "GET /api/v1/settings": settingsList(),
      "GET /api/v1/admin/api-keys": [KEY_ADMIN, KEY_KEPT],
      [`DELETE /api/v1/admin/api-keys/${KEY_KEPT.id}`]: null,
    });
    await renderApp({ path: "/settings/access" });
    await userEvent.click(await screen.findByRole("button", { name: "Revoke Kept" }));
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Revoke key" }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE")).toBe(true));
  });

  it("shows the SSO state read-only and the webhook key as a secret", async () => {
    mockApi({ "GET /api/v1/settings": settingsList({ "access.webhook_api_key": { is_set: true } }), "GET /api/v1/admin/api-keys": [KEY_ADMIN] });
    await renderApp({ path: "/settings/access", info: { auth: { sso_configured: true, bootstrap_open: false } } });
    expect(await screen.findByText(/Sign-in through a reverse proxy is configured/)).toBeVisible();
    expect(screen.getByLabelText("Webhook key")).toHaveValue("");
  });

  it("warns that a short webhook key is rejected before sending", async () => {
    const { calls } = mockApi({ "GET /api/v1/settings": settingsList(), "GET /api/v1/admin/api-keys": [] });
    await renderApp({ path: "/settings/access" });
    await userEvent.type(await screen.findByLabelText("Webhook key"), "short");
    expect(screen.getByText(/at least 32 characters/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Save webhook key" })).toBeDisabled();
    expect(calls.some((c) => c.method === "PUT")).toBe(false);
  });
});

describe("System", () => {
  it("shows version, health, readiness, the export link, the logs and the API docs", async () => {
    mockApi({
      "GET /api/v1/settings": settingsList(),
      "GET /healthz": { status: "ok", version: "1.2.3", revision: "abc", build_date: "2026-11-01", repository: "r", sse_active_subscribers: 2 },
      "GET /readiness": { status: "degraded", checks: { database: { status: "ok" }, snmp: { status: "stale", detail: "no probe yet" } }, version: "1.2.3", revision: "abc" },
      "GET /api/v1/system/logs": [
        { ts: "2026-11-04T10:00:00Z", level: "WARNING", logger: "app.queue", message: "retry scheduled" },
        { ts: "2026-11-04T10:05:00Z", level: "ERROR", logger: "app.probe", message: "probe failed" },
      ],
    });
    await renderApp({ path: "/settings/system" });
    expect(await screen.findByText("0.0.0-test")).toBeVisible();
    expect(await screen.findByText("Healthy")).toBeVisible();
    expect(await screen.findByText("Degraded")).toBeVisible();
    expect(screen.getByRole("link", { name: "Download settings" })).toHaveAttribute("href", "/api/v1/settings/export");
    expect(screen.getByRole("link", { name: "API documentation" })).toHaveAttribute("href", "/docs");
    const rows = within(await screen.findByRole("table", { name: "Recent warnings and errors" })).getAllByRole("row");
    // Newest first, after the header row.
    expect(rows[1]).toHaveTextContent("probe failed");
    expect(rows[2]).toHaveTextContent("retry scheduled");
  });

  it("says so when there is nothing to report", async () => {
    mockApi({
      "GET /api/v1/settings": settingsList(),
      "GET /healthz": { status: "ok", version: "1", revision: "r", build_date: "d", repository: "r", sse_active_subscribers: 0 },
      "GET /readiness": { status: "ready", checks: {}, version: "1", revision: "r" },
      "GET /api/v1/system/logs": [],
    });
    await renderApp({ path: "/settings/system" });
    expect(await screen.findByText("No warnings or errors recorded.")).toBeVisible();
  });
});

describe("fix round 1", () => {
  const created = { key_id: KEY_KEPT.id, name: "Kept", plaintext: "lph_fake-plaintext-for-tests", prefix: "lph_kept", scopes: ["print"] };
  const createKey = async (view: Awaited<ReturnType<typeof renderApp>>) => {
    await userEvent.type(await screen.findByRole("textbox", { name: "Key name" }), "Kept");
    await userEvent.click(screen.getByRole("button", { name: "Create key" }));
    return view;
  };

  it("the new-key dialog survives Escape and only closes with Done", async () => {
    mockApi({ "GET /api/v1/settings": settingsList(), "GET /api/v1/admin/api-keys": [KEY_ADMIN], "POST /api/v1/admin/api-keys": created });
    await renderApp({ path: "/settings/access" });
    await createKey({} as never);
    const dialog = await screen.findByRole("dialog", { name: "Your new key" });
    await userEvent.keyboard("{Escape}");
    expect(screen.getByRole("dialog", { name: "Your new key" })).toBeVisible();
    await userEvent.click(within(dialog).getByRole("button", { name: "Done" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("a generated webhook key disappears from the page once saved", async () => {
    mockApi({
      "GET /api/v1/settings": settingsList(),
      "GET /api/v1/admin/api-keys": [],
      "PUT /api/v1/settings": settingsList({ "access.webhook_api_key": { is_set: true } }),
    });
    await renderApp({ path: "/settings/access" });
    await userEvent.click(await screen.findByRole("button", { name: "Generate a key" }));
    expect(screen.getByText(/Copy it now/)).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Save webhook key" }));
    expect(await screen.findByText("Saved")).toBeVisible();
    expect(screen.queryByText(/Copy it now/)).toBeNull();
    expect(screen.queryByText(/^[0-9a-f]{48}$/)).toBeNull();
  });

  it("the integration card takes its state from /api/v1/info, like the sidebar", async () => {
    mockApi({ "GET /api/v1/settings": settingsList(), "GET /api/v1/admin/api-keys": [] });
    await renderApp({
      path: "/settings/integrations",
      info: { integrations: [{ name: "snipeit", configured: false }, { name: "grocy", configured: true }, { name: "spoolman", configured: true }] },
    });
    const snipe = await screen.findByRole("group", { name: "Snipe-IT" });
    // Settings say url + key are saved, but the plugin does not accept them.
    expect(within(snipe).getByText("Not set up")).toBeVisible();
    expect(within(snipe).getByText(/cannot be used/i)).toBeVisible();
    // Grocy has nothing saved in settings, yet the plugin is configured (environment).
    const grocy = screen.getByRole("group", { name: "Grocy" });
    expect(within(grocy).getByText("Configured")).toBeVisible();
    expect(within(grocy).queryByText(/cannot be used/i)).toBeNull();
  });

  it("an undecryptable secret makes the card say so as well", async () => {
    mockApi({
      "GET /api/v1/settings": settingsList({ "integrations.snipeit.api_key": { is_set: true, state: "undecryptable" } }),
      "GET /api/v1/admin/api-keys": [],
    });
    await renderApp({ path: "/settings/integrations", info: { integrations: [{ name: "snipeit", configured: false }] } });
    const snipe = await screen.findByRole("group", { name: "Snipe-IT" });
    expect(within(snipe).getByText("Not set up")).toBeVisible();
    expect(within(snipe).getByText(/cannot be used/i)).toBeVisible();
  });
});
