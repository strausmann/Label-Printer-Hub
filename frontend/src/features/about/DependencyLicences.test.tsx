import { I18nProvider } from "@lingui/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createQueryClient } from "../../app/queryClient";
import { i18n, initI18n } from "../../i18n";
import { DependencyLicences } from "./DependencyLicences";

const WEB = [
  { name: "react", version: "19.3.1", license: "MIT", licenseText: "MIT text of react" },
  { name: "@headlessui/vue", version: "1.7.23", license: "MIT", licenseText: null },
];
const SERVER = [
  { name: "brother-ql", version: "0.9.4", license: "GPL-3.0-or-later", licenseText: "GNU GENERAL PUBLIC LICENSE" },
  { name: "anyio", version: "4.0.0", license: "MIT", licenseText: "anyio text" },
];

type Reply = { body?: unknown; status?: number; type?: string; raw?: string } | "missing";

function stubLists(web: Reply, server: Reply) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const reply = url === "/licenses/frontend.json" ? web : url === "/licenses/backend.json" ? server : undefined;
      if (reply === undefined) throw new Error(`unexpected fetch ${url}`);
      if (reply === "missing") return new Response("", { status: 404 });
      return new Response(reply.raw ?? JSON.stringify(reply.body), { status: reply.status ?? 200, headers: { "content-type": reply.type ?? "application/json" } });
    }),
  );
}

async function show() {
  await initI18n("en");
  return render(
    <I18nProvider i18n={i18n}>
      <QueryClientProvider client={createQueryClient()}>
        <DependencyLicences />
      </QueryClientProvider>
    </I18nProvider>,
  );
}

const OS_SENTENCE = /Operating system packages of the image are listed in its SBOM/;

beforeEach(() => stubLists({ body: WEB }, { body: SERVER }));
afterEach(() => vi.unstubAllGlobals());

