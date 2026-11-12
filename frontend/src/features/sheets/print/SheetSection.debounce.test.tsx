import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
    await userEvent.click(await screen.findByRole("gridcell", { name: /^Cell 18, new/ }));
    await userEvent.click(screen.getByRole("gridcell", { name: /^Cell 19, new/ }));
    await waitFor(() => expect(body(previews(calls).at(-1)!).placements[0]).toMatchObject({ skip: [18, 19] }));
    // The first preview, and the one for both changes: the one between them never left the browser.
    expect(previews(calls)).toHaveLength(2);
  });
});
