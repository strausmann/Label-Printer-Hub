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

  it("lists held tape prints with their actions, so a closed notification loses nothing (#277)", async () => {
    const B = "bbbbbbbb-0000-4000-8000-000000000001";
    const W = "bbbbbbbb-0000-4000-8000-000000000002";
    const label = (i: number) => `cccccccc-0000-4000-8000-${String(i).padStart(12, "0")}`;
    const base = { printer_id: PRINTER_A.id, sub_job_size: 50, confirmed_job_ids: [], stop_code: null, unknown_from: null, unknown_to: null, stop_kind: null, reprint_from: null, reprint_to: null };
    const stopped = { ...base, batch_id: B, state: "stopped", current_sub_job: 1, sub_jobs: 1, sub_job_starts: [0], job_ids: Array.from({ length: 25 }, (_, i) => label(i)), stop_code: "tape_empty", unknown_from: 11, unknown_to: 20, stop_kind: "unknown", reprint_from: 11, reprint_to: 21 };
    const waiting = { ...base, batch_id: W, state: "awaiting_confirmation", current_sub_job: 2, sub_jobs: 2, sub_job_starts: [0, 50], job_ids: Array.from({ length: 51 }, (_, i) => label(100 + i)) };
    const { calls } = mockApi({
      "GET /api/v1/printers": [PRINTER_A],
      "GET /api/v1/jobs": [],
      "GET /api/v1/batches/runs/held": [stopped, waiting],
      [`POST /api/v1/batches/${B}/reprint`]: { new_job_ids: [], confirmed_job_ids: [], job_ids: [], skipped_job_ids: [], run: null },
      [`POST /api/v1/batches/${W}/discard`]: null,
    });
    await renderApp({ path: "/jobs" });
    const held = await screen.findByRole("region", { name: "Tape prints that wait for you" });
    expect(within(held).getByText(/Labels 11 to 20 may or may not have printed/)).toBeVisible();
    expect(within(held).getByRole("button", { name: "Continue with part 2" })).toBeVisible();
    await userEvent.selectOptions(within(held).getByRole("combobox", { name: "First missing label" }), "13");
    await userEvent.click(within(held).getByRole("button", { name: "Reprint from label 13" }));
    await waitFor(() => expect(calls.find((c) => c.path === `/api/v1/batches/${B}/reprint`)?.body).toBe(JSON.stringify({ from_label: 13 })));
    await userEvent.click(within(held).getByRole("button", { name: "Discard the rest" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === `/api/v1/batches/${W}/discard`)).toBe(true));
  });

  it("names a held run of one label in the singular", async () => {
    const one = { batch_id: "bbbbbbbb-0000-4000-8000-000000000003", printer_id: PRINTER_A.id, state: "stopped", current_sub_job: 1, sub_jobs: 1, sub_job_size: 50, sub_job_starts: [0], job_ids: ["cccccccc-0000-4000-8000-000000000001"], confirmed_job_ids: [], unknown_from: 1, unknown_to: 1, stop_code: "tape_empty", stop_kind: "unknown", reprint_from: 1, reprint_to: 2 };
    mockApi({ "GET /api/v1/printers": [PRINTER_A], "GET /api/v1/jobs": [], "GET /api/v1/batches/runs/held": [one] });
    await renderApp({ path: "/jobs" });
    expect(await screen.findByText("1 label on Workshop PT-P750W")).toBeVisible();
  });

  it("each row links to the job", async () => {
    mockApi({ "GET /api/v1/printers": [PRINTER_A], "GET /api/v1/jobs": [mk(1, "done", "2026-11-04T08:00:00Z")] });
    await renderApp({ path: "/jobs" });
    const link = await screen.findByRole("link", { name: "Label 1" });
    expect(link).toHaveAttribute("href", "/jobs/eeeeeeee-0000-4000-8000-000000000001");
  });
});
