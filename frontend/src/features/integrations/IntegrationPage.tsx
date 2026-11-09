import { i18n } from "@lingui/core";
import { msg } from "@lingui/core/macro";
import { useLingui } from "@lingui/react";
import { useLingui as useMacroLingui } from "@lingui/react/macro";
import { useQueryClient } from "@tanstack/react-query";
import { getRouteApi, Link, useNavigate } from "@tanstack/react-router";
import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { Button } from "react-aria-components";
import { NotFoundPage } from "../../pages/placeholders";
import { StatusBadge } from "../../shell/StatusBadge";
import { FIELD, PRIMARY_BUTTON } from "../../shell/SignIn";
import { DEFAULT_CONTENT_TYPE, isLookupApp, safeHref, useAppName } from "../lookup/apps";
import { useCart, type LookupApp } from "../lookup/cart";
import { resolveInput } from "../lookup/labelUrl";
import { useRecent, type RecentItem, type RecentKind } from "../lookup/recent";
import { PANEL, SECONDARY_BUTTON, SECTION_HEADING } from "../ui";
import { useIntegrationStates, useIsAdmin } from "./api";
import { baseUrlOf } from "./baseUrl";

const integrationRoute = getRouteApi("/integrations/$app");

export function IntegrationPage() {
  const { app } = integrationRoute.useParams();
  return isLookupApp(app) ? <Start app={app} /> : <NotFoundPage />;
}

const FIND_HEADING = {
  snipeit: msg`Find an asset or location`,
  grocy: msg`Find a product`,
  spoolman: msg`Find a spool`,
};
const HINT = {
  snipeit: msg`Asset tag (for example AT-0042), numeric ID (42) or a printed label link. Locations need the loc: prefix, for example loc:17.`,
  grocy: msg`Product ID or barcode.`,
  spoolman: msg`Spool ID.`,
};
const SCAN_LABEL = { snipeit: msg`Scan`, grocy: msg`Scan barcode`, spoolman: msg`Scan` };
const KIND_LABEL: Record<RecentKind, ReturnType<typeof msg>> = {
  asset: msg`Asset`,
  location: msg`Location`,
  product: msg`Product`,
  spool: msg`Spool`,
};

/** A keyboard is expected on a desktop; on a phone it would cover the page the moment it opens. */
const hasFinePointer = () => window.matchMedia?.("(pointer: fine)").matches ?? true;

function ago(at: number, now: number): string {
  const seconds = Math.max(0, Math.round((now - at) / 1000));
  if (seconds < 45) return i18n._(msg`just now`);
  const rtf = new Intl.RelativeTimeFormat(i18n.locale, { numeric: "auto" });
  if (seconds < 3600) return rtf.format(-Math.max(1, Math.floor(seconds / 60)), "minute");
  if (seconds < 86400) return rtf.format(-Math.floor(seconds / 3600), "hour");
  return rtf.format(-Math.floor(seconds / 86400), "day");
}

function Start({ app }: { app: LookupApp }) {
  const { t } = useMacroLingui();
  const { _ } = useLingui();
  const appName = useAppName()(app);
  const admin = useIsAdmin();
  const configured = useIntegrationStates().find((i) => i.app === app)?.configured ?? false;
  const cart = useCart();
  const inCart = cart.items.length;
  const base = useKnownBase(app);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <p className="text-small text-ink-3">
          {t`Integrations`} <span aria-hidden="true">›</span> {appName}
        </p>
        <header className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <h1 className="text-title font-bold">{appName}</h1>
          <StatusBadge state={configured ? "ok" : "idle"} label={configured ? t`Configured` : t`Not set up`} />
          {configured && base && (
            <a href={base} target="_blank" rel="noopener noreferrer" className={SECONDARY_BUTTON}>
              {t`Open ${appName}`}&nbsp;<span aria-hidden="true">↗</span>
            </a>
          )}
          {inCart > 0 && (
            <Link to="/cart" className="press ml-auto inline-flex h-11 items-center text-link underline underline-offset-2">
              {t`Cart (${inCart})`}
            </Link>
          )}
        </header>
      </div>

      {configured ? (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
          <Finder app={app} heading={_(FIND_HEADING[app])} hint={_(HINT[app])} scan={_(SCAN_LABEL[app])} />
          <Recent app={app} />
        </div>
      ) : (
        <section className={`${PANEL} flex max-w-xl flex-col items-start gap-3`}>
          <p>{t`${appName} is not set up yet, so there is nothing to look up.`}</p>
          {admin ? (
            <Link to="/settings/integrations" className="text-link underline underline-offset-2">
              {t`Open Settings › Integrations`}
            </Link>
          ) : (
            <p className="text-ink-2">{t`Ask an admin to set it up.`}</p>
          )}
        </section>
      )}
    </div>
  );
}

