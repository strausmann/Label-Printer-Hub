import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { App } from "./App";
import { initI18n } from "./i18n";

describe("App", () => {
  it("renders the product title as the page heading", async () => {
    await initI18n("en");
    render(<App />);
    expect(screen.getByRole("heading", { level: 1, name: "Label Printer Hub" })).toBeInTheDocument();
  });
});
