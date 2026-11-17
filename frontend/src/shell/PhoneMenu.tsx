// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useLingui } from "@lingui/react/macro";
import { useIsMutating } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";
import { Button, Dialog, DialogTrigger, Heading, Modal, ModalOverlay } from "react-aria-components";
import { useInfo, useSession } from "../app/session";
import { useConfiguredIntegrations } from "../features/integrations/api";
import { ConnectionStatus } from "./ConnectionStatus";
import { navGroups, SETTINGS_SECTIONS } from "./features";
import { CloseIcon, InfoIcon, MenuIcon, ReloadIcon, SignOutIcon } from "./icons";
import { IntegrationNavEntries } from "./IntegrationNav";
import { useNavLabels } from "./labels";
import { reloadApp } from "./pullToRefresh";
import { ThemeSwitch } from "./ThemeSwitch";
import { UpdateSidebarNotice } from "./UpdateNotice";
import { useBackdropClose } from "./useBackdropClose";

const FOCUS = "data-[focus-visible]:outline-3 data-[focus-visible]:outline-offset-1 data-[focus-visible]:outline-link";
const ICON_BUTTON = `press flex size-11 shrink-0 items-center justify-center rounded-r2 text-ink-2 transition-colors duration-150 hover:bg-sunken hover:text-ink ${FOCUS}`;
// 48 px rows: a thumb-sized target on a phone, where the sidebar's 40 px is for a pointer.
const ROW =
  "press flex h-12 items-center gap-3 rounded-r2 px-3 text-ink-2 transition-colors duration-150 hover:bg-sunken hover:text-ink data-[status=active]:bg-sunken data-[status=active]:font-bold data-[status=active]:text-ink focus-visible:outline-3 focus-visible:outline-offset-1 focus-visible:outline-link";

