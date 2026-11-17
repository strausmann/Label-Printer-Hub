// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

/**
 * How a tray takes paper (#350): `print_side` is the face that gets printed as the sheet lies in
 * the tray, `leading_edge` the edge of the printed image that lands at the sheet edge put in first.
 */
export type TrayLoading = { print_side: "up" | "down"; leading_edge: "top" | "bottom" };

/**
 * The answers of the guided test. The person marks a cross on the face-up side next to the edge
 * that goes in first, then prints the test page: the print on the crossed side means the tray
 * prints face up; "TOP" next to the cross means the image's top edge leads.
 */
export function loadingFromAnswers(printedOnCrossedSide: boolean, topNextToCross: boolean): TrayLoading {
  return { print_side: printedOnCrossedSide ? "up" : "down", leading_edge: topNextToCross ? "top" : "bottom" };
}

/**
 * What the person does to print on the back: the liner faces the side the tray prints on, and
 * the top edge always goes in first (the hub turns the page when the tray leads with the bottom).
 */
export function backSideInstruction(loading: TrayLoading): { linerSide: "up" | "down"; edgeFirst: "top" } {
  return { linerSide: loading.print_side, edgeFirst: "top" };
}
