import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SIGNED_IN, renderApp } from "../../test-utils";
import { mockApi, PRINTER_A, status } from "../test-api";

afterEach(() => vi.unstubAllGlobals());

const ROLL = { colour: null, media_raw: "12mm laminated", prompt_pending: true, set_at: null, width_mm: 12 };
const rollPath = `/api/v1/printers/${PRINTER_A.id}/roll`;
const detail = (over: Record<string, unknown> = {}, roll: unknown = ROLL, extra: Record<string, unknown> = {}) => ({
  [`GET /api/v1/printers/${PRINTER_A.id}`]: PRINTER_A,
  [`GET /api/v1/printers/${PRINTER_A.id}/status`]: status(PRINTER_A.id, {
    tape_loaded: "12mm laminated",
    tape_width_mm: 12,
    roll_prompt: true,
    tape_colour: null,
    ...over,
  }),
  [`GET ${rollPath}`]: roll,
  [`GET /api/v1/printers/${PRINTER_A.id}/queue`]: [],
  "GET /api/v1/jobs": [],
  ...extra,
});
const read = { ...SIGNED_IN, scope: "read" as const };

describe("RollColourPrompt (#229)", () => {
  it("offers the known colours and skip when the roll changed", async () => {
    mockApi(detail());
    await renderApp({ path: `/printers/${PRINTER_A.id}` });
    const group = await screen.findByRole("group", { name: "Tape colour" });
    for (const name of ["White", "Yellow", "Green", "Blue", "Red", "Black", "Clear"]) {
      expect(await screen.findByRole("button", { name: name })).toBeVisible();
    }
    expect(group).toBeVisible();
    expect(screen.getByRole("button", { name: "Skip" })).toBeVisible();
  });

  it("choosing Blue sends the colour with the width and media text that were shown", async () => {
    const { calls } = mockApi(detail({}, ROLL, { [`PUT ${rollPath}`]: { ...ROLL, colour: "blue", prompt_pending: false } }));
    await renderApp({ path: `/printers/${PRINTER_A.id}` });
    await userEvent.click(await screen.findByRole("button", { name: "Blue" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    const put = calls.find((c) => c.method === "PUT")!;
    expect(put.path).toBe(rollPath);
    expect(JSON.parse(put.body!)).toEqual({ colour: "blue", width_mm: 12, media_raw: "12mm laminated" });
  });

  it("Skip sends a null colour", async () => {
    const { calls } = mockApi(detail({}, ROLL, { [`PUT ${rollPath}`]: { ...ROLL, prompt_pending: false } }));
    await renderApp({ path: `/printers/${PRINTER_A.id}` });
    await userEvent.click(await screen.findByRole("button", { name: "Skip" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    expect(JSON.parse(calls.find((c) => c.method === "PUT")!.body!)).toMatchObject({ colour: null, width_mm: 12 });
  });

  it("a user who may only read sees no prompt", async () => {
    const { calls } = mockApi(detail());
    await renderApp({ path: `/printers/${PRINTER_A.id}`, session: read });
    expect(await screen.findByText("12 mm")).toBeVisible();
    // Let a roll request and its render happen if the page were going to make them.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 100));
    });
    expect(calls.some((c) => c.path === rollPath)).toBe(false);
    expect(screen.queryByRole("group", { name: "Tape colour" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Change colour" })).toBeNull();
  });

  it("no prompt for a stale status", async () => {
    mockApi(detail({ stale: true, online: null, roll_prompt: false, tape_loaded: null, tape_width_mm: null }));
    await renderApp({ path: `/printers/${PRINTER_A.id}` });
    expect(await screen.findByText("Tape not known")).toBeVisible();
    expect(screen.queryByRole("group", { name: "Tape colour" })).toBeNull();
  });

  it("a 409 roll-changed refetches and asks about the new roll", async () => {
    let swapped = false;
    const newRoll = { ...ROLL, width_mm: 24, media_raw: "24mm laminated" };
    mockApi(
      detail({}, () => (swapped ? newRoll : ROLL), {
        [`GET /api/v1/printers/${PRINTER_A.id}/status`]: () =>
          status(PRINTER_A.id, { tape_loaded: swapped ? "24mm laminated" : "12mm laminated", tape_width_mm: swapped ? 24 : 12, roll_prompt: true }),
        [`PUT ${rollPath}`]: () => {
          swapped = true;
          return new Response(JSON.stringify({ detail: { type: "roll-changed", title: "The roll changed" } }), {
            status: 409,
            headers: { "Content-Type": "application/json" },
          });
        },
      }),
    );
    await renderApp({ path: `/printers/${PRINTER_A.id}` });
    await userEvent.click(await screen.findByRole("button", { name: "Blue" }));
    expect(await screen.findByText(/changed again/i)).toBeVisible();
    await waitFor(() => expect(screen.getAllByText(/24 mm/).length).toBeGreaterThan(0));
    expect(screen.getByRole("group", { name: "Tape colour" })).toBeVisible();
  });

  it("a recorded colour shows next to the width and can be changed or removed", async () => {
    const { calls } = mockApi(
      detail({ roll_prompt: false, tape_colour: "blue" }, { ...ROLL, colour: "blue", prompt_pending: false }, { [`PUT ${rollPath}`]: { ...ROLL, prompt_pending: false } }),
    );
    await renderApp({ path: `/printers/${PRINTER_A.id}` });
    expect(await screen.findByText("Blue")).toBeVisible();
    expect(screen.queryByRole("group", { name: "Tape colour" })).toBeNull();
    fireEvent.click(await screen.findByRole("button", { name: "Change colour" }));
    expect(await screen.findByRole("group", { name: "Tape colour" })).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Remove colour" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    expect(JSON.parse(calls.find((c) => c.method === "PUT")!.body!)).toMatchObject({ colour: null });
  });

  it("without a colour there is no colour line, only a way to set one", async () => {
    mockApi(detail({ roll_prompt: false }, { ...ROLL, prompt_pending: false }));
    await renderApp({ path: `/printers/${PRINTER_A.id}` });
    expect(await screen.findByText("12 mm")).toBeVisible();
    expect(screen.queryByText(/colour not reported/i)).toBeNull();
    expect(screen.getByRole("button", { name: "Set colour" })).toBeVisible();
  });
});
