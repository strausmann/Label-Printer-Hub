import { defineRouteMiddleware } from "@astrojs/starlight/route-data";

const SOCIAL_CARD = "https://labelyard.app/social-card.png";
const OG_LOCALE: Record<string, string> = { en: "en_GB", de: "de_DE" };

type SidebarEntry = { type: "link"; href: string } | { type: "group"; entries: SidebarEntry[] };

function hrefs(entry: SidebarEntry): string[] {
  return entry.type === "link" ? [entry.href] : entry.entries.flatMap(hrefs);
}

/** Drop the API reference group of the other language (both are generated into every sidebar). */
function keepOwnApiGroup(entries: SidebarEntry[], german: boolean): SidebarEntry[] {
  return entries
    .filter((entry) => {
      const links = hrefs(entry);
      const api = links.length > 0 && links.every((href) => /\/developers\/api\//.test(href));
      if (!api) return true;
      return links.every((href) => href.startsWith("/de/")) === german;
    })
    .map((entry) =>
      entry.type === "group" ? { ...entry, entries: keepOwnApiGroup(entry.entries, german) } : entry,
    );
}

export const onRequest = defineRouteMiddleware(async (context, next) => {
  await next();
  const route = context.locals.starlightRoute;
  const german = route.lang === "de";

  route.sidebar = keepOwnApiGroup(route.sidebar as SidebarEntry[], german) as typeof route.sidebar;

  // Starlight writes og:locale as the bare language ("de"); replace it with the full form.
  route.head = route.head.filter(
    (tag) => !(tag.tag === "meta" && tag.attrs?.property === "og:locale"),
  );
  route.head.push(
    { tag: "meta", attrs: { property: "og:image", content: SOCIAL_CARD } },
    { tag: "meta", attrs: { name: "twitter:image", content: SOCIAL_CARD } },
    { tag: "meta", attrs: { property: "og:locale", content: OG_LOCALE[route.lang] ?? "en_GB" } },
  );
});
