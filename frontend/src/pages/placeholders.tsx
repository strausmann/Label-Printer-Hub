// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useLingui } from "@lingui/react/macro";
import { Link } from "@tanstack/react-router";

/**
 * Stand-ins for pages that later tasks build. Each one is replaced by importing the real
 * page in `app/router.tsx`; until then the shell has something honest to show.
 */
function PagePlaceholder({ title }: { title: string }) {
  const { t } = useLingui();
  return (
    <div>
      <h1 className="text-title font-bold">{title}</h1>
      <p className="mt-2 text-ink-2">{t`This page is not available yet.`}</p>
    </div>
  );
}

/* Modules that have not shipped: their navigation entries stay hidden until `features` says so. */
export function AsnPage() {
  const { t } = useLingui();
  return <PagePlaceholder title={t`Paperless ASN`} />;
}
export function KeptPage() {
  const { t } = useLingui();
  return <PagePlaceholder title={t`Kept / Hangar / Grocy`} />;
}

export function NotFoundPage() {
  const { t } = useLingui();
  return (
    <div>
      <h1 className="text-title font-bold">{t`Page not found`}</h1>
      <p className="mt-2">
        <Link to="/" className="text-link underline underline-offset-2">
          {t`Back to the overview`}
        </Link>
      </p>
    </div>
  );
}
