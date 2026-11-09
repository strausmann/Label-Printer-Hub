import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderApp } from "../../test-utils";
import { job, mockApi, PRINTER_A } from "../test-api";

afterEach(() => vi.unstubAllGlobals());

const mk = (n: number, state: string, at: string) =>
  job(`eeeeeeee-0000-4000-8000-00000000000${n}`, PRINTER_A.id, state, {
    template_key: null,
    created_at: at,
    payload: { label_data: { title: `Label ${n}` } },
  });

describe("JobsPage", () => {
  it("lists jobs newest first with their printer and state", async () => {
    mockApi({
      "GET /api/v1/printers": [PRINTER_A],
      "GET /api/v1/jobs": [mk(1, "done", "2026-11-04T08:00:00Z"), mk(2, "failed", "2026-11-04T10:00:00Z"), mk(3, "queued", "2026-11-04T09:00:00Z")],
    });
    await renderApp({ path: "/jobs" });
    const list = await screen.findByRole("list", { name: "Jobs" });
    const names = within(list).getAllByRole("link").map((l) => l.textContent);
    expect(names).toEqual(["Label 2", "Label 3", "Label 1"]);
    expect(await within(list).findAllByText(/Workshop PT-P750W/)).toHaveLength(3);
    expect(within(list).getByText("Failed")).toBeVisible();
  });

  it("filters by state through the API", async () => {
    const { calls } = mockApi({ "GET /api/v1/printers": [PRINTER_A], "GET /api/v1/jobs": [] });
    await renderApp({ path: "/jobs" });
    await screen.findByText("No jobs.");
    await userEvent.click(screen.getByRole("radio", { name: "Failed" }));
    await waitFor(() => expect(calls.some((c) => c.path === "/api/v1/jobs" && c.search.includes("state=failed"))).toBe(true));
  });

  it("each row links to the job", async () => {
    mockApi({ "GET /api/v1/printers": [PRINTER_A], "GET /api/v1/jobs": [mk(1, "done", "2026-11-04T08:00:00Z")] });
    await renderApp({ path: "/jobs" });
    const link = await screen.findByRole("link", { name: "Label 1" });
    expect(link).toHaveAttribute("href", "/jobs/eeeeeeee-0000-4000-8000-000000000001");
  });
});
