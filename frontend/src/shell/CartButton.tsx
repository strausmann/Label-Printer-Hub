// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { plural } from "@lingui/core/macro";
import { useLingui } from "@lingui/react/macro";
import { Link } from "@tanstack/react-router";
import { useCart } from "../features/lookup/cart";
import { CartIcon } from "./icons";

/** The badge text for a number of cart entries: nothing for an empty cart, "99+" above 99. */
export function cartBadge(entries: number): string | null {
  if (entries <= 0) return null;
  return entries > 99 ? "99+" : String(entries);
}

/**
 * The permanent cart icon of the top bar (#316). The count is the number of entries, the rows of the cart page, never
 * the sum of copies. The badge sits inside the 44 px target, so it cannot reach a neighbouring control at any width.
 */
export function CartButton() {
  const { t } = useLingui();
  const { items } = useCart();
  const entries = items.length;
  const badge = cartBadge(entries);
  const name =
    entries === 0
      ? t`Cart, empty`
      : plural(entries, { one: "Cart, # item", other: "Cart, # items" });

  return (
    <Link
      to="/cart"
      aria-label={name}
      className="press relative flex size-11 shrink-0 items-center justify-center rounded-r2 text-ink-2 transition-colors duration-150 hover:bg-sunken hover:text-ink focus-visible:outline-3 focus-visible:outline-offset-1 focus-visible:outline-link"
    >
      <CartIcon />
      {badge !== null && (
        <span
          aria-hidden="true"
          data-testid="cart-badge"
          className="pointer-events-none absolute right-0.5 top-0.5 flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-accent px-1 text-[11px] font-bold leading-none tabular-nums text-accent-ink"
        >
          {badge}
        </span>
      )}
    </Link>
  );
}
