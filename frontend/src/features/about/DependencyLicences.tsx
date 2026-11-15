// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { plural } from "@lingui/core/macro";
import { useLingui } from "@lingui/react/macro";
import { Fragment, useDeferredValue, useMemo, useState } from "react";
import { Button, Input, Label, SearchField } from "react-aria-components";
import { Section } from "../settings/sections";
import { FIELD } from "../../shell/SignIn";
import { SECONDARY_BUTTON } from "../ui";
import { useLicenceLists, type LicenceEntry } from "./licences";

const SPDX_URL = "https://spdx.org/licenses/";
const KEYWORDS = new Set(["AND", "OR", "WITH"]);
const SPDX_ID = /^[A-Za-z0-9][A-Za-z0-9.+-]*$/;
/**
 * A button reached by Tab must not end up under the top bar (4 rem), the pinned filter bar (about 6.5 rem) or the tab bar
 * on phones (4 rem): scroll margins as tall as those bars. On short screens the filter bar is not pinned.
 */
const SCROLL_CLEAR = "scroll-mt-44 scroll-mb-24 [@media(max-height:500px)]:scroll-mt-20";
const BREAK = "[overflow-wrap:anywhere]";
const CELL = "px-1.5 py-2 align-top sm:px-3";
/** The list starts with this many rows; the rest is one button away (the filter always searches all). */
export const INITIAL_ROWS = 50;
const FOCUS = "data-[focus-visible]:outline-3 data-[focus-visible]:outline-offset-2 data-[focus-visible]:outline-link";

type Keyed = { entry: LicenceEntry; key: string };

/** A key per record that survives filtering; a record that repeats within a list gets a counter. */
function withKeys(entries: LicenceEntry[]): Keyed[] {
  const seen = new Map<string, number>();
  return entries.map((entry) => {
    const base = `${entry.part}:${entry.name}@${entry.version}`;
    const n = seen.get(base) ?? 0;
    seen.set(base, n + 1);
    return { entry, key: n === 0 ? base : `${base}#${n}` };
  });
}

/** The licence expression as text; a package without a licence text of its own links each id to the SPDX text. */
function LicenceId({ licence, link }: { licence: string; link: boolean }) {
  const { t } = useLingui();
  if (!link) return <>{licence}</>;
  return (
    <>
      {licence.split(/(\s+|[()])/).map((token, index) =>
        SPDX_ID.test(token) && !KEYWORDS.has(token) && !token.startsWith("LicenseRef-") ? (
          <a
            key={index}
            href={`${SPDX_URL}${encodeURIComponent(token)}.html`}
            target="_blank"
            rel="noopener noreferrer"
            aria-label={t`${token}: licence text at SPDX`}
            className="text-link underline underline-offset-2"
          >
            {token}
          </a>
        ) : (
          <Fragment key={index}>{token}</Fragment>
        ),
      )}
    </>
  );
}

function Chevron({ open }: { open: boolean }) {
  return (
    <svg
      viewBox="0 0 12 12"
      width="12"
      height="12"
      aria-hidden="true"
      className={`fill-none stroke-current stroke-2 transition-transform duration-150 ease-out motion-reduce:transition-none ${open ? "rotate-180" : ""}`}
    >
      <path d="m2 4 4 4 4-4" />
    </svg>
  );
}

function Rows({ rows }: { rows: Keyed[] }) {
  const { t } = useLingui();
  const [open, setOpen] = useState<ReadonlySet<string>>(new Set());
  const toggle = (key: string) =>
    setOpen((current) => {
      const next = new Set(current);
      if (!next.delete(key)) next.add(key);
      return next;
    });

  return (
    <tbody>
      {rows.map(({ entry, key }) => {
        const expanded = open.has(key);
        const textId = `licence-text-${key.replace(/[^A-Za-z0-9_-]/g, "_")}`;
        return (
          <Fragment key={key}>
            <tr className="border-t border-line">
              <td className={`${CELL} ${BREAK} font-bold text-ink`}>{entry.name}</td>
              <td className={`${CELL} ${BREAK} font-mono text-ink-2`}>{entry.version}</td>
              <td className={`${CELL} ${BREAK} text-ink`}>
                {entry.licence.trim() === "" ? <span className="text-ink-2">{t({ message: "Licence unknown", context: "licence of a package" })}</span> : <LicenceId licence={entry.licence} link={entry.text === null} />}
              </td>
              <td className={`${CELL} ${BREAK} text-ink-2`}>{entry.part === "web" ? t({ message: "Web", context: "part of the hub" }) : t({ message: "Server", context: "part of the hub" })}</td>
              <td className="w-10 p-0 text-center align-top">
                {entry.text === null ? null : (
                  <Button
                    onPress={() => toggle(key)}
                    aria-expanded={expanded}
                    aria-controls={expanded ? textId : undefined}
                    aria-label={
                      expanded
                        ? t({ message: `Hide licence text of ${entry.name}`, context: "action" })
                        : t({ message: `Show licence text of ${entry.name}`, context: "action" })
                    }
                    className={`press inline-flex h-11 w-10 items-center justify-center rounded-r2 text-ink-2 transition-colors duration-150 hover:text-ink ${FOCUS} data-[focus-visible]:outline-offset-[-3px] ${SCROLL_CLEAR}`}
                  >
                    <Chevron open={expanded} />
                  </Button>
                )}
              </td>
            </tr>
            {expanded && entry.text !== null ? (
              <tr className="bg-sunken">
                <td colSpan={5} className="px-2 pb-3 sm:px-3">
                  {/* A scrollable region has to be reachable from the keyboard. */}
                  {/* eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex */}
                  <pre id={textId} role="region" tabIndex={0} aria-label={t`Licence text of ${entry.name}`} className={`max-h-80 overflow-auto whitespace-pre-wrap ${BREAK} rounded-r2 border border-line p-2 font-mono text-small text-ink`}>
                    {entry.text}
                  </pre>
                </td>
              </tr>
            ) : null}
          </Fragment>
        );
      })}
    </tbody>
  );
}

