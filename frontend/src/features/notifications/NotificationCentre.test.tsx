// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderApp } from "../../test-utils";
import { job, mockApi, PRINTER_A, PRINTER_B, status } from "../test-api";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const J1 = "aaaaaaaa-0000-4000-8000-000000000001";
const J2 = "aaaaaaaa-0000-4000-8000-000000000002";
const J3 = "aaaaaaaa-0000-4000-8000-000000000003";
const minutesAgo = (m: number) => new Date(Date.now() - m * 60_000).toISOString();

const routes = (jobs: unknown[] = [], printers: unknown[] = [PRINTER_A]) => ({
  "GET /api/v1/printers": printers,
  [`GET /api/v1/printers/${PRINTER_A.id}/status`]: status(PRINTER_A.id),
  [`GET /api/v1/printers/${PRINTER_B.id}/status`]: status(PRINTER_B.id),
  "GET /api/v1/jobs": jobs,
});

const notices = (...records: Record<string, unknown>[]) => ({ "GET /api/v1/notices": records });
const noticeRecord = (key: string, code: string, kind: string, ageMinutes = 5) => ({
  id: `sheet-type-verified:${key}:2`,
  kind,
  key,
  code,
  at: minutesAgo(ageMinutes),
});

const SHEETS_ON = { features: { sheets: true } };

const bell = () => screen.findByRole("button", { name: /^Notifications/ });

describe("NotificationCentre: the bell", () => {
  it("the bell names count and severity", async () => {
    mockApi(
      routes([
        job(J1, PRINTER_A.id, "failed", { error: "Cover open", updated_at: minutesAgo(3) }),
        job(J2, PRINTER_A.id, "done", { updated_at: minutesAgo(2) }),
        job(J3, PRINTER_A.id, "printing", { updated_at: minutesAgo(1) }),
      ]),
    );
    await renderApp({ path: "/printers" });
    expect(await screen.findByRole("button", { name: "Notifications, 3 unread, the most severe is an error" })).toBeVisible();
  });

  it("says in German what it says in English", async () => {
    mockApi(routes([job(J1, PRINTER_A.id, "failed", { updated_at: minutesAgo(3) })]));
    await renderApp({ path: "/printers", language: "de" });
    expect(await screen.findByRole("button", { name: "Benachrichtigungen, 1 ungelesen, die schwerste ist ein Fehler" })).toBeVisible();
  });

  it("the warning uses the diamond shape", async () => {
    // PRINTER_B is paused: a warning.
    mockApi(routes([], [PRINTER_B]));
    await renderApp({ path: "/printers" });
    const button = await screen.findByRole("button", { name: "Notifications, 1 unread, the most severe is a warning" });
    expect(button.querySelector('[data-shape="diamond"]')).not.toBeNull();
  });

  it("an error is a dot, not a diamond", async () => {
    mockApi(routes([job(J1, PRINTER_A.id, "failed", { updated_at: minutesAgo(3) })]));
    await renderApp({ path: "/printers" });
    const button = await screen.findByRole("button", { name: /most severe is an error/ });
    expect(button.querySelector('[data-shape="dot"]')).not.toBeNull();
    expect(button.querySelector('[data-shape="diamond"]')).toBeNull();
  });

  it("shows no dot and no count when there is nothing unread", async () => {
    mockApi(routes());
    await renderApp({ path: "/printers" });
    const button = await bell();
    await waitFor(() => expect(button).toHaveAccessibleName("Notifications, nothing unread"));
    expect(button.querySelector("svg[data-shape]")).toBeNull();
  });

  it("counts 99+ above 99", async () => {
    const many = Array.from({ length: 120 }, (_, i) => job(`bbbbbbbb-0000-4000-8000-${String(i).padStart(12, "0")}`, PRINTER_A.id, "done", { updated_at: minutesAgo(1) }));
    mockApi(routes(many));
    await renderApp({ path: "/printers" });
    const button = await screen.findByRole("button", { name: /^Notifications, 100 unread/ });
    expect(within(button).getByText("99+")).toBeInTheDocument();
  });
});

