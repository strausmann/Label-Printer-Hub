import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderApp } from "../../test-utils";
import { job, mockApi, PRINTER_A, respond } from "../test-api";

afterEach(() => vi.unstubAllGlobals());

const ID = "dddddddd-0000-4000-8000-000000000001";
const NEW = "dddddddd-0000-4000-8000-000000000002";
const payload = { content_type: "qr_two_lines", tape_mm: 12, options: { copies: 1 }, label_data: { source_app: "snipeit", title: "Cordless drill", primary_id: "A-0042" } };

function routes(state: string, over: Record<string, unknown> = {}, extra: Record<string, unknown> = {}) {
  return {
    [`GET /api/v1/jobs/${ID}`]: job(ID, PRINTER_A.id, state, { template_key: null, payload, ...over }),
    "GET /api/v1/printers": [PRINTER_A],
    ...extra,
  };
}

describe("JobDetail", () => {
  it("Retry only on failed", async () => {
    for (const [state, retry, cancel] of [
      ["failed", true, false],
      ["failed_restart", true, false],
      ["queued", false, true],
      ["printing", false, false],
      ["done", false, false],
      ["cancelled", false, false],
    ] as const) {
      mockApi(routes(state));
      const { unmount } = await renderApp({ path: `/jobs/${ID}` });
      await screen.findByRole("heading", { level: 1, name: "Cordless drill" });
      expect(screen.queryByRole("button", { name: "Retry" }) !== null, `retry on ${state}`).toBe(retry);
      expect(screen.queryByRole("button", { name: "Cancel" }) !== null, `cancel on ${state}`).toBe(cancel);
      unmount();
    }
  });

  it("shows the error text of a failed job and the payload summary", async () => {
    mockApi(routes("failed", { error: "Printer reported: cover open" }));
    await renderApp({ path: `/jobs/${ID}` });
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Printer reported: cover open");
    const summary = screen.getByRole("region", { name: "What was printed" });
    expect(within(summary).getByText("A-0042")).toBeVisible();
    expect(within(summary).getByText("qr_two_lines")).toBeVisible();
    expect(within(summary).getByText("12 mm")).toBeVisible();
  });

  it("lists the state history from the job's timestamps", async () => {
    mockApi(routes("done", { started_at: "2026-11-04T10:00:05Z", finished_at: "2026-11-04T10:00:09Z" }));
    await renderApp({ path: `/jobs/${ID}` });
    const history = await screen.findByRole("region", { name: "History" });
    const rows = within(history).getAllByRole("listitem").map((li) => li.textContent);
    expect(rows[0]).toMatch(/Queued/);
    expect(rows[1]).toMatch(/Printing/);
    expect(rows[2]).toMatch(/Done/);
  });

  it("Retry posts with the CSRF header and opens the new job", async () => {
    const { calls } = mockApi(
      routes("failed", {}, {
        [`POST /api/v1/jobs/${ID}/retry`]: job(NEW, PRINTER_A.id, "queued", { payload }),
        [`GET /api/v1/jobs/${NEW}`]: job(NEW, PRINTER_A.id, "queued", { payload, template_key: null }),
      }),
    );
    const { router } = await renderApp({ path: `/jobs/${ID}` });
    await userEvent.click(await screen.findByRole("button", { name: "Retry" }));
    await waitFor(() => expect(router.state.location.pathname).toBe(`/jobs/${NEW}`));
    const post = calls.find((c) => c.method === "POST")!;
    expect(post.path).toBe(`/api/v1/jobs/${ID}/retry`);
    expect(post.headers.get("X-CSRF-Token")).toBe("csrf-test");
  });

  it("Cancel posts for a queued job", async () => {
    const { calls } = mockApi(routes("queued", {}, { [`POST /api/v1/jobs/${ID}/cancel`]: job(ID, PRINTER_A.id, "cancelled") }));
    await renderApp({ path: `/jobs/${ID}` });
    await userEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(calls.some((c) => c.path === `/api/v1/jobs/${ID}/cancel`)).toBe(true));
  });

  it("says so when the retry is refused", async () => {
    mockApi(routes("failed", {}, { [`POST /api/v1/jobs/${ID}/retry`]: respond(409, { detail: "busy" }) }));
    await renderApp({ path: `/jobs/${ID}` });
    await userEvent.click(await screen.findByRole("button", { name: "Retry" }));
    expect(await screen.findByText("The job could not be retried.")).toBeVisible();
  });

  it("says that a held printer must be confirmed by an admin first", async () => {
    mockApi(
      routes("failed", {}, {
        [`POST /api/v1/jobs/${ID}/retry`]: respond(409, { type: "printer-identity-mismatch", title: "Held", status: 409, detail: "held" }),
      }),
    );
    await renderApp({ path: `/jobs/${ID}` });
    await userEvent.click(await screen.findByRole("button", { name: "Retry" }));
    expect(
      await screen.findByText("This printer may be a different device now. An admin has to confirm it on the printer's page first."),
    ).toBeVisible();
  });

  it("a job that is not there (or not yours) reads as not found", async () => {
    mockApi({ [`GET /api/v1/jobs/${ID}`]: respond(404, { detail: "job not found" }) });
    await renderApp({ path: `/jobs/${ID}` });
    expect(await screen.findByText("This job does not exist.")).toBeVisible();
  });
});
