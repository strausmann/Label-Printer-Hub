// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { I18nProvider } from "@lingui/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { i18n, initI18n } from "../../../i18n";
import { notificationJobsKey } from "../../notifications/jobsQuery";
import type { Job, Printer, PrinterStatus } from "../../printers/api";
import { job, PRINTER_A, status } from "../../test-api";
import { PrinterRow, printerWaits } from "./PrinterRow";

const P = PRINTER_A as unknown as Printer;
const cover = status(PRINTER_A.id, { error_flags: ["doorOpen"], error_state: "doorOpen" }) as unknown as PrinterStatus;

async function renderRow(jobs: Job[]) {
  await initI18n("en");
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  // The jobs the bell reads; `usePrinterWaiting` reads the same query.
  client.setQueryData(notificationJobsKey, jobs);
  render(
    <QueryClientProvider client={client}>
      <I18nProvider i18n={i18n}>
        <PrinterRow printer={P} status={cover} />
      </I18nProvider>
    </QueryClientProvider>,
  );
}

describe("PrinterRow (#376)", () => {
  it("an open cover with a queued job is a problem, as on the card and in the notification", async () => {
    await renderRow([job("aaaaaaaa-0000-4000-8000-000000000001", PRINTER_A.id, "queued") as unknown as Job]);
    expect(await screen.findByText("Problem")).toBeVisible();
  });

  it("an open cover with nothing waiting is a warning", async () => {
    await renderRow([]);
    expect(await screen.findByText("Warning")).toBeVisible();
  });

  it("a print to a printer that reports a condition waits", () => {
    expect(printerWaits("attention")).toBe(true);
    expect(printerWaits("ready")).toBe(false);
  });
});