/** The entries of the menu: the sidebar's groups from `navGroups`, then the six settings sections for an admin. */
function MenuItems({ onNavigate }: { onNavigate: () => void }) {
  const { t } = useLingui();
  const info = useInfo();
  const session = useSession();
  const labels = useNavLabels();
  const integrations = useConfiguredIntegrations();
  const admin = session.scope === "admin";
  const groups = navGroups({ isOn: (feature) => info.data?.features[feature] ?? false, admin, integrations });

  return (
    <nav aria-label={t`Pages`} className="flex flex-col gap-6 px-3 py-2">
      {groups.map((group) => {
        // The Settings entry opens as its six sections (General is /settings itself).
        const settings = group.entries.find((entry) => entry.id === "settings");
        const entries = group.entries.filter((entry) => entry.id !== "settings");
        const heading = labels.group[group.id];
        const headingId = `menu-group-${group.id}`;
        return (
          <div key={group.id} className="flex flex-col gap-2">
            {/* A group that holds only Settings gets no heading of its own: Settings names it (and would sit right below it). */}
            {heading && !(settings && entries.length === 0) ? (
              <p id={headingId} className="px-3 text-small font-bold text-ink-3">
                {heading}
              </p>
            ) : null}
            {entries.length > 0 || group.id === "integrations" ? (
              <ul aria-labelledby={heading ? headingId : undefined} className="flex flex-col gap-0.5">
                {group.id === "integrations" && <IntegrationNavEntries integrations={integrations} row={ROW} onNavigate={onNavigate} />}
                {entries.map((entry) => (
                  <li key={entry.id}>
                    <Link
                      to={entry.to}
                      activeOptions={{ exact: entry.to === "/" || entry.to === "/sheets" }}
                      onClick={onNavigate}
                      className={ROW}
                    >
                      {entry.icon}
                      <span>{labels.entry[entry.id]}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            ) : null}
            {settings ? (
              <>
                <p id="menu-settings" className="px-3 text-small font-bold text-ink-3">
                  {labels.entry.settings}
                </p>
                <ul aria-labelledby="menu-settings" className="flex flex-col gap-0.5">
                  {SETTINGS_SECTIONS.map((section) => (
                    <li key={section.id}>
                      <Link to={section.to} activeOptions={{ exact: section.to === "/settings" }} onClick={onNavigate} className={`${ROW} pl-12`}>
                        <span>{labels.sections[section.id]}</span>
                      </Link>
                    </li>
                  ))}
                </ul>
              </>
            ) : null}
          </div>
        );
      })}
    </nav>
  );
}

/** Reload the app, for the installed app (no browser reload) and as the plain way when pulling down is awkward (#331). */
function ReloadEntry({ onNavigate }: { onNavigate: () => void }) {
  const { t } = useLingui();
  // A reload drops writes that are still on their way; the entry says so instead of silently doing it.
  const busy = useIsMutating() > 0;
  return (
    <div className="px-3 pt-2 pb-3">
      <button
        type="button"
        aria-disabled={busy || undefined}
        aria-describedby={busy ? "menu-reload-note" : undefined}
        onClick={() => {
          if (busy) return;
          onNavigate();
          void reloadApp();
        }}
        className={`${ROW} w-full ${busy ? "cursor-not-allowed opacity-60 hover:bg-transparent hover:text-ink-2" : ""}`}
      >
        <ReloadIcon />
        <span>{t`Reload`}</span>
      </button>
      {busy && (
        <p id="menu-reload-note" className="px-3 pt-1 text-small text-ink-3">
          {t`Wait until the current action has finished.`}
        </p>
      )}
    </div>
  );
}

/**
 * Phone menu (< 1024 px): the button at the top left opens a sheet from the left with every area of the hub, so calibration,
 * the settings and the integrations are reachable without the sidebar (#319). About, the theme and Sign out live here too.
 */
export function PhoneMenu() {
  const { t } = useLingui();
  const session = useSession();
  const [open, setOpen] = useState(false);
  const close = () => setOpen(false);
  const backdrop = useBackdropClose(open, close);

  return (
    <DialogTrigger isOpen={open} onOpenChange={setOpen}>
      <Button aria-label={t`Menu`} className={`${ICON_BUTTON} lg:hidden`}>
        <MenuIcon />
      </Button>
      <ModalOverlay
        ref={backdrop}
        // The dim area is handled by useBackdropClose; React Aria's own outside press would close the sheet a second time.
        isDismissable={false}
        // The overlay is the visible area, not the screen: with the on-screen keyboard open the sheet stays inside it.
        className="fixed inset-x-0 top-(--vv-top) z-50 h-(--vvh) bg-ink/40 data-[entering]:animate-[fadein_200ms_ease-out] motion-reduce:data-[entering]:animate-none"
      >
        <Modal className="h-full w-[min(20rem,86vw)] border-r border-line bg-surface data-[entering]:animate-[menuin_200ms_cubic-bezier(0.23,1,0.32,1)] motion-reduce:data-[entering]:animate-none">
          <Dialog aria-label={t`Menu`} className="flex h-full flex-col outline-none">
            {/* Header and footer stay put; only the entries scroll. The insets keep them clear of a notch and rounded corners. */}
            <div className="flex shrink-0 items-center gap-2 bg-surface pt-[max(0.75rem,env(safe-area-inset-top))] pr-4 pb-1 pl-[max(1rem,env(safe-area-inset-left))]">
              <Heading slot="title" className="min-w-0 flex-1 text-section font-bold">
                {t`Menu`}
              </Heading>
              <Button slot="close" aria-label={t`Close`} className={`${ICON_BUTTON} -mr-2`}>
                <CloseIcon width={20} height={20} />
              </Button>
            </div>
            <div data-testid="menu-scroll" className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
              <MenuItems onNavigate={close} />
              <ReloadEntry onNavigate={close} />
            </div>
            <div className="flex shrink-0 flex-col gap-3 border-t border-line pt-4 pr-4 pb-[max(1rem,env(safe-area-inset-bottom))] pl-[max(1rem,env(safe-area-inset-left))]">
              <div className="flex items-center gap-1">
                <Link to="/about" onClick={close} aria-label={t({ message: "About and licences", context: "link to the about page" })} className={ICON_BUTTON}>
                  <InfoIcon />
                </Link>
                <ThemeSwitch />
                <Button aria-label={t`Sign out`} onPress={() => void session.signOut()} className={ICON_BUTTON}>
                  <SignOutIcon />
                </Button>
              </div>
              {/* A waiting version (#354), right above the version it replaces. */}
              <UpdateSidebarNotice />
              <ConnectionStatus />
            </div>
          </Dialog>
        </Modal>
      </ModalOverlay>
    </DialogTrigger>
  );
}