/** Every third-party package the web app and the server ship, with its licence, from the two lists the image build writes. */
export function DependencyLicences() {
  const { t } = useLingui();
  const { entries, missing, failed, isPending, retry } = useLicenceLists();
  const [filter, setFilter] = useState("");
  const [all, setAll] = useState(false);
  const needle = useDeferredValue(filter.trim().toLowerCase());
  const keyed = useMemo(() => withKeys(entries), [entries]);
  const matches = needle ? keyed.filter(({ entry }) => entry.name.toLowerCase().includes(needle) || entry.licence.toLowerCase().includes(needle)) : keyed;
  const shown = all ? matches : matches.slice(0, INITIAL_ROWS);

  return (
    <Section
      title={t({ message: "Third-party software", context: "heading" })}
      intro={t`Operating system packages of the image are listed in its SBOM; their licence texts are in /usr/share/doc inside the image.`}
    >
      {missing.includes("web") ? <p className="text-ink-2">{t`The licence list of the web app is not included in this build.`}</p> : null}
      {missing.includes("server") ? <p className="text-ink-2">{t`The licence list of the server is not included in this build.`}</p> : null}
      {failed.length > 0 ? (
        <div role="alert" className="flex flex-wrap items-center gap-3">
          <p className="text-ink">{t`The licence list could not be loaded.`}</p>
          <Button onPress={retry} className={`${SECONDARY_BUTTON}`}>
            {t({ message: "Try again", context: "action" })}
          </Button>
        </div>
      ) : null}
      {isPending ? <p role="status" className="text-ink-2">{t`Loading…`}</p> : null}

      {entries.length > 0 ? (
        <>
          {/* Stays under the top bar while the rows scroll, so field and results are in view together. Not on short screens (keyboard up): there it would be a third of the height. */}
          <div className="sticky top-16 z-[5] [@media(max-height:500px)]:static -mx-1 flex flex-wrap items-center justify-between gap-x-4 gap-y-1 bg-bg px-1 py-2">
            <div className="w-full max-w-sm">
              <SearchField value={filter} onChange={setFilter} className="relative block">
                <Label className="sr-only">{t({ message: "Filter packages", context: "field label" })}</Label>
                <Input
                  placeholder={t`Filter by package or licence`}
                  enterKeyHint="search"
                  spellCheck={false}
                  autoCapitalize="none"
                  className={`${FIELD} pr-11 [&::-webkit-search-cancel-button]:hidden`}
                />
                {filter === "" ? null : (
                  <Button
                    aria-label={t({ message: "Clear filter", context: "action" })}
                    className={`press absolute inset-y-0 right-0 inline-flex w-11 items-center justify-center rounded-r2 text-ink-2 hover:text-ink ${FOCUS}`}
                  >
                    <svg viewBox="0 0 12 12" width="12" height="12" aria-hidden="true" className="fill-none stroke-current stroke-2">
                      <path d="m2 2 8 8m0-8-8 8" />
                    </svg>
                  </Button>
                )}
              </SearchField>
            </div>
            <p aria-live="polite" className="text-small text-ink-2">
              {shown.length < matches.length
                ? t`${shown.length} of ${matches.length} packages`
                : plural(matches.length, { one: "# package", other: "# packages" })}
            </p>
          </div>
          {matches.length === 0 ? (
            <p className="text-ink-2">{t`No package matches the filter.`}</p>
          ) : (
            <>
              <div className="rounded-r3 border border-line bg-surface">
                <table className="w-full table-fixed text-small">
                  <thead>
                    <tr className="text-left text-ink-2">
                      <th scope="col" className={`${CELL} w-[32%] font-bold sm:w-[34%]`}>{t({ message: "Package", context: "column" })}</th>
                      <th scope="col" className={`${CELL} w-[22%] font-bold sm:w-[14%]`}>{t({ message: "Version", context: "column" })}</th>
                      <th scope="col" className={`${CELL} w-[20%] font-bold sm:w-[28%]`}>{t({ message: "Licence", context: "column" })}</th>
                      <th scope="col" className={`${CELL} w-[14%] font-bold sm:w-[13%]`}>{t({ message: "Part", context: "column" })}</th>
                      <th scope="col" className="w-10 p-0">
                        <span className="sr-only">{t({ message: "Licence text", context: "column" })}</span>
                      </th>
                    </tr>
                  </thead>
                  <Rows rows={shown} />
                </table>
              </div>
              {shown.length < matches.length ? (
                <div>
                  <Button onPress={() => setAll(true)} className={`${SECONDARY_BUTTON} ${SCROLL_CLEAR}`}>
                    {t({ message: `Show all ${matches.length} packages`, context: "action" })}
                  </Button>
                </div>
              ) : null}
            </>
          )}
        </>
      ) : null}
    </Section>
  );
}
