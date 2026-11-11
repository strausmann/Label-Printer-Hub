import { I18nProvider } from "@lingui/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createQueryClient } from "../../app/queryClient";
import { i18n, initI18n } from "../../i18n";
import { renderApp, SIGNED_IN } from "../../test-utils";
import { AboutPage, AGPL_INFO_URL, PROJECT_LICENCE_TEXT_URL } from "./AboutPage";

const SOURCE = "https://example.invalid/fork/tree/v1.1.0";

afterEach(() => vi.unstubAllGlobals());

describe("AboutPage", () => {
  it("shows licence, version and source", async () => {
    await renderApp({
      path: "/about",
      info: { license: "AGPL-3.0-or-later", version: "1.1.0", revision: "abc1234", source_url: SOURCE },
    });
    expect(await screen.findByRole("heading", { level: 1, name: "About" })).toBeInTheDocument();
    expect(screen.getByText("AGPL-3.0-or-later")).toBeInTheDocument();
    expect(screen.getByText("1.1.0")).toBeInTheDocument();
    expect(screen.getByText("abc1234")).toBeInTheDocument();

    const page = within(screen.getByRole("main"));
    const source = page.getByRole("link", { name: "Source code" });
    expect(source).toHaveAttribute("href", SOURCE);
    expect(source.getAttribute("rel")).toContain("noopener");
    expect(source.getAttribute("rel")).toContain("noreferrer");
    expect(page.getByRole("link", { name: "Read the licence" })).toHaveAttribute("href", PROJECT_LICENCE_TEXT_URL);
    expect(page.getByRole("link", { name: "About the GNU AGPL" })).toHaveAttribute("href", AGPL_INFO_URL);
  });

  it("is open to a session that is not an admin", async () => {
    await renderApp({ path: "/about", session: { ...SIGNED_IN, scope: "print" } });
    expect(await screen.findByRole("heading", { level: 1, name: "About" })).toBeInTheDocument();
    expect(within(screen.getByRole("main")).getByRole("link", { name: "Source code" })).toBeInTheDocument();
  });

  it.each([
    ["en" as const, "unknown"],
    ["de" as const, "unbekannt"],
  ])("shows a revision the build did not know as '%s' in %s", async (language, word) => {
    await renderApp({ path: "/about", language, info: { revision: "unknown" } });
    await screen.findByRole("heading", { level: 1 });
    expect(screen.getByText(word)).toBeInTheDocument();
  });

  it("is in German, with the licence heading apart from the action", async () => {
    await renderApp({ path: "/about", language: "de" });
    expect(await screen.findByRole("heading", { level: 1, name: "Über" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Lizenz" })).toBeInTheDocument();
    const page = within(screen.getByRole("main"));
    expect(page.getByRole("link", { name: "Quellcode" })).toBeInTheDocument();
    expect(page.getByRole("link", { name: "Lizenz lesen" })).toBeInTheDocument();
    expect(page.getByRole("link", { name: "Über die GNU AGPL" })).toBeInTheDocument();
    expect(screen.getByText(/bekommst du jederzeit/)).toBeInTheDocument();
  });

  it("renders the dependency licences in the dependencies section", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (url !== "/licenses/frontend.json") return new Response("", { status: 404 });
        return new Response(JSON.stringify([{ name: "react", version: "19.3.1", license: "MIT", licenseText: "MIT text" }]), {
          headers: { "content-type": "application/json" },
        });
      }),
    );
    const { container } = await renderApp({ path: "/about" });
    await screen.findByRole("heading", { level: 1, name: "About" });
    const section = container.querySelector('[data-section="dependencies"]') as HTMLElement;
    expect(section).not.toBeNull();
    expect(await within(section).findByRole("row", { name: /react/ })).toBeInTheDocument();
    expect(within(section).getByRole("heading", { level: 2, name: "Third-party software" })).toBeInTheDocument();
    expect(within(section).getByText("The licence list of the server is not included in this build.")).toBeInTheDocument();
    // The project licence and the source link stay, whatever the lists say.
    expect(within(screen.getByRole("main")).getByRole("link", { name: "Source code" })).toBeInTheDocument();
  });

  it("renders while info is loading", async () => {
    await initI18n("en");
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => undefined)));
    render(
      <I18nProvider i18n={i18n}>
        <QueryClientProvider client={createQueryClient()}>
          <AboutPage />
        </QueryClientProvider>
      </I18nProvider>,
    );
    expect(screen.getAllByText("…").length).toBeGreaterThanOrEqual(3);
    for (const link of screen.queryAllByRole("link")) {
      expect(link.getAttribute("href")).toBeTruthy();
    }
    expect(screen.queryByRole("link", { name: "Source code" })).toBeNull();
  });
});
