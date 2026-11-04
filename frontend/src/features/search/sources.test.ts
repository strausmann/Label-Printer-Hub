import { QueryClient } from "@tanstack/react-query";
import { initI18n } from "../../i18n";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { job, mockApi, PRINTER_A, PRINTER_B } from "../test-api";
import { jobsSource } from "./jobsSource";
import { printersSource } from "./printersSource";

beforeAll(() => initI18n("en"));
afterEach(() => vi.unstubAllGlobals());
const ctx = () => ({ queryClient: new QueryClient({ defaultOptions: { queries: { retry: false } } }) });

describe("search", () => {
  it("finds a printer by slug and a job by id prefix", async () => {
    const wanted = job("0f3a9c1e-7b2d-4e5f-8a6b-1c2d3e4f5a6b", PRINTER_B.id, "failed", { payload: { label_data: { title: "Cable label" } } });
    const other = job("9b8c7d6e-1111-4222-8333-444455556666", PRINTER_A.id, "queued");
    const { calls } = mockApi({ "GET /api/printers": [PRINTER_A, PRINTER_B], "GET /api/jobs": [wanted, other] });
    const c = ctx();

    const printers = await printersSource.search("office-ql", c);
    expect(printers).toEqual([expect.objectContaining({ title: "Office QL-820NWB", detail: "office-ql", href: `/printers/${PRINTER_B.id}` })]);

    const jobs = await jobsSource.search("0f3a9c", c);
    expect(jobs).toEqual([expect.objectContaining({ href: `/jobs/${wanted.id}`, title: "Cable label 0f3a9c1e", code: "0f3a9c1e" })]);
    expect(calls.find((x) => x.path === "/api/jobs")?.search).toBe("?limit=50");
  });

  it("matches a printer by part of its name, ignoring case", async () => {
    mockApi({ "GET /api/printers": [PRINTER_A, PRINTER_B] });
    const found = await printersSource.search("WORKSHOP", ctx());
    expect(found.map((r) => r.href)).toEqual([`/printers/${PRINTER_A.id}`]);
    expect(await printersSource.search("nothing-like-this", ctx())).toEqual([]);
  });

  it("a job needs at least three hex characters, so a word never lists jobs", async () => {
    const { calls } = mockApi({ "GET /api/jobs": [job("0f3a9c1e-7b2d-4e5f-8a6b-1c2d3e4f5a6b", PRINTER_A.id, "queued")] });
    expect(await jobsSource.search("0f", ctx())).toEqual([]);
    expect(await jobsSource.search("workshop", ctx())).toEqual([]);
    expect(calls).toHaveLength(0);
  });

  it("a job source finds nothing for a prefix no job has", async () => {
    mockApi({ "GET /api/jobs": [job("0f3a9c1e-7b2d-4e5f-8a6b-1c2d3e4f5a6b", PRINTER_A.id, "queued")] });
    expect(await jobsSource.search("abc123", ctx())).toEqual([]);
  });
});
