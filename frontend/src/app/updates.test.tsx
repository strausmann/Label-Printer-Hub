import { act, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderApp } from "../test-utils";
import { mockApi } from "../features/test-api";
import { resetUpdatesForTest, startUpdates } from "./updates";

afterEach(() => {
  resetUpdatesForTest();
  vi.unstubAllGlobals();
});

describe("new version prompt", () => {
  it("appears on needRefresh and its button calls updateSW(true)", async () => {
    mockApi({});
    const updateSW = vi.fn(async () => {});
    let needRefresh!: () => void;
    startUpdates((options) => {
      needRefresh = options.onNeedRefresh;
      return updateSW;
    });
    await renderApp({ path: "/" });
    expect(screen.queryByText("New version available")).toBeNull();

    await act(async () => needRefresh());
    expect(screen.getByRole("status", { name: "" })).toBeDefined();
    expect(screen.getByText("New version available")).toBeVisible();
    // Non-blocking: the page is still there and usable.
    expect(screen.getByRole("main")).toBeVisible();

    await userEvent.click(screen.getByRole("button", { name: "Reload" }));
    expect(updateSW).toHaveBeenCalledWith(true);
  });

  it("stays away when the app never reports an update", async () => {
    mockApi({});
    startUpdates(() => async () => {});
    await renderApp({ path: "/" });
    expect(screen.queryByRole("button", { name: "Reload" })).toBeNull();
  });
});
