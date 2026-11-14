import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderApp } from "../../test-utils";
import { ADMIN_PRINTER, apiErrorBody, mockApi, PAGE_PRINTER, respond, type Call } from "../test-api";

afterEach(() => vi.unstubAllGlobals());

const NOT_SET = { ...ADMIN_PRINTER, connection: { host: "192.0.2.10", port: 9100, snmp: { discover: false, community_set: false } } };
const PUT = "PUT /api/v1/admin/printers/workshop-pt";

/** Puts a whole value into a field in one input event (typing key by key re-renders the page per character). */
async function enter(name: string, value: string) {
  const field = screen.getByLabelText(name);
  await userEvent.clear(field);
  await userEvent.click(field);
  await userEvent.paste(value);
}
/** The hint a sighted person reads: the live region (screen readers only) repeats the same words. */
const visibleHint = () => screen.queryAllByText(/stored community is not reused/).filter((el) => !el.closest("[aria-live]"));
const sentConnection = (calls: Call[]) => (JSON.parse(calls.filter((c) => c.method === "PUT").at(-1)!.body!) as { connection: Record<string, unknown> }).connection;

async function openEdit(printer: unknown, routes: Record<string, unknown> = {}) {
  const mocked = mockApi({ "GET /api/v1/admin/printers": [printer], ...routes });
  await renderApp({ path: "/settings/printers" });
  await userEvent.click(await screen.findByRole("button", { name: /^Edit / }));
  return mocked;
}

