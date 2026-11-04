import { msg } from "@lingui/core/macro";
import { i18n } from "@lingui/core";
import { printersKey, type Printer } from "../printers/api";
import { apiFetch } from "../../api/client";
import type { SearchSource } from "./registry";

/** Printers by part of the name or the slug. The list is the one the printers page keeps fresh. */
export const printersSource: SearchSource = {
  id: "printers",
  order: 10,
  async search(query, { queryClient }) {
    const printers = await queryClient.ensureQueryData({
      queryKey: printersKey,
      queryFn: () => apiFetch<Printer[]>("/api/printers"),
    });
    const q = query.toLowerCase();
    const group = i18n._(msg`Printers`);
    return printers
      .filter((p) => p.name.toLowerCase().includes(q) || p.slug.toLowerCase().includes(q))
      .map((p) => ({ id: p.id, group, title: p.name, detail: p.slug, href: `/printers/${p.id}` }));
  },
};
