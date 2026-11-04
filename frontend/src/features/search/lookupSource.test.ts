import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";
import { initI18n } from "../../i18n";
import { INFO_KEY, type InfoData } from "../../app/session";
import { INFO } from "../../test-utils";
import { lookupSource } from "./lookupSource";

const withIntegrations = (integrations: InfoData["integrations"]) => {
  const queryClient = new QueryClient();
  queryClient.setQueryData(INFO_KEY, { ...INFO, integrations });
  return { queryClient };
};
const all = (snipeit: boolean, grocy: boolean, spoolman: boolean): InfoData["integrations"] => [
  { name: "snipeit", configured: snipeit },
  { name: "grocy", configured: grocy },
  { name: "spoolman", configured: spoolman },
];

describe("lookup search source", () => {
  it("offers a lookup in each configured integration, in navigation order", async () => {
    await initI18n("en");
    const results = await lookupSource.search("HH-AK0042", withIntegrations(all(true, true, false)));
    expect(results.map((r) => [r.title, r.href])).toEqual([
      ["Look up HH-AK0042 in Snipe-IT", "/lookup/snipeit/HH-AK0042"],
      ["Look up HH-AK0042 in Grocy", "/lookup/grocy/HH-AK0042"],
    ]);
  });

  it("offers nothing for an integration that is not set up", async () => {
    await initI18n("en");
    expect(await lookupSource.search("42", withIntegrations(all(false, false, false)))).toEqual([]);
    const only = await lookupSource.search("42", withIntegrations(all(false, false, true)));
    expect(only.map((r) => r.href)).toEqual(["/lookup/spoolman/42"]);
  });

  it("encodes the value in the link", async () => {
    await initI18n("en");
    const [first] = await lookupSource.search("loc:17 a/b", withIntegrations(all(true, false, false)));
    expect(first?.href).toBe("/lookup/snipeit/loc%3A17%20a%2Fb");
  });

  it("a pasted label link goes straight to the item it names", async () => {
    await initI18n("en");
    const results = await lookupSource.search("https://hub.example.invalid/spool/5", withIntegrations(all(true, true, true)));
    expect(results).toHaveLength(1);
    expect(results[0]?.href).toBe("/lookup/spoolman/5");
    expect(results[0]?.title).toBe("Open 5 in Spoolman");
  });

  it("a label link into an app that is not set up offers nothing", async () => {
    await initI18n("en");
    expect(await lookupSource.search("https://hub.example.invalid/spool/5", withIntegrations(all(true, true, false)))).toEqual([]);
  });

  it("sorts first, so the lookups stay above printers and jobs", () => {
    expect(lookupSource.order).toBeLessThan(10);
  });
});
