// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useLingui } from "@lingui/react/macro";
import { Link } from "@tanstack/react-router";
import { useState } from "react";
import { Button, Dialog, DialogTrigger, Heading, Modal, ModalOverlay } from "react-aria-components";
import { useInfo, useSession } from "../app/session";
import { useConfiguredIntegrations } from "../features/integrations/api";
import { ConnectionStatus } from "./ConnectionStatus";
import { navGroups, SETTINGS_SECTIONS } from "./features";
import { CloseIcon, InfoIcon, MenuIcon, SignOutIcon } from "./icons";
import { IntegrationNavEntries } from "./IntegrationNav";
import { useNavLabels } from "./labels";
import { ThemeSwitch } from "./ThemeSwitch";
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
            {/* The System heading would sit right above the Settings heading: Settings names the group itself. */}
            {heading && !settings ? (
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
        <Modal className="h-full w-[min(20rem,86vw)] overflow-y-auto overscroll-contain border-r border-line bg-surface data-[entering]:animate-[menuin_200ms_cubic-bezier(0.23,1,0.32,1)] motion-reduce:data-[entering]:animate-none">
          <Dialog aria-label={t`Menu`} className="flex min-h-full flex-col outline-none">
            {/* Sticky: the sheet scrolls, the close button stays in reach. */}
            <div className="sticky top-0 z-10 flex items-center gap-2 bg-surface px-4 pt-3 pb-1">
              <Heading slot="title" className="min-w-0 flex-1 text-section font-bold">
                {t`Menu`}
              </Heading>
              <Button slot="close" aria-label={t`Close`} className={`${ICON_BUTTON} -mr-2`}>
                <CloseIcon width={20} height={20} />
              </Button>
            </div>
            <div className="flex-1">
              <MenuItems onNavigate={close} />
            </div>
            <div className="flex flex-col gap-3 border-t border-line px-4 pt-4 pb-[max(1rem,env(safe-area-inset-bottom))]">
              <div className="flex items-center gap-1">
                <Link to="/about" onClick={close} aria-label={t({ message: "About and licences", context: "link to the about page" })} className={ICON_BUTTON}>
                  <InfoIcon />
                </Link>
                <ThemeSwitch />
                <Button aria-label={t`Sign out`} onPress={() => void session.signOut()} className={ICON_BUTTON}>
                  <SignOutIcon />
                </Button>
              </div>
              {/* The slot above this line is kept free for the update notice (#354). */}
              <ConnectionStatus />
            </div>
          </Dialog>
        </Modal>
      </ModalOverlay>
    </DialogTrigger>
  );
}
