import { plural } from "@lingui/core/macro";
import { useLingui } from "@lingui/react/macro";
import { Fragment, useDeferredValue, useState } from "react";
import { Button } from "react-aria-components";
import { Section } from "../settings/sections";
import { TextInput } from "../settings/controls";
import { useLicenceLists, type LicenceEntry } from "./licences";

const SPDX_URL = "https://spdx.org/licenses/";
const KEYWORDS = new Set(["AND", "OR", "WITH"]);
const SPDX_ID = /^[A-Za-z0-9][A-Za-z0-9.+-]*$/;
const BREAK = "[overflow-wrap:anywhere]";
const CELL = "px-2 py-2 align-top sm:px-3";
const FOCUS = "data-[focus-visible]:outline-3 data-[focus-visible]:outline-offset-2 data-[focus-visible]:outline-link";

const rowKey = (entry: LicenceEntry) => `${entry.part}:${entry.name}@${entry.version}`;

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

function Rows({ entries }: { entries: LicenceEntry[] }) {
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
      {entries.map((entry) => {
        const key = rowKey(entry);
        const expanded = open.has(key);
        const textId = `licence-text-${key.replace(/[^A-Za-z0-9_-]/g, "_")}`;
        return (
          <Fragment key={key}>
            <tr className="border-t border-line">
              <td className={`${CELL} ${BREAK} font-bold text-ink`}>{entry.name}</td>
              <td className={`${CELL} ${BREAK} font-mono text-ink-2`}>{entry.version}</td>
              <td className={`${CELL} ${BREAK} text-ink`}>
                <LicenceId licence={entry.licence} link={entry.text === null} />
              </td>
              <td className={`${CELL} text-ink-2`}>{entry.part === "web" ? t({ message: "Web", context: "part of the hub" }) : t({ message: "Server", context: "part of the hub" })}</td>
              <td className="w-11 p-0 text-center align-top">
                {entry.text === null ? null : (
                  <Button
                    onPress={() => toggle(key)}
                    aria-expanded={expanded}
                    aria-controls={expanded ? textId : undefined}
                    aria-label={expanded ? t({ message: "Hide licence text", context: "action" }) : t({ message: "Show licence text", context: "action" })}
                    className={`press inline-flex h-11 w-11 items-center justify-center rounded-r2 text-ink-2 transition-colors duration-150 hover:text-ink ${FOCUS}`}
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
                  <pre id={textId} tabIndex={0} className={`max-h-80 overflow-auto whitespace-pre-wrap ${BREAK} rounded-r2 p-2 font-mono text-small text-ink`}>
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
  const { entries, missing, isPending } = useLicenceLists();
  const [filter, setFilter] = useState("");
  const needle = useDeferredValue(filter.trim().toLowerCase());
  const shown = needle ? entries.filter((e) => e.name.toLowerCase().includes(needle) || e.licence.toLowerCase().includes(needle)) : entries;

  return (
    <Section
      title={t({ message: "Third-party software", context: "heading" })}
      intro={t`Operating system packages of the image are listed in its SBOM; their licence texts are in /usr/share/doc inside the image.`}
    >
      {missing.includes("web") ? <p className="text-ink-2">{t`The licence list of the web app is not included in this build.`}</p> : null}
      {missing.includes("server") ? <p className="text-ink-2">{t`The licence list of the server is not included in this build.`}</p> : null}
      {isPending ? <p role="status" className="text-ink-2">{t`Loading…`}</p> : null}

      {entries.length > 0 ? (
        <>
          <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
            <div className="w-full max-w-sm">
              <TextInput label={t({ message: "Filter packages", context: "field label" })} hideLabel placeholder={t`Filter by package or licence`} value={filter} onChange={setFilter} inputMode="text" />
            </div>
            <p role="status" className="text-small text-ink-2">
              {plural(shown.length, { one: "# package", other: "# packages" })}
            </p>
          </div>
          {shown.length === 0 ? (
            <p className="text-ink-2">{t`No package matches the filter.`}</p>
          ) : (
            <div className="overflow-hidden rounded-r3 border border-line bg-surface">
              <table className="w-full table-fixed text-small">
                <thead>
                  <tr className="text-left text-ink-2">
                    <th scope="col" className={`${CELL} w-[29%] font-bold sm:w-[34%]`}>{t({ message: "Package", context: "column" })}</th>
                    <th scope="col" className={`${CELL} w-[22%] font-bold sm:w-[14%]`}>{t({ message: "Version", context: "column" })}</th>
                    <th scope="col" className={`${CELL} w-[24%] font-bold sm:w-[28%]`}>{t({ message: "Licence", context: "column" })}</th>
                    <th scope="col" className={`${CELL} w-[13%] font-bold sm:w-[13%]`}>{t({ message: "Part", context: "column" })}</th>
                    <th scope="col" className="w-11 p-0">
                      <span className="sr-only">{t({ message: "Licence text", context: "column" })}</span>
                    </th>
                  </tr>
                </thead>
                <Rows entries={shown} />
              </table>
            </div>
          )}
        </>
      ) : null}
    </Section>
  );
}
