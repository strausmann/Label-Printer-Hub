import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SIGNED_IN, renderApp } from "../../test-utils";
import { mockApi, PRINTER_A, respond, status } from "../test-api";

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
    const group = await screen.findByRole("radiogroup", { name: "Tape colour" });
    for (const name of ["White", "Yellow", "Green", "Blue", "Red", "Black", "Clear"]) {
      expect(await screen.findByRole("radio", { name: name })).toBeVisible();
    }
    expect(group).toBeVisible();
    expect(screen.getByRole("button", { name: "Skip" })).toBeVisible();
  });

  it("colour choices are radios: one is marked, nothing is sent until Save", async () => {
    const { calls } = mockApi(detail({}, ROLL, { [`PUT ${rollPath}`]: { ...ROLL, colour: "blue", prompt_pending: false } }));
    await renderApp({ path: `/printers/${PRINTER_A.id}` });
    const group = await screen.findByRole("radiogroup", { name: "Tape colour" });
    // They are radios, not toggle buttons (no aria-pressed), and Save waits for a choice.
    expect(within(group).queryAllByRole("button")).toHaveLength(0);
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.click(screen.getByRole("radio", { name: "Blue" }));
    expect(screen.getByRole("radio", { name: "Blue" })).toBeChecked();
    await userEvent.click(screen.getByRole("radio", { name: "Red" }));
    expect(screen.getByRole("radio", { name: "Red" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "Blue" })).not.toBeChecked();
    expect(calls.some((c) => c.method === "PUT")).toBe(false);
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
  });

  it("the arrow keys move the choice inside the group", async () => {
    mockApi(detail());
    await renderApp({ path: `/printers/${PRINTER_A.id}` });
    await userEvent.click(await screen.findByRole("radio", { name: "White" }));
    await userEvent.keyboard("{ArrowRight}");
    expect(screen.getByRole("radio", { name: "Yellow" })).toBeChecked();
  });

  it("choosing Blue and saving sends the colour with the width and media text that were shown", async () => {
    const { calls } = mockApi(detail({}, ROLL, { [`PUT ${rollPath}`]: { ...ROLL, colour: "blue", prompt_pending: false } }));
    await renderApp({ path: `/printers/${PRINTER_A.id}` });
    await userEvent.click(await screen.findByRole("radio", { name: "Blue" }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
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
    expect(screen.queryByRole("radiogroup", { name: "Tape colour" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Change colour" })).toBeNull();
  });

  it("a roll that cannot be read says so and offers a retry instead of showing nothing", async () => {
    mockApi(detail({}, () => new Response(JSON.stringify({ detail: "boom" }), { status: 500, headers: { "Content-Type": "application/json" } })));
    await renderApp({ path: `/printers/${PRINTER_A.id}` });
    expect(await screen.findByText("The roll could not be read.", {}, { timeout: 5000 })).toBeVisible();
    expect(screen.getByRole("button", { name: "Retry" })).toBeVisible();
    expect(screen.queryByRole("radiogroup", { name: "Tape colour" })).toBeNull();
  });

  it("no prompt for a stale status", async () => {
    mockApi(detail({ stale: true, online: null, roll_prompt: false, tape_loaded: null, tape_width_mm: null }));
    await renderApp({ path: `/printers/${PRINTER_A.id}` });
    expect(await screen.findByText("Tape not known")).toBeVisible();
    expect(screen.queryByRole("radiogroup", { name: "Tape colour" })).toBeNull();
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
    await userEvent.click(await screen.findByRole("radio", { name: "Blue" }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText(/changed again/i)).toBeVisible();
    await waitFor(() => expect(screen.getAllByText(/24 mm/).length).toBeGreaterThan(0));
    expect(screen.getByRole("radiogroup", { name: "Tape colour" })).toBeVisible();
    // The colour marked for the old roll is gone: the operator picks again for the new one.
    expect(screen.getByRole("radio", { name: "Blue" })).not.toBeChecked();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });

  it("a recorded colour shows next to the width and can be changed or removed", async () => {
    const { calls } = mockApi(
      detail({ roll_prompt: false, tape_colour: "blue" }, { ...ROLL, colour: "blue", prompt_pending: false }, { [`PUT ${rollPath}`]: { ...ROLL, prompt_pending: false } }),
    );
    await renderApp({ path: `/printers/${PRINTER_A.id}` });
    expect(await screen.findByText("Blue")).toBeVisible();
    expect(screen.queryByRole("radiogroup", { name: "Tape colour" })).toBeNull();
    fireEvent.click(await screen.findByRole("button", { name: "Change colour" }));
    expect(await screen.findByRole("radiogroup", { name: "Tape colour" })).toBeVisible();
    // The current colour is marked, and saving it again would change nothing.
    expect(screen.getByRole("radio", { name: "Blue" })).toBeChecked();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
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

  describe("focus and the open panel (263-39, 263-40, 263-41)", () => {
    const statusKey = ["printers", PRINTER_A.id, "status"];

    it("focus returns to trigger: after the panel closes by Escape, Cancel and Save, and after a prompt without a width", async () => {
      const { calls } = mockApi(
        detail({ roll_prompt: false }, { ...ROLL, colour: "blue", prompt_pending: false }, { [`PUT ${rollPath}`]: { ...ROLL, prompt_pending: false } }),
      );
      await renderApp({ path: `/printers/${PRINTER_A.id}` });
      const trigger = await screen.findByRole("button", { name: "Set colour" });
      for (const close of [() => userEvent.keyboard("{Escape}"), async () => userEvent.click(screen.getByRole("button", { name: "Cancel" }))]) {
        await userEvent.click(trigger);
        expect(await screen.findByRole("radiogroup", { name: "Tape colour" })).toBeVisible();
        await close();
        await waitFor(() => expect(screen.queryByRole("radiogroup", { name: "Tape colour" })).toBeNull());
        expect(trigger).toHaveFocus();
      }
      await userEvent.click(trigger);
      await userEvent.click(await screen.findByRole("radio", { name: "Green" }));
      await userEvent.click(screen.getByRole("button", { name: "Save" }));
      await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
      await waitFor(() => expect(screen.queryByRole("radiogroup", { name: "Tape colour" })).toBeNull());
      expect(trigger).toHaveFocus();
    });

    it("focus returns to trigger: a roll without a known width has no trigger, so the material heading takes the focus", async () => {
      let answered = false;
      const widthless = { ...ROLL, width_mm: null, media_raw: null };
      mockApi(
        detail({ tape_loaded: null, tape_width_mm: null }, widthless, {
          [`GET /api/v1/printers/${PRINTER_A.id}/status`]: () =>
            status(PRINTER_A.id, { tape_loaded: null, tape_width_mm: null, roll_prompt: !answered, tape_colour: null }),
          [`PUT ${rollPath}`]: () => {
            answered = true;
            return { ...widthless, prompt_pending: false };
          },
        }),
      );
      await renderApp({ path: `/printers/${PRINTER_A.id}` });
      await userEvent.click(await screen.findByRole("button", { name: "Skip" }));
      await waitFor(() => expect(screen.queryByRole("radiogroup", { name: "Tape colour" })).toBeNull());
      expect(screen.queryByRole("button", { name: /colour/i })).toBeNull();
      await waitFor(() => expect(screen.getByRole("heading", { name: "Material" })).toHaveFocus());
    });

    it("roll change closes edit panel: a new question replaces it instead of being rebound to it", async () => {
      let swapped = false;
      const newRoll = { ...ROLL, width_mm: 24, media_raw: "24mm laminated", prompt_pending: true };
      const { queryClient } = await (async () => {
        mockApi(
          detail({}, () => (swapped ? newRoll : { ...ROLL, colour: "blue", prompt_pending: false }), {
            [`GET /api/v1/printers/${PRINTER_A.id}/status`]: () =>
              swapped
                ? status(PRINTER_A.id, { tape_loaded: "24mm laminated", tape_width_mm: 24, roll_prompt: true, tape_colour: null })
                : status(PRINTER_A.id, { roll_prompt: false, tape_colour: "blue" }),
          }),
        );
        return renderApp({ path: `/printers/${PRINTER_A.id}` });
      })();
      await userEvent.click(await screen.findByRole("button", { name: "Change colour" }));
      expect(await screen.findByRole("button", { name: "Remove colour" })).toBeVisible();
      // Focus is inside the panel when the other roll goes in.
      expect(screen.getByRole("radio", { name: "Blue" })).toHaveFocus();
      swapped = true;
      await act(async () => {
        await queryClient.invalidateQueries({ queryKey: statusKey });
      });
      // Only the prompt's own choices remain; the edit panel is closed, its trigger is collapsed and has the focus.
      expect(await screen.findByRole("heading", { name: "The roll was changed" })).toBeVisible();
      expect(screen.getAllByRole("radiogroup", { name: "Tape colour" })).toHaveLength(1);
      expect(screen.queryByRole("button", { name: "Remove colour" })).toBeNull();
      expect(screen.getByRole("button", { name: "Set colour" })).toHaveAttribute("aria-expanded", "false");
      expect(screen.getByRole("button", { name: "Set colour" })).toHaveFocus();
    });

    it("escape handler subscribes once per opening, not on every render", async () => {
      // Every answer differs from the last (structural sharing would otherwise hand back the same object and skip the render).
      let reading = 0;
      mockApi(
        detail({ roll_prompt: false }, { ...ROLL, colour: "blue", prompt_pending: false }, {
          [`GET /api/v1/printers/${PRINTER_A.id}/status`]: () => status(PRINTER_A.id, { roll_prompt: false, tape_colour: "blue", last_probe_age_s: reading++ }),
        }),
      );
      const { queryClient } = await renderApp({ path: `/printers/${PRINTER_A.id}` });
      await userEvent.click(await screen.findByRole("button", { name: "Change colour" }));
      await screen.findByRole("radiogroup", { name: "Tape colour" });
      const spy = vi.spyOn(document, "addEventListener");
      const keydownAdds = () => spy.mock.calls.filter(([type]) => type === "keydown").length;
      // Each refetch hands the page a new status object, so the component renders again.
      for (let i = 0; i < 3; i++) {
        await act(async () => {
          await queryClient.invalidateQueries({ queryKey: statusKey });
        });
      }
      expect(keydownAdds()).toBe(0);
      spy.mockRestore();
    });
  });

  it("a 500 on saving says so and keeps the choice", async () => {
    mockApi(detail({}, ROLL, { [`PUT ${rollPath}`]: () => respond(500, { detail: "boom" }) }));
    await renderApp({ path: `/printers/${PRINTER_A.id}` });
    await userEvent.click(await screen.findByRole("radio", { name: "Red" }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("The colour could not be saved. Try again.")).toBeVisible();
    expect(screen.getByRole("radio", { name: "Red" })).toBeChecked();
  });

  it("a failed save does not leave the focus on the page: it returns to the choices", async () => {
    // While the save is pending the buttons are disabled, and the focused Save drops the focus to the page.
    mockApi(detail({}, ROLL, { [`PUT ${rollPath}`]: () => respond(500, { detail: "boom" }) }));
    await renderApp({ path: `/printers/${PRINTER_A.id}` });
    await userEvent.click(await screen.findByRole("radio", { name: "Red" }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await screen.findByText("The colour could not be saved. Try again.");
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("radio", { name: "Red" })));
  });

  it("while the new-roll question shows, the edit control opens no second set of choices", async () => {
    mockApi(detail());
    await renderApp({ path: `/printers/${PRINTER_A.id}` });
    await screen.findByRole("radiogroup", { name: "Tape colour" });
    const trigger = await screen.findByRole("button", { name: "Set colour" });
    expect(trigger).toHaveAttribute("aria-disabled", "true");
    await userEvent.click(trigger);
    expect(screen.getAllByRole("radiogroup", { name: "Tape colour" })).toHaveLength(1);
  });
});
