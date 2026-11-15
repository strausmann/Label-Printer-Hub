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
    expect(screen.getByRole("heading", { level: 2, name: "Step 1: Print the calibration page" })).toBeVisible();
  });

  it("with a stored correction the check is the main action in the current values", async () => {
    await open();
    const current = await screen.findByRole("region", { name: "Current values" });
    const check = await within(current).findByRole("button", { name: CHECK });
    expect(check).toBeEnabled();
    expect(check.className).toContain("bg-accent");
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
