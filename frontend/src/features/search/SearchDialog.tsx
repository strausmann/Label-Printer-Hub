// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useLingui } from "@lingui/react/macro";
import { useRouter } from "@tanstack/react-router";
import { useEffect, useRef } from "react";
import { Button, Dialog, DialogTrigger, Modal, ModalOverlay } from "react-aria-components";
import { CloseIcon, SearchIcon } from "../../shell/icons";
import { useBackdropClose } from "../../shell/useBackdropClose";
import { SearchResults } from "./SearchResults";
import { useSearch } from "./useSearch";

const ICON_BUTTON =
  "press flex size-11 shrink-0 items-center justify-center rounded-r2 text-ink-2 transition-colors duration-150 hover:bg-sunken hover:text-ink data-[focus-visible]:outline-3 data-[focus-visible]:outline-offset-1 data-[focus-visible]:outline-link";

/** The field, its close button and the list. Mounted only while the dialog is open, so every opening starts with an empty field. */
function SearchPanel({ close }: { close: () => void }) {
  const { t } = useLingui();
  const router = useRouter();
  const search = useSearch((result) => {
    close();
    router.history.push(result.href);
  });
  // The field takes the focus when the dialog opens, which brings up the keyboard on a phone.
  const field = useRef<HTMLInputElement>(null);
  useEffect(() => field.current?.focus(), []);
  return (
    <>
      <div className="flex shrink-0 items-center gap-1 p-2">
        <div role="search" className="relative min-w-0 flex-1">
          <SearchIcon width={18} height={18} className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-ink-3" />
          <input
            {...search.inputProps}
            ref={field}
            className="h-11 w-full rounded-r2 border border-line-strong bg-sunken pr-3 pl-10 text-ink placeholder:text-ink-3 focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-link [&::-webkit-search-cancel-button]:appearance-none"
          />
        </div>
        <Button slot="close" aria-label={t`Close`} className={ICON_BUTTON}>
          <CloseIcon width={20} height={20} />
        </Button>
      </div>
      {/* In the flow of the dialog, which is bounded by the visible area: the list scrolls inside it, above the keyboard. */}
      <SearchResults search={search} className="min-h-0 flex-1 overflow-y-auto overscroll-contain border-t border-line p-1" />
    </>
  );
}

/**
 * Below 1024 px the search is a magnifier in the top bar that opens this dialog (#320). The dialog sits at the top of the
 * visible area (not of the screen), so with the on-screen keyboard open the field, the first result and the close button
 * stay in sight.
 */
export function SearchDialog({ isOpen, onOpenChange }: { isOpen: boolean; onOpenChange: (open: boolean) => void }) {
  const { t } = useLingui();
  const backdrop = useBackdropClose(isOpen, () => onOpenChange(false));
  return (
    <DialogTrigger isOpen={isOpen} onOpenChange={onOpenChange}>
      <Button aria-label={t`Search`} className={`${ICON_BUTTON} ml-auto`}>
        <SearchIcon />
      </Button>
      <ModalOverlay
        ref={backdrop}
        // The dim area is handled by useBackdropClose; React Aria's own outside press would close the dialog a second time.
        isDismissable={false}
        className="fixed inset-x-0 top-(--vv-top) z-50 h-(--vvh) bg-ink/40 data-[entering]:animate-[fadein_150ms_ease-out] motion-reduce:data-[entering]:animate-none"
      >
        <Modal className="mx-4 mt-[max(0.75rem,env(safe-area-inset-top))] flex max-h-[calc(100%-1.5rem)] flex-col rounded-r3 border border-line bg-surface shadow-lg">
          <Dialog aria-label={t`Search`} className="flex min-h-0 flex-col outline-none">
            <SearchPanel close={() => onOpenChange(false)} />
          </Dialog>
        </Modal>
      </ModalOverlay>
    </DialogTrigger>
  );
}