describe("NotificationCentre: the panel", () => {
  it("opens with focus on Mark all as read", async () => {
    mockApi(routes([job(J1, PRINTER_A.id, "failed", { updated_at: minutesAgo(3) })]));
    await renderApp({ path: "/printers" });
    await userEvent.click(await bell());
    expect(await screen.findByRole("button", { name: "Mark all as read" })).toHaveFocus();
  });

  it("Escape closes and returns focus to the bell", async () => {
    mockApi(routes([job(J1, PRINTER_A.id, "failed", { updated_at: minutesAgo(3) })]));
    await renderApp({ path: "/printers" });
    const trigger = await bell();
    await userEvent.click(trigger);
    await screen.findByRole("dialog");
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it("Tab stays inside the panel", async () => {
    mockApi(routes([job(J1, PRINTER_A.id, "failed", { updated_at: minutesAgo(3) })]));
    await renderApp({ path: "/printers" });
    await userEvent.click(await bell());
    const dialog = await screen.findByRole("dialog");
    const link = await within(dialog).findByRole("link");
    const markAll = within(dialog).getByRole("button", { name: "Mark all as read" });
    await waitFor(() => expect(markAll).toHaveFocus());
    await userEvent.tab();
    expect(within(dialog).getByRole("button", { name: "Clear all" })).toHaveFocus();
    await userEvent.tab();
    expect(link).toHaveFocus();
    // From the last control it wraps to the first, and back.
    await userEvent.tab();
    expect(markAll).toHaveFocus();
    await userEvent.tab({ shift: true });
    expect(link).toHaveFocus();
  });

  it("an entry navigates to the job page and closes the panel", async () => {
    mockApi({ ...routes([job(J1, PRINTER_A.id, "failed", { error: "Cover open", template_key: "cable", updated_at: minutesAgo(3) })]), [`GET /api/v1/jobs/${J1}`]: job(J1, PRINTER_A.id, "failed", { error: "Cover open" }) });
    const { router } = await renderApp({ path: "/printers" });
    await userEvent.click(await bell());
    await userEvent.click(await screen.findByRole("link", { name: /cable failed: Cover open/ }));
    await waitFor(() => expect(router.state.location.pathname).toBe(`/jobs/${J1}`));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("the panel says the cover sentence, never \"doorOpen\"", async () => {
    mockApi({ ...routes(), [`GET /api/v1/printers/${PRINTER_A.id}/status`]: status(PRINTER_A.id, { error_flags: ["doorOpen"], error_state: "doorOpen" }) });
    await renderApp({ path: "/jobs" });
    await userEvent.click(await bell());
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByRole("link", { name: /Workshop PT-P750W: Cover open — close it to print/ })).toBeVisible();
    expect(dialog.textContent).not.toContain("doorOpen");
  });

  it("an entry of a printer opens the printer page", async () => {
    mockApi(routes([], [{ ...PRINTER_A, paused: true }]));
    const { router } = await renderApp({ path: "/jobs" });
    await userEvent.click(await bell());
    await userEvent.click(await screen.findByRole("link", { name: /Workshop PT-P750W: Paused/ }));
    await waitFor(() => expect(router.state.location.pathname).toBe(`/printers/${PRINTER_A.id}`));
  });

  it("a sheet-type entry links to the archive filtered by its type", async () => {
    mockApi({ ...routes(), ...notices(noticeRecord("avery-zweckform-6121", "6121", "sheet_type_verified")) });
    const { router } = await renderApp({ path: "/printers", info: SHEETS_ON });
    await userEvent.click(await bell());
    const link = await screen.findByRole("link", { name: /6121 marked as verified/ });
    expect(link).toHaveAttribute("href", "/sheets/archive?type=avery-zweckform-6121");
    await userEvent.click(link);
    await waitFor(() => expect(router.state.location.pathname).toBe("/sheets/archive"));
    expect(router.state.location.search).toMatchObject({ type: "avery-zweckform-6121" });
  });

  it("the updated notice reads \"6121 dimensions updated (verified)\"", async () => {
    mockApi({
      ...routes(),
      ...notices(
        noticeRecord("avery-zweckform-6121", "6121", "sheet_type_updated", 5),
        noticeRecord("avery-zweckform-l4731rev", "L4731REV", "sheet_type_updated", 6),
      ),
    });
    await renderApp({ path: "/printers", info: SHEETS_ON });
    await userEvent.click(await bell());
    expect(await screen.findByRole("link", { name: /6121 dimensions updated \(verified\)/ })).toBeVisible();
    expect(screen.getByRole("link", { name: /L4731REV dimensions updated \(verified\)/ })).toBeVisible();
  });

  it("says the notices in German", async () => {
    mockApi({
      ...routes(),
      ...notices(
        noticeRecord("avery-zweckform-6121", "6121", "sheet_type_updated", 5),
        noticeRecord("avery-zweckform-3490", "3490", "sheet_type_verified", 6),
      ),
    });
    await renderApp({ path: "/printers", language: "de", info: SHEETS_ON });
    await userEvent.click(await screen.findByRole("button", { name: /^Benachrichtigungen/ }));
    expect(await screen.findByRole("link", { name: /Maße von 6121 aktualisiert \(geprüft\)/ })).toBeVisible();
    expect(screen.getByRole("link", { name: /3490 als geprüft markiert/ })).toBeVisible();
  });

  it("a read notice stays read after a reload", async () => {
    mockApi({ ...routes(), ...notices(noticeRecord("avery-zweckform-6121", "6121", "sheet_type_verified")) });
    const first = await renderApp({ path: "/printers", info: SHEETS_ON });
    await userEvent.click(await bell());
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText("New")).toBeVisible();
    await userEvent.click(within(dialog).getByRole("button", { name: "Mark all as read" }));
    first.unmount();
    mockApi({ ...routes(), ...notices(noticeRecord("avery-zweckform-6121", "6121", "sheet_type_verified")) });
    await renderApp({ path: "/printers", info: SHEETS_ON });
    expect(await screen.findByRole("button", { name: "Notifications, nothing unread" })).toBeVisible();
  });

  it("a failed notices read is no feed error", async () => {
    mockApi({ ...routes([job(J1, PRINTER_A.id, "done", { updated_at: minutesAgo(3) })]) });
    await renderApp({ path: "/printers" });
    await userEvent.click(await bell());
    expect(await screen.findByRole("link", { name: /printed/ })).toBeVisible();
    expect(screen.queryByText(/Could not load/i)).toBeNull();
  });

  it("marks entries as new until Mark all as read, which keeps them and clears the dot", async () => {
    mockApi(routes([job(J1, PRINTER_A.id, "failed", { updated_at: minutesAgo(3) })]));
    await renderApp({ path: "/printers" });
    const trigger = await bell();
    await userEvent.click(trigger);
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText("New")).toBeVisible();
    await userEvent.click(within(dialog).getByRole("button", { name: "Mark all as read" }));
    expect(within(dialog).queryByText("New")).toBeNull();
    expect(within(dialog).getAllByRole("link")).toHaveLength(1);
    expect(trigger).toHaveAccessibleName("Notifications, nothing unread");
  });

  it("Clear all hides the entries, and a newer one shows again", async () => {
    mockApi(routes([job(J1, PRINTER_A.id, "failed", { updated_at: minutesAgo(3) })]));
    await renderApp({ path: "/printers" });
    await userEvent.click(await bell());
    const dialog = await screen.findByRole("dialog");
    await within(dialog).findByRole("link");
    await userEvent.click(within(dialog).getByRole("button", { name: "Clear all" }));
    expect(within(dialog).queryByRole("link")).toBeNull();
    expect(within(dialog).getByText("Nothing new.")).toBeVisible();
  });

  it("the empty state says Nothing new.", async () => {
    mockApi(routes());
    await renderApp({ path: "/printers" });
    await userEvent.click(await bell());
    expect(await screen.findByText("Nothing new.")).toBeVisible();
  });

  it("says Loading notifications… while nothing has arrived", async () => {
    mockApi({ ...routes(), "GET /api/v1/jobs": () => new Promise(() => undefined), "GET /api/v1/printers": () => new Promise(() => undefined) });
    await renderApp({ path: "/printers" });
    await userEvent.click(await bell());
    expect(await screen.findByText("Loading notifications…")).toBeVisible();
  });

  it("says so when no source could be read, and Retry reads them again", async () => {
    mockApi({});
    await renderApp({ path: "/printers" });
    await userEvent.click(await bell());
    expect(await screen.findByText("Notifications could not be loaded.")).toBeVisible();
    mockApi(routes([job(J1, PRINTER_A.id, "done", { template_key: "cable", updated_at: minutesAgo(1) })]));
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("link", { name: /cable printed/ })).toBeVisible();
  });

  it("lists what it has when only one source failed", async () => {
    mockApi({ ...routes([]), "GET /api/v1/jobs": undefined });
    await renderApp({ path: "/printers" });
    await userEvent.click(await bell());
    expect(screen.queryByText("Notifications could not be loaded.")).toBeNull();
  });

  it("says when live updates are paused", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mockApi(routes());
    await renderApp({ path: "/printers" });
    // The test shell's stream never opens: after 5 s the shell calls it paused.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_100);
    });
    await userEvent.click(await bell());
    expect(await screen.findByText("Live updates paused; the list may be out of date.")).toBeVisible();
  });

  it("a failed job retried to done reads as printed on retry and is not an error", async () => {
    mockApi(
      routes([
        job(J1, PRINTER_A.id, "failed", { template_key: "cable", error: "Jam", updated_at: minutesAgo(20) }),
        job(J2, PRINTER_A.id, "done", { template_key: "cable", payload: { retry_of: J1 }, updated_at: minutesAgo(10) }),
      ]),
    );
    await renderApp({ path: "/printers" });
    await userEvent.click(await bell());
    expect(await screen.findByRole("link", { name: /cable failed, printed on retry/ })).toBeVisible();
    // React Aria hides everything outside the open panel from the accessibility tree, the bell included.
    expect(screen.getByRole("button", { name: /^Notifications, 2 unread, the most severe is a success/, hidden: true })).toBeInTheDocument();
  });

  it("says now for what happened under a minute ago, and counts minutes after that", async () => {
    mockApi(
      routes([
        job(J1, PRINTER_A.id, "done", { template_key: "fresh", updated_at: new Date(Date.now() - 5_000).toISOString() }),
        job(J2, PRINTER_A.id, "done", { template_key: "older", updated_at: minutesAgo(3) }),
      ]),
    );
    await renderApp({ path: "/printers" });
    await userEvent.click(await bell());
    const fresh = await screen.findByRole("link", { name: /fresh printed/ });
    expect(within(fresh).getByText("now")).toBeVisible();
    expect(within(screen.getByRole("link", { name: /older printed/ })).getByText("3 minutes ago")).toBeVisible();
  });

  it("is a full-height sheet with a close button on a phone", async () => {
    vi.stubGlobal("matchMedia", (query: string) => ({ matches: query.includes("max-width"), media: query, addEventListener: () => undefined, removeEventListener: () => undefined }));
    mockApi(routes([job(J1, PRINTER_A.id, "failed", { updated_at: minutesAgo(3) })]));
    await renderApp({ path: "/printers" });
    const trigger = await bell();
    await userEvent.click(trigger);
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(trigger).toHaveFocus());
  });
});
