// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { renderHook, act } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApiError } from "../../api/client";
import { PRINTER_A, status } from "../test-api";
import type { PrinterStatus } from "./api";
import { noteJobEvent, notePrintError, observeStatuses, useCoverRefusals } from "./coverRefusals";

const P = PRINTER_A.id;
const reading = (capturedAt: string, flags: string[] = []) =>
  ({ [P]: status(P, { captured_at: capturedAt, error_flags: flags }) as unknown as PrinterStatus });

const current = () => renderHook(() => useCoverRefusals()).result;

describe("cover refusals", () => {
  it("a cover-open job event records a refusal", () => {
    const refusals = current();
    act(() => noteJobEvent(P, { job_id: "j1", to_state: "failed", error_code: "printer_cover_open" }));
    expect(refusals.current).toEqual({ [P]: { title: "" } });
  });

  it("a 409 printer_cover_open of this browser records one", () => {
    const refusals = current();
    act(() => notePrintError(P, "Shelf 3", new ApiError(409, "printer_cover_open", "The printer cover is open.")));
    expect(refusals.current).toEqual({ [P]: { title: "Shelf 3" } });
  });

  it("another failure code records none", () => {
    const refusals = current();
    act(() => {
      notePrintError(P, "Shelf 3", new ApiError(409, "printer_offline", "offline"));
      notePrintError(P, "Shelf 3", new Error("network"));
      noteJobEvent(P, { job_id: "j1", to_state: "failed", error_code: "tape_mismatch" });
      noteJobEvent(P, { job_id: "j1", to_state: "queued", error_code: "printer_cover_open" });
      noteJobEvent(null, { job_id: "j1", to_state: "failed", error_code: "printer_cover_open" });
    });
    expect(refusals.current).toEqual({});
  });

  it("the status without doorOpen clears it", () => {
    const refusals = current();
    act(() => notePrintError(P, "", new ApiError(409, "printer_cover_open", "x")));
    // The reading current at the refusal can predate the open cover: it does not clear.
    act(() => observeStatuses(reading("2026-11-14T10:00:00Z")));
    expect(refusals.current).toEqual({ [P]: { title: "" } });
    // A new reading with the cover still open keeps it.
    act(() => observeStatuses(reading("2026-11-14T10:00:01Z", ["doorOpen"])));
    expect(refusals.current).toEqual({ [P]: { title: "" } });
    // A new reading with the cover closed clears it.
    act(() => observeStatuses(reading("2026-11-14T10:00:02Z")));
    expect(refusals.current).toEqual({});
  });
});
