import { createMemoryHistory } from "@tanstack/react-router";
import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { App } from "../App";
import { initI18n } from "../i18n";
import { INFO, SIGNED_IN } from "../test-utils";
import { mockApi, sheetRead } from "../features/test-api";
import { createQueryClient } from "./queryClient";
import { createAppRouter } from "./router";
import { INFO_KEY, SESSION_KEY } from "./session";

async function mountAt(path: string) {
  await initI18n("en");
  const queryClient = createQueryClient();
  queryClient.setQueryData(INFO_KEY, INFO);
  queryClient.setQueryData(SESSION_KEY, SIGNED_IN);
  const router = createAppRouter({ history: createMemoryHistory({ initialEntries: [path] }) });
  render(<App queryClient={queryClient} router={router} />);
  await act(async () => {
    await router.load();
  });
  return router;
}

beforeEach(() => {
  mockApi({});
});

describe("sheet routes", () => {
  it.each(["/sheets/L4736-0002", "/sheet/L4736-0002"])("%s opens the sheet page for that code", async (path) => {
    mockApi({ "GET /api/sheets/L4736-0002": sheetRead("L4736-0002") });
    await mountAt(path);
    // The detail page asks for exactly the code in the path and titles itself with it.
    expect(await screen.findByRole("heading", { level: 1, name: "L4736-0002" })).toBeVisible();
  });

  it("/sheets/archive stays the archive page, not a sheet called archive", async () => {
    await mountAt("/sheets/archive");
    expect(await screen.findByRole("heading", { name: "Sheet archive" })).toBeVisible();
  });
});

describe("typed search parameters", () => {
  it("/cart keeps a sheet code and drops anything else", async () => {
    expect((await mountAt("/cart?sheet=L4736-0002")).state.location.search).toEqual({ sheet: "L4736-0002" });
    expect((await mountAt("/cart?sheet=not-a-code")).state.location.search).toEqual({});
    expect((await mountAt("/cart?sheet=l4736-0002")).state.location.search).toEqual({});
    expect((await mountAt("/cart")).state.location.search).toEqual({});
  });

  it("/calibration keeps printer and tray", async () => {
    const router = await mountAt("/calibration?printer=p1&tray=tray-2");
    expect(router.state.location.search).toEqual({ printer: "p1", tray: "tray-2" });
    expect((await mountAt("/calibration?printer=&tray=")).state.location.search).toEqual({});
  });

  it("typed links build their address (this also fails the typecheck when a parameter is undeclared)", async () => {
    const router = await mountAt("/");
    expect(router.buildLocation({ to: "/cart", search: { sheet: "L4736-0001" } }).href).toBe("/cart?sheet=L4736-0001");
    expect(router.buildLocation({ to: "/calibration", search: { printer: "p1", tray: "t2" } }).href).toBe(
      "/calibration?printer=p1&tray=t2",
    );
  });
});
