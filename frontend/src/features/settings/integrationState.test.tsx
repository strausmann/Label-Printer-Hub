import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderApp } from "../../test-utils";
import { KEY_ADMIN, mockApi, settingsList } from "../test-api";

afterEach(() => vi.unstubAllGlobals());

const TEST_PATH = "POST /api/v1/settings/integrations/grocy/test";
const CONFIGURED = [
  { name: "snipeit" as const, configured: false },
  { name: "grocy" as const, configured: true },
  { name: "spoolman" as const, configured: false },
];

async function openGrocy(testResult: unknown, language: "en" | "de" = "en") {
  mockApi({ "GET /api/v1/settings": settingsList(), "GET /api/admin/api-keys": [KEY_ADMIN], [TEST_PATH]: testResult });
  await renderApp({ path: "/settings/integrations", info: { integrations: CONFIGURED }, language });
  return screen.findByRole("group", { name: "Grocy" });
}

/** The line under the buttons: the card has other status regions, so it is found by its result badge. */
const resultLine = async (card: HTMLElement) =>
  (await within(card).findByText(/^(Works|Failed|Funktioniert|Fehlgeschlagen)$/)).closest<HTMLElement>("[role=status]")!;

const testButton = (card: HTMLElement, de = false) => within(card).getByRole("button", { name: de ? "Verbindung testen" : "Test connection" });

describe("integration card state (#176)", () => {
  it("a configured integration reads 'Configured' and never 'Set up' (en)", async () => {
    const card = await openGrocy({ ok: true, status: 200, detail: "ok" });
    expect(within(card).getByText("Configured")).toBeVisible();
    expect(within(card).queryByText("Set up")).toBeNull();
    expect(within(card).queryByText("Connected")).toBeNull();
  });

  it("a configured integration reads 'Eingerichtet', not the imperative 'Einrichten' (de)", async () => {
    const card = await openGrocy({ ok: true, status: 200, detail: "ok" }, "de");
    expect(within(card).getByText("Eingerichtet")).toBeVisible();
    expect(within(card).queryByText("Einrichten")).toBeNull();
  });

  it("an integration that is not configured keeps 'Not set up'", async () => {
    mockApi({ "GET /api/v1/settings": settingsList(), "GET /api/admin/api-keys": [] });
    await renderApp({ path: "/settings/integrations", info: { integrations: CONFIGURED } });
    const spool = await screen.findByRole("group", { name: "Spoolman" });
    expect(within(spool).getByText("Not set up")).toBeVisible();
  });

  it("'Connected' appears only after a successful test, in both languages", async () => {
    const en = await openGrocy({ ok: true, status: 200, detail: "ok" });
    await userEvent.click(testButton(en));
    expect(await within(en).findAllByText("Connected")).not.toHaveLength(0);
    expect(within(en).queryByText("Configured")).toBeNull();
  });

  it("'Verbunden' appears only after a successful test (de)", async () => {
    const de = await openGrocy({ ok: true, status: 200, detail: "ok" }, "de");
    expect(within(de).queryByText("Verbunden")).toBeNull();
    await userEvent.click(testButton(de, true));
    expect((await within(de).findAllByText("Verbunden")).length).toBeGreaterThan(0);
  });

  it("a failed test turns the header into 'Connection failed' / 'Verbindung fehlgeschlagen'", async () => {
    const en = await openGrocy({ ok: false, status: null, detail: "timeout" });
    await userEvent.click(testButton(en));
    expect(await within(en).findByText("Connection failed")).toBeVisible();
    expect(within(en).queryByText("Configured")).toBeNull();
  });

  it("a failed test turns the header into 'Verbindung fehlgeschlagen' (de)", async () => {
    const de = await openGrocy({ ok: false, status: null, detail: "timeout" }, "de");
    await userEvent.click(testButton(de, true));
    expect(await within(de).findByText("Verbindung fehlgeschlagen")).toBeVisible();
  });

  it("editing a field after a test drops the result: the header falls back to 'Configured'", async () => {
    const card = await openGrocy({ ok: false, status: null, detail: "timeout" });
    await userEvent.click(testButton(card));
    await within(card).findByText("Connection failed");
    await userEvent.type(within(card).getByRole("textbox", { name: "URL" }), "x");
    expect(within(card).queryByText("Connection failed")).toBeNull();
    expect(within(card).getByText("Configured")).toBeVisible();
  });

  it("a result for unsaved values does not claim the saved integration is connected", async () => {
    const card = await openGrocy({ ok: true, status: 200, detail: "ok" });
    await userEvent.type(within(card).getByRole("textbox", { name: "URL" }), "https://grocy.example.invalid");
    await userEvent.click(testButton(card));
    await resultLine(card);
    expect(within(card).queryByText("Connected")).toBeNull();
    expect(within(card).getByText("Configured")).toBeVisible();
  });
});

describe("test result line (#174)", () => {
  it("shows the status once when the detail only repeats it", async () => {
    const card = await openGrocy({ ok: false, status: 404, detail: "HTTP 404" });
    await userEvent.click(testButton(card));
    const line = await resultLine(card);
    expect(line.textContent?.match(/HTTP 404/g)).toHaveLength(1);
  });

  it("shows status and detail when they differ", async () => {
    const card = await openGrocy({ ok: true, status: 200, detail: "ok" });
    await userEvent.click(testButton(card));
    const line = await resultLine(card);
    expect(line).toHaveTextContent("HTTP 200");
    expect(line).toHaveTextContent("ok");
  });

  it("explains a redirect: login page in front of the app, use an address that reaches the API", async () => {
    const card = await openGrocy({ ok: false, status: 302, detail: "HTTP 302" });
    await userEvent.click(testButton(card));
    const line = await resultLine(card);
    expect(line.textContent?.match(/HTTP 302/g)).toHaveLength(1);
    expect(line).toHaveTextContent(/redirect/i);
    expect(line).toHaveTextContent(/login/i);
    expect(line).toHaveTextContent(/directly/i);
  });

  it("explains a redirect in German", async () => {
    const card = await openGrocy({ ok: false, status: 302, detail: "HTTP 302" }, "de");
    await userEvent.click(testButton(card, true));
    const line = await resultLine(card);
    expect(line.textContent?.match(/HTTP 302/g)).toHaveLength(1);
    expect(line).toHaveTextContent(/weitergeleitet/i);
  });

  it("does not add the redirect hint to other errors", async () => {
    const card = await openGrocy({ ok: false, status: 500, detail: "HTTP 500" });
    await userEvent.click(testButton(card));
    const line = await resultLine(card);
    expect(line).not.toHaveTextContent(/redirect/i);
  });
});
