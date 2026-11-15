// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { USED_17, body, previewFor, routes } from "./testkit";
import { itemView, previews, resetBetweenTests } from "./SheetSection.kit";

// Each test boots the whole app and clicks re-render it, so the busiest ones take a few seconds on a loaded runner;
// the per-test limit is widened for this file only (vi.setConfig is scoped to the file).
vi.setConfig({ testTimeout: 15_000 });
resetBetweenTests();

describe("asking the server for previews", () => {
  it("changes in quick succession ask for one preview, not one each", async () => {
    const { calls } = await itemView(routes({ preview: previewFor("L4736-0001", [18, 19, 20], USED_17) }), 3);
    // Settled first: the preview for three copies has left, so no change is waiting for its timer.
    await waitFor(() => expect(body(previews(calls).at(-1)!).items).toHaveLength(3));
    const before = previews(calls).length;
    const cell18 = await screen.findByRole("gridcell", { name: /^Cell 18, new/ });
    const cell19 = screen.getByRole("gridcell", { name: /^Cell 19, new/ });
    // Two changes with no turn of the event loop between them: the wait the first one started cannot have
    // run out, however slow the machine is, so the test needs no clock and no assumption about speed.
    fireEvent.click(cell18);
    fireEvent.click(cell19);
    await waitFor(() => expect(body(previews(calls).at(-1)!).placements[0]).toMatchObject({ skip: [18, 19] }));
    // One preview for both changes: the one between them never left the browser. How long the wait is, and
    // that a change inside it restarts it, is useDebounced.test.tsx (fake timers); this checks the wiring.
    expect(previews(calls)).toHaveLength(before + 1);
  });
});