describe("DependencyLicences", () => {
  it("lists package, version, licence and part, sorted by name across both parts", async () => {
    await show();
    const table = await screen.findByRole("table");
    expect(within(table).getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["Package", "Version", "Licence", "Part", "Licence text"]);
    const names = within(table).getAllByRole("row").slice(1).map((r) => within(r).getAllByRole("cell")[0]!.textContent);
    expect(names).toEqual(["@headlessui/vue", "anyio", "brother-ql", "react"]);
    const brother = screen.getByRole("row", { name: /brother-ql/ });
    expect(within(brother).getByText("0.9.4")).toBeInTheDocument();
    expect(within(brother).getByText("GPL-3.0-or-later")).toBeInTheDocument();
    expect(within(brother).getByText("Server")).toBeInTheDocument();
    expect(within(screen.getByRole("row", { name: /^react/ })).getByText("Web")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Third-party software" })).toBeInTheDocument();
    expect(screen.getByText("4 packages")).toBeInTheDocument();
  });

  it("mounts no licence text until it is asked for", async () => {
    await show();
    await screen.findByRole("table");
    expect(screen.queryByText("GNU GENERAL PUBLIC LICENSE")).toBeNull();
    const row = screen.getByRole("row", { name: /brother-ql/ });
    const user = userEvent.setup();
    const button = within(row).getByRole("button", { name: "Show licence text" });
    expect(button).toHaveAttribute("aria-expanded", "false");
    await user.click(button);
    expect(screen.getByText("GNU GENERAL PUBLIC LICENSE")).toBeInTheDocument();
    expect(within(row).getByRole("button", { name: "Hide licence text" })).toHaveAttribute("aria-expanded", "true");
    await user.click(within(row).getByRole("button", { name: "Hide licence text" }));
    expect(screen.queryByText("GNU GENERAL PUBLIC LICENSE")).toBeNull();
  });

  it("shows the licence id and a link to the SPDX text where a package ships no text (no empty block, no button)", async () => {
    await show();
    const row = await screen.findByRole("row", { name: /@headlessui\/vue/ });
    expect(within(row).queryByRole("button")).toBeNull();
    const link = within(row).getByRole("link", { name: "MIT: licence text at SPDX" });
    expect(link).toHaveAttribute("href", "https://spdx.org/licenses/MIT.html");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(link).toHaveTextContent("MIT");
  });

  it("links every id of an expression and leaves operators and unknown references as text", async () => {
    stubLists({ body: [{ name: "dual", version: "1", license: "(MIT OR Apache-2.0) AND LicenseRef-x", licenseText: null }] }, { body: [] });
    await show();
    const row = await screen.findByRole("row", { name: /dual/ });
    expect(within(row).getAllByRole("link").map((a) => a.getAttribute("href"))).toEqual(["https://spdx.org/licenses/MIT.html", "https://spdx.org/licenses/Apache-2.0.html"]);
    expect(row.textContent).toContain("(MIT OR Apache-2.0) AND LicenseRef-x");
  });

  it("shows a hostile text as literal text and creates no element from it", async () => {
    const hostile = "<script>alert(1)</script><img src=x onerror=alert(2)>";
    stubLists({ body: [{ name: "evil", version: "1", license: "MIT", licenseText: hostile }] }, { body: [] });
    const { container } = await show();
    const row = await screen.findByRole("row", { name: /evil/ });
    await userEvent.setup().click(within(row).getByRole("button", { name: "Show licence text" }));
    expect(screen.getByText(hostile)).toBeInTheDocument();
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
  });

  it("filters by package and licence and says when nothing matches", async () => {
    await show();
    await screen.findByRole("table");
    const user = userEvent.setup();
    const filter = screen.getByRole("textbox", { name: "Filter packages" });
    await user.type(filter, "gpl");
    expect(await screen.findByText("1 package")).toBeInTheDocument();
    expect(screen.getByRole("row", { name: /brother-ql/ })).toBeInTheDocument();
    expect(screen.queryByRole("row", { name: /^react/ })).toBeNull();
    await user.clear(filter);
    await user.type(filter, "no-such-package");
    expect(await screen.findByText("No package matches the filter.")).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("names the server list as missing and keeps the web rows", async () => {
    stubLists({ body: WEB }, "missing");
    await show();
    expect(await screen.findByText("The licence list of the server is not included in this build.")).toBeInTheDocument();
    expect(screen.queryByText("The licence list of the web app is not included in this build.")).toBeNull();
    expect(screen.getByRole("row", { name: /^react/ })).toBeInTheDocument();
    expect(screen.queryByRole("row", { name: /brother-ql/ })).toBeNull();
  });

  it("with both lists missing shows the two messages and the OS sentence, no table", async () => {
    stubLists({ type: "text/html", raw: "<!doctype html><title>app</title>" }, "missing");
    await show();
    expect(await screen.findByText("The licence list of the web app is not included in this build.")).toBeInTheDocument();
    expect(screen.getByText("The licence list of the server is not included in this build.")).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.getByText(OS_SENTENCE)).toBeInTheDocument();
  });

  it("always shows the OS sentence, also while loading", async () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => undefined)));
    await show();
    expect(screen.getByText(OS_SENTENCE)).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Loading…");
  });

  it("renders a 2 MB list as rows with a count and mounts no text", async () => {
    const text = "x".repeat(7000);
    const big = Array.from({ length: 300 }, (_, i) => ({ name: `pkg-${String(i).padStart(3, "0")}`, version: "1.0.0", license: "MIT", licenseText: text }));
    stubLists({ body: big }, { body: [] });
    const { container } = await show();
    expect(await screen.findByText("300 packages")).toBeInTheDocument();
    expect(JSON.stringify(big).length).toBeGreaterThan(2_000_000);
    expect(container.querySelectorAll("pre")).toHaveLength(0);
    expect(container.textContent).not.toContain("xxxxxxxxxx");
  });

  it("is in German", async () => {
    await initI18n("de");
    render(
      <I18nProvider i18n={i18n}>
        <QueryClientProvider client={createQueryClient()}>
          <DependencyLicences />
        </QueryClientProvider>
      </I18nProvider>,
    );
    expect(await screen.findByRole("heading", { level: 2, name: "Software von Dritten" })).toBeInTheDocument();
    expect(await screen.findByText("4 Pakete")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Lizenztext anzeigen" }).length).toBeGreaterThan(0);
    expect(screen.getByText(/Die Betriebssystempakete des Images stehen in seiner SBOM/)).toBeInTheDocument();
  });
});
