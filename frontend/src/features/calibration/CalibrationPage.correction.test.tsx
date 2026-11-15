// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { respond } from "../test-api";
import { BASE, body, button, only, open, P, resetBetweenTests } from "./CalibrationPage.kit";

vi.setConfig({ testTimeout: 15_000 });
resetBetweenTests();

const CALIBRATION = "Print the calibration page (without correction)";
const CHECK = "Print the check page (with correction)";
// The page keeps watching a job it queued until the app is reloaded, so every test queues a job of its own.
let jobs = 0;
const post = (tray = "main") => ({ [`POST ${BASE}/${tray}/page`]: respond(202, { job_id: `eeeeeeee-0000-4000-8000-${String(++jobs).padStart(12, "0")}` }) });

/** The tray without a correction (the second one in the mock). */
const withoutCorrection = `/calibration?printer=${P}&tray=bypass`;

describe("the buttons depend on whether a correction is stored (#349)", () => {
  it("without a stored correction the calibration page is the main action and the check is disabled", async () => {
    await open({}, undefined, withoutCorrection);
    const calibration = await button(CALIBRATION);
    const check = await button(CHECK);
    expect(calibration).toBeEnabled();
    expect(calibration.className).toContain("bg-accent");
    expect(check).toBeDisabled();
    expect(check.className).not.toContain("bg-accent");
    expect(screen.getByText("Measure and save values first, then check.")).toBeVisible();
    // A disabled button is not reachable by keyboard: the hint is its description for a screen reader.
    expect(check).toHaveAccessibleDescription("Measure and save values first, then check.");
    expect(screen.getByRole("heading", { level: 2, name: "Step 1: Print the calibration page" })).toBeVisible();
  });

  it("with a stored correction the check is the main action in the current values", async () => {
    await open();
    const current = await screen.findByRole("region", { name: "Current values" });
    const check = await within(current).findByRole("button", { name: CHECK });
    expect(check).toBeEnabled();
    expect(check.className).toContain("bg-accent");
    expect(check).toHaveAccessibleDescription("Every crossing should be within 0.5 mm of the cut.");
    expect(within(current).getByText("Every crossing should be within 0.5 mm of the cut.")).toBeVisible();
    // Step 1 became "Measure again", and its button is the secondary one.
    const measure = await screen.findByRole("region", { name: "Measure again" });
    const again = within(measure).getByRole("button", { name: CALIBRATION });
    expect(again.className).not.toContain("bg-accent");
    expect(within(measure).getByRole("link", { name: "Download PDF" })).toBeVisible();
    // The check page comes before the calibration page in the reading order.
    expect(check.compareDocumentPosition(again) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("measuring again with a stored correction asks first", async () => {
    const { calls } = await open(post());
    await userEvent.click(await button(CALIBRATION));
    const dialog = await screen.findByRole("alertdialog", { name: "Print without correction?" });
    expect(dialog).toHaveTextContent("A correction is stored for this tray.");
    expect(within(dialog).getByRole("button", { name: "Print the check page" })).toBeVisible();
    expect(within(dialog).getByRole("button", { name: "Measure again anyway" })).toBeVisible();
    expect(only(calls, "POST", "/page")).toHaveLength(0);
  });

  it("the dialog's check button prints with correction", async () => {
    const { calls } = await open(post());
    await userEvent.click(await button(CALIBRATION));
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Print the check page" }));
    expect(only(calls, "POST", "/page")).toHaveLength(1);
    expect(body(only(calls, "POST", "/page")[0])).toEqual({ type: "L4736REV", version: 1, corrected: true });
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    // The answer shows under the check button, where a person looks for it.
    expect(await within(await screen.findByRole("status", { name: "Check page status" })).findByText("Queued")).toBeVisible();
  });

  it("measure again anyway prints without correction", async () => {
    const { calls } = await open(post());
    await userEvent.click(await button(CALIBRATION));
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Measure again anyway" }));
    expect(only(calls, "POST", "/page")).toHaveLength(1);
    expect(body(only(calls, "POST", "/page")[0])).toEqual({ type: "L4736REV", version: 1, corrected: false });
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(await within(await screen.findByRole("status", { name: "Calibration page status" })).findByText("Queued")).toBeVisible();
  });

  it("the dialog says the stored values stay in place until a new measurement is saved", async () => {
    await open(post());
    await userEvent.click(await button(CALIBRATION));
    expect(await screen.findByRole("alertdialog")).toHaveTextContent("The stored values stay in place until you save a new measurement.");
  });

  it("after measuring again anyway focus returns to the calibration button, which is still enabled while the page is queued", async () => {
    // The answer is held back, so the print is still pending when the dialog closes and hands focus back.
    let release: () => void = () => undefined;
    const held = new Promise<void>((resolve) => (release = resolve));
    const { calls } = await open({
      [`POST ${BASE}/main/page`]: async () => {
        await held;
        return respond(202, { job_id: `eeeeeeee-0000-4000-8000-${String(++jobs).padStart(12, "0")}` });
      },
    });
    await userEvent.click(await button(CALIBRATION));
    await userEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Measure again anyway" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    const again = screen.getByRole("button", { name: CALIBRATION });
    expect(again).toBeEnabled();
    await waitFor(() => expect(again).toHaveFocus());
    // A second press while it is queued says so, asks nothing and sends nothing.
    await userEvent.click(again);
    expect(await screen.findByText("A print is already on its way.")).toBeVisible();
    // A live region that was in the page before the text came, so a screen reader announces it.
    expect(screen.getByText("A print is already on its way.")).toHaveAttribute("role", "status");
    expect(screen.getByRole("button", { name: CALIBRATION })).toHaveAccessibleDescription("A print is already on its way.");
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(only(calls, "POST", "/page")).toHaveLength(1);
    release();
    await waitFor(() => expect(screen.getByRole("status", { name: "Calibration page status" })).toHaveTextContent("Queued"));
    // Once it is out of the queue the note is gone.
    expect(screen.queryByText("A print is already on its way.")).toBeNull();
  });

  it("escape closes the dialog without printing", async () => {
    const { calls } = await open(post());
    await userEvent.click(await button(CALIBRATION));
    await screen.findByRole("alertdialog");
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(only(calls, "POST", "/page")).toHaveLength(0);
  });

  it("cancel closes the dialog without printing", async () => {
    const { calls } = await open(post());
    await userEvent.click(await button(CALIBRATION));
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(only(calls, "POST", "/page")).toHaveLength(0);
  });

  it("without a stored correction the calibration page prints at once, without asking", async () => {
    const { calls } = await open(post("bypass"), undefined, withoutCorrection);
    await userEvent.click(await button(CALIBRATION));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    await waitFor(() => expect(only(calls, "POST", "/page")).toHaveLength(1));
    expect(body(only(calls, "POST", "/page")[0])).toMatchObject({ corrected: false });
  });

  it("switching to a tray without correction switches the state", async () => {
    await open();
    expect(await button(CHECK)).toBeEnabled();
    await userEvent.click(await screen.findByRole("button", { name: /Tray$/ }));
    await userEvent.click(await screen.findByRole("option", { name: "Bypass" }));
    await waitFor(() => expect(screen.getByRole("button", { name: CHECK })).toBeDisabled());
    expect(screen.getByText("Measure and save values first, then check.")).toBeVisible();
    expect(screen.getByRole("button", { name: CALIBRATION }).className).toContain("bg-accent");
    expect(screen.getByRole("heading", { level: 2, name: "Step 1: Print the calibration page" })).toBeVisible();
  });
});
