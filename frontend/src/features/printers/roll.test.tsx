// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderApp } from "../../test-utils";
import { job, mockApi, PRINTER_A, status } from "../test-api";
import type { Printer, PrinterStatus } from "./api";
import { describePrinter } from "./model";
import { NOT_WAITING, printerWaiting } from "./flags";
import { rollKey, rollSize, unsupportedRoll } from "./roll";

afterEach(() => vi.unstubAllGlobals());

const DIE_CUT = { tape_loaded: "29mm", tape_width_mm: 29, media_kind: "die_cut", label_length_mm: 90 };
const st = (over: Record<string, unknown> = {}) => status(PRINTER_A.id, { ...DIE_CUT, tape_colour: null, ...over }) as unknown as PrinterStatus;
const A = PRINTER_A as unknown as Printer;

describe("unsupportedRoll", () => {
  it("names a die-cut roll with its size", () => {
    const roll = unsupportedRoll(st());
    expect(roll).toEqual({ kind: "die_cut", widthMm: 29, lengthMm: 90 });
    expect(rollSize(roll!)).toBe("29 × 90 mm");
    expect(rollKey(roll!)).toBe("die_cut:29x90");
  });

  it.each([
    ["a continuous roll", { media_kind: "continuous", label_length_mm: null }],
    ["an unknown kind", { media_kind: null, label_length_mm: null }],
    ["a stale status", { stale: true }],
    ["an unpolled status", { polled: false }],
    ["an offline printer", { online: false }],
  ])("is none for %s", (_name, over) => {
    expect(unsupportedRoll(st(over))).toBeNull();
  });
});

describe("describePrinter with a die-cut roll", () => {
  it("is a warning while nothing waits", () => {
    const view = describePrinter(A, st(), false);
    expect(view).toMatchObject({ kind: "attention", badge: "warn" });
    expect(view.roll).toMatchObject({ widthMm: 29, lengthMm: 90 });
  });

  it("is a problem once a job waits", () => {
    expect(describePrinter(A, st(), false, { waiting: true, job: "x", refused: false })).toMatchObject({ kind: "error", badge: "bad" });
  });

  it("is a problem when a print was refused because of the roll", () => {
    expect(describePrinter(A, st(), false, { ...NOT_WAITING, rollRefused: true })).toMatchObject({ kind: "error", badge: "bad" });
  });

  it("is ready again with a continuous roll, whatever happened before", () => {
    const view = describePrinter(A, st({ media_kind: "continuous", label_length_mm: null }), false, { ...NOT_WAITING, rollRefused: true });
    expect(view).toMatchObject({ kind: "ready", badge: "ok" });
    expect(view.roll).toBeUndefined();
  });
});

describe("printerWaiting: a refusal because of the roll", () => {
  const mk = (id: string, state: string, error: string | null, at: string) =>
    job(id, A.id, state, { error, created_at: at, updated_at: at }) as never;

  it("counts when the newest finished job failed with media_type_mismatch", () => {
    const w = printerWaiting(A.id, [mk("1", "failed", "media_type_mismatch: die-cut", "2026-11-17T10:00:00Z")], {});
    expect(w.rollRefused).toBe(true);
    expect(w.waiting).toBe(false);
  });

  it("does not count when a later print went through, or the failure had another cause", () => {
    const later = [mk("1", "failed", "media_type_mismatch: x", "2026-11-17T10:00:00Z"), mk("2", "done", null, "2026-11-17T11:00:00Z")];
    expect(printerWaiting(A.id, later, {}).rollRefused).toBeUndefined();
    expect(printerWaiting(A.id, [mk("3", "failed", "printer_offline: x", "2026-11-17T10:00:00Z")], {})).toEqual(NOT_WAITING);
  });
});

describe("rendering", () => {
  const api = (over: Record<string, unknown>, jobs: unknown[] = []) =>
    mockApi({
      "GET /api/v1/printers": [PRINTER_A],
      [`GET /api/v1/printers/${PRINTER_A.id}/status`]: status(PRINTER_A.id, { ...DIE_CUT, tape_colour: null, ...over }),
      [`GET /api/v1/printers/${PRINTER_A.id}`]: PRINTER_A,
      "GET /api/v1/jobs": jobs,
    });

  it("the card names the die-cut roll, the warning and the hint", async () => {
    api({});
    await renderApp({ path: "/printers" });
    const card = await screen.findByRole("link", { name: /Workshop PT-P750W/ });
    expect(await within(card).findByText("29 × 90 mm · Die-cut labels")).toBeVisible();
    expect(within(card).getByText("Warning")).toBeVisible();
    expect(within(card).getByText("Unsupported roll loaded: 29 × 90 mm die-cut labels")).toBeVisible();
    expect(within(card).getByText("Printing on die-cut labels comes in a later version")).toBeVisible();
  });

  it("the card in German", async () => {
    api({});
    await renderApp({ path: "/printers", language: "de" });
    const card = await screen.findByRole("link", { name: /Workshop PT-P750W/ });
    expect(await within(card).findByText("29 × 90 mm · Stanzetiketten")).toBeVisible();
    expect(within(card).getByText("Nicht unterstützte Rolle eingelegt: 29 × 90 mm Stanzetiketten")).toBeVisible();
    expect(within(card).getByText("Drucken auf Stanzetiketten kommt in einer späteren Version")).toBeVisible();
  });

  it("a continuous roll stays '29 mm' without a roll line (counter-check)", async () => {
    api({ media_kind: "continuous", label_length_mm: null });
    await renderApp({ path: "/printers" });
    const card = await screen.findByRole("link", { name: /Workshop PT-P750W/ });
    expect(await within(card).findByText("Ready")).toBeVisible();
    expect(within(card).getByText("29 mm")).toBeVisible();
    expect(card.textContent).not.toContain("Unsupported roll");
  });

  it("a waiting job makes the card a problem", async () => {
    api({}, [job("aaaaaaaa-0000-4000-8000-000000000001", PRINTER_A.id, "queued")]);
    await renderApp({ path: "/printers" });
    const card = await screen.findByRole("link", { name: /Workshop PT-P750W/ });
    expect(await within(card).findByText("Problem")).toBeVisible();
  });

  it("the detail page shows the Material card and the sentence", async () => {
    api({});
    await renderApp({ path: `/printers/${PRINTER_A.id}` });
    expect(await screen.findByText("29 × 90 mm · Die-cut labels")).toBeVisible();
    // Once in the header and once as the reason the test print is off.
    expect(screen.getAllByText("Unsupported roll loaded: 29 × 90 mm die-cut labels").length).toBeGreaterThanOrEqual(1);
  });
});