describe("SNMP fields in the printer form", () => {
  it("the IPP driver shows no SNMP fields", async () => {
    await openEdit(PAGE_PRINTER);
    expect(screen.queryByRole("switch", { name: "Status discovery" })).toBeNull();
    expect(screen.queryByLabelText("SNMP community")).toBeNull();
  });

  it("a tape driver shows the switch and a password field that autofill leaves alone", async () => {
    await openEdit(ADMIN_PRINTER);
    expect(screen.getByRole("switch", { name: "Status discovery" })).not.toBeChecked();
    const field = screen.getByLabelText("SNMP community");
    expect(field).toHaveAttribute("type", "password");
    expect(field).toHaveAttribute("autocomplete", "off");
  });

  it("the field is empty and says a community is stored", async () => {
    await openEdit(ADMIN_PRINTER);
    expect(screen.getByLabelText("SNMP community")).toHaveValue("");
    expect(screen.getByText("A community is stored. Leave the field empty to keep it.")).toBeVisible();
  });

  it("without a stored community the field says what is usual", async () => {
    await openEdit(NOT_SET);
    expect(screen.getByText("Usually public.")).toBeVisible();
  });

  it("saving with an empty field sends snmp without community", async () => {
    const { calls } = await openEdit(ADMIN_PRINTER, { [PUT]: ADMIN_PRINTER });
    await userEvent.click(screen.getByRole("switch", { name: "Status discovery" }));
    await userEvent.click(screen.getByRole("button", { name: "Save printer" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    const connection = sentConnection(calls);
    expect(connection).toEqual({ host: "192.0.2.10", port: 9100, snmp: { discover: true } });
    expect(JSON.stringify(connection)).not.toContain("community");
  });

  it("a typed community is sent", async () => {
    const { calls } = await openEdit(NOT_SET, { [PUT]: NOT_SET });
    await userEvent.click(screen.getByRole("switch", { name: "Status discovery" }));
    await enter("SNMP community", "workshop");
    await userEvent.click(screen.getByRole("button", { name: "Save printer" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    expect(sentConnection(calls).snmp).toEqual({ discover: true, community: "workshop" });
  });

  it("discovery on without any community is refused before anything is sent", async () => {
    const { calls } = await openEdit(NOT_SET, { [PUT]: NOT_SET });
    await userEvent.click(screen.getByRole("switch", { name: "Status discovery" }));
    await userEvent.click(screen.getByRole("button", { name: "Save printer" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Enter the SNMP community, or turn status discovery off.");
    expect(calls.some((c) => c.method === "PUT")).toBe(false);
  });

  it("65 characters are refused before anything is sent", async () => {
    const { calls } = await openEdit(NOT_SET, { [PUT]: NOT_SET });
    await enter("SNMP community", "x".repeat(65));
    await userEvent.click(screen.getByRole("button", { name: "Save printer" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("at most 64 characters");
    expect(calls.some((c) => c.method === "PUT")).toBe(false);
  });

  it("a changed host of a printer with a stored community asks for the community before the submit", async () => {
    const { calls } = await openEdit(ADMIN_PRINTER, { [PUT]: ADMIN_PRINTER });
    expect(visibleHint()).toHaveLength(0);
    await enter("Host", "198.51.100.7");
    expect(visibleHint()).toHaveLength(1);
    expect(screen.getByLabelText("SNMP community")).toBeInvalid();
    await userEvent.click(screen.getByRole("button", { name: "Save printer" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Enter the SNMP community again");
    expect(calls.some((c) => c.method === "PUT")).toBe(false);
    // Typing the community clears the hint and the save goes through with it.
    await enter("SNMP community", "workshop");
    expect(screen.getByLabelText("SNMP community")).toBeValid();
    await userEvent.click(screen.getByRole("button", { name: "Save printer" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    expect(sentConnection(calls)).toEqual({ host: "198.51.100.7", port: 9100, snmp: { discover: false, community: "workshop" } });
  });

  it("a changed port asks for the community too, and changing it back takes the hint away", async () => {
    await openEdit(ADMIN_PRINTER);
    await enter("Port", "9101");
    expect(visibleHint()).toHaveLength(1);
    await enter("Port", "9100");
    expect(visibleHint()).toHaveLength(0);
  });

  it("a new host on a printer with no stored community needs no community", async () => {
    const { calls } = await openEdit(NOT_SET, { [PUT]: NOT_SET });
    await enter("Host", "198.51.100.7");
    expect(visibleHint()).toHaveLength(0);
    await userEvent.click(screen.getByRole("button", { name: "Save printer" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    expect(sentConnection(calls).snmp).toEqual({ discover: false });
  });

  it("a server 422 snmp_community_required shows on the community field", async () => {
    // The hub compares an IP address by value; here it sees a new target where the form saw none.
    const { calls } = await openEdit(ADMIN_PRINTER, { [PUT]: () => respond(422, apiErrorBody("snmp_community_required", "raw text")) });
    await userEvent.click(screen.getByRole("button", { name: "Save printer" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Enter the SNMP community. A stored community is not reused for another host or port.");
    expect(screen.getByLabelText("SNMP community")).toBeInvalid();
    expect(screen.getByRole("alert")).not.toHaveTextContent("snmp_community_required");
    expect(calls.filter((c) => c.method === "PUT")).toHaveLength(1);
  });

  it("a server error of another kind is shown and leaves the field alone", async () => {
    await openEdit(ADMIN_PRINTER, { [PUT]: () => respond(409, apiErrorBody("duplicate_name", "raw text")) });
    await userEvent.click(screen.getByRole("button", { name: "Save printer" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("That name is already used by another printer.");
    expect(screen.getByLabelText("SNMP community")).toBeValid();
  });

  it("a field of blanks counts as not entered", async () => {
    const { calls } = await openEdit(NOT_SET, { [PUT]: NOT_SET });
    await userEvent.click(screen.getByRole("switch", { name: "Status discovery" }));
    await enter("SNMP community", "   ");
    await userEvent.click(screen.getByRole("button", { name: "Save printer" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Enter the SNMP community, or turn status discovery off.");
    expect(calls.some((c) => c.method === "PUT")).toBe(false);
  });

  it("blanks around a typed community are not sent", async () => {
    const { calls } = await openEdit(NOT_SET, { [PUT]: NOT_SET });
    await enter("SNMP community", " bench \n");
    await userEvent.click(screen.getByRole("button", { name: "Save printer" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    expect(sentConnection(calls).snmp).toEqual({ discover: false, community: "bench" });
  });

  it.each([
    ["the host is changed", async () => enter("Host", "198.51.100.7")],
    ["the port is changed", async () => enter("Port", "9101")],
    ["the community is typed", async () => enter("SNMP community", "bench")],
  ])("after a server 422 the stale error clears when %s", async (_name, edit) => {
    await openEdit(ADMIN_PRINTER, { [PUT]: () => respond(422, apiErrorBody("snmp_community_required", "raw text")) });
    await userEvent.click(screen.getByRole("button", { name: "Save printer" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Enter the SNMP community.");
    expect(screen.getByLabelText("SNMP community")).toBeInvalid();
    await edit();
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    // Host and port are now different from what the hub refused; only the typed community leaves the field valid.
    if (_name === "the community is typed") expect(screen.getByLabelText("SNMP community")).toBeValid();
  });

  it("restoring the old host after a hub 422 takes the stale error away", async () => {
    // The form sees a new host and a community; the hub still refuses (it saw another target).
    await openEdit(ADMIN_PRINTER, { [PUT]: () => respond(422, apiErrorBody("snmp_community_required", "raw text")) });
    await enter("Host", "198.51.100.7");
    await enter("SNMP community", "bench");
    await userEvent.click(screen.getByRole("button", { name: "Save printer" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Enter the SNMP community.");
    await enter("Host", "192.0.2.10");
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
  });

  it("restoring the old host after the form's own refusal takes that message away", async () => {
    await openEdit(ADMIN_PRINTER);
    await enter("Host", "198.51.100.7");
    await userEvent.click(screen.getByRole("button", { name: "Save printer" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Enter the SNMP community again");
    await enter("Host", "192.0.2.10");
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    expect(screen.getByLabelText("SNMP community")).toBeValid();
  });

  it("the hint is announced once, in a polite live region that does not change while typing", async () => {
    await openEdit(ADMIN_PRINTER);
    const region = document.querySelector('[aria-live="polite"]') as HTMLElement;
    expect(region).not.toBeNull();
    expect(region).toHaveTextContent("");
    await enter("Host", "198.51.100.7");
    const hint = "The address changed, so the stored community is not reused. Enter it again.";
    expect(region).toHaveTextContent(hint);
    // More typing in the host, and a second field, leave the text as it is: nothing to announce again.
    await enter("Host", "198.51.100.77");
    await enter("Queue timeout (seconds)", "45");
    expect(region.textContent).toBe(hint);
    // Entering the community removes the need; the region empties.
    await enter("SNMP community", "bench");
    expect(region.textContent).toBe("");
  });

  it("a new printer sends the community it was given", async () => {
    const { calls } = mockApi({ "GET /api/v1/admin/printers": [], "POST /api/v1/admin/printers": ADMIN_PRINTER });
    await renderApp({ path: "/settings/printers" });
    await userEvent.click(await screen.findByRole("button", { name: "Add printer" }));
    await enter("Name", "Bench");
    await enter("Slug", "bench-pt");
    await enter("Host", "192.0.2.20");
    await userEvent.click(screen.getByRole("switch", { name: "Status discovery" }));
    await enter("SNMP community", "bench");
    await userEvent.click(screen.getByRole("button", { name: "Create printer" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    const body = JSON.parse(calls.find((c) => c.method === "POST")!.body!) as { connection: unknown };
    expect(body.connection).toEqual({ host: "192.0.2.20", port: 9100, snmp: { discover: true, community: "bench" } });
  });
});