/**
 * The app's own address, known only once an item of it was shown in this session: the hub's
 * `/api/v1/info` carries no URL on purpose, a lookup result does carry the deep link.
 */
function useKnownBase(app: LookupApp): string | null {
  const queryClient = useQueryClient();
  for (const [, result] of queryClient.getQueriesData<{ url?: string | null }>({ queryKey: ["lookup", app] })) {
    const href = safeHref(result?.url);
    const base = href ? baseUrlOf(app, href) : null;
    if (base) return base;
  }
  return null;
}

function Finder({ app, heading, hint, scan }: { app: LookupApp; heading: string; hint: string; scan: string }) {
  const navigate = useNavigate();
  const [value, setValue] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const id = useId();

  useEffect(() => {
    if (hasFinePointer()) input.current?.focus();
  }, [app]);

  const open = (event: FormEvent) => {
    event.preventDefault();
    const target = resolveInput(app, value);
    if (target) void navigate({ to: "/lookup/$app/$id", params: { app: target.app, id: target.id } });
  };

  return (
    <section aria-labelledby={`${id}-h`} className={`${PANEL} flex flex-col gap-4`}>
      <h2 id={`${id}-h`} className={SECTION_HEADING}>{heading}</h2>
      <form onSubmit={open} className="flex flex-col gap-3">
        <input
          ref={input}
          value={value}
          onChange={(event) => setValue(event.target.value)}
          aria-labelledby={`${id}-h`}
          aria-describedby={`${id}-hint`}
          inputMode="text"
          enterKeyHint="go"
          autoComplete="off"
          autoCapitalize="none"
          autoCorrect="off"
          spellCheck={false}
          className={`${FIELD} code focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-link font-mono`}
        />
        <div className="flex gap-2">
          <Button type="submit" className={`${PRIMARY_BUTTON} flex-1 sm:flex-none`}>
            {i18n._(msg`Open`)}
          </Button>
          <Link to="/scan" className={`${SECONDARY_BUTTON} flex-1 sm:flex-none`}>
            {scan}
          </Link>
        </div>
      </form>
      <p id={`${id}-hint`} className="text-small text-ink-2">{hint}</p>
    </section>
  );
}

function Recent({ app }: { app: LookupApp }) {
  const { t } = useMacroLingui();
  const { _ } = useLingui();
  const items = useRecent(app);
  const cart = useCart();
  const [now] = useState(() => Date.now());
  const [added, setAdded] = useState<string | null>(null);

  return (
    <section aria-labelledby="recent-h" className={`${PANEL} flex flex-col gap-3`}>
      <h2 id="recent-h" className={SECTION_HEADING}>{t`Recently opened`}</h2>
      {items.length === 0 ? (
        <p className="text-ink-2">{t`Nothing opened yet.`}</p>
      ) : (
        <ul aria-labelledby="recent-h" className="flex flex-col divide-y divide-line">
          {items.map((item) => (
            <RecentRow
              key={item.id}
              app={app}
              item={item}
              kind={_(KIND_LABEL[item.kind])}
              age={ago(item.at, now)}
              onPrint={() => {
                cart.add({ app, id: item.id, name: item.name, content_type: DEFAULT_CONTENT_TYPE, copies: 1 });
                setAdded(item.name);
              }}
            />
          ))}
        </ul>
      )}
      <p role="status" className="min-h-5 text-small text-ink">
        {added !== null && t`Added to the cart: ${added}`}
      </p>
      <p className="text-small text-ink-2">{t`Kept only in this browser. Print adds the label to the cart.`}</p>
    </section>
  );
}

function RecentRow({ app, item, kind, age, onPrint }: { app: LookupApp; item: RecentItem; kind: string; age: string; onPrint: () => void }) {
  const { t } = useMacroLingui();
  return (
    <li className="grid grid-cols-[minmax(0,5.5rem)_minmax(0,1fr)_auto] items-center gap-3 py-3 first:pt-0">
      <code className="truncate text-code" title={item.id}>{item.id}</code>
      <span className="flex min-w-0 flex-col">
        <Link to="/lookup/$app/$id" params={{ app, id: item.id }} className="truncate font-bold text-ink hover:underline">
          {item.name}
        </Link>
        <span className="truncate text-small text-ink-2">
          {kind} · {age}
        </span>
      </span>
      <Button
        aria-label={t`Print ${item.name}`}
        onPress={onPrint}
        className="press inline-flex h-11 min-w-11 items-center justify-center rounded-full border border-line-strong bg-surface px-3 text-small font-bold text-ink hover:bg-sunken data-[focus-visible]:outline-3 data-[focus-visible]:outline-offset-2 data-[focus-visible]:outline-link"
      >
        {t`Print`}
      </Button>
    </li>
  );
}
