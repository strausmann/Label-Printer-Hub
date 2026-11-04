import { msg } from "@lingui/core/macro";
import { i18n } from "@lingui/core";
import { INFO_KEY, type InfoData } from "../../app/session";
import { appNameOf, LOOKUP_APPS } from "../lookup/apps";
import { parseLabelUrl } from "../lookup/labelUrl";
import type { SearchResult, SearchSource } from "./registry";

const lookupHref = (app: string, id: string) => `/lookup/${app}/${encodeURIComponent(id)}`;

/**
 * "Look up <q> in <App>" for each configured integration, listed before everything else.
 * A pasted label link is the one case where the app is known: it offers that item alone.
 */
export const lookupSource: SearchSource = {
  id: "integration-lookup",
  order: 0,
  async search(query, { queryClient }) {
    const info = queryClient.getQueryData<InfoData>(INFO_KEY);
    const configured = new Set(info?.integrations.filter((i) => i.configured).map((i) => i.name));
    const group = i18n._(msg`Look up in an integration`);

    const label = parseLabelUrl(query);
    if (label) {
      if (!configured.has(label.app)) return [];
      const name = appNameOf(label.app);
      return [{ id: `open-${label.app}`, group, title: i18n._(msg`Open ${label.id} in ${name}`), code: label.id, href: lookupHref(label.app, label.id) }];
    }

    return LOOKUP_APPS.filter((app) => configured.has(app)).map((app): SearchResult => {
      const name = appNameOf(app);
      return { id: `lookup-${app}`, group, title: i18n._(msg`Look up ${query} in ${name}`), code: query, href: lookupHref(app, query) };
    });
  },
};
