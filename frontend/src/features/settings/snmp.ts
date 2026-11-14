// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

/**
 * SNMP status discovery in the printer form (#296).
 *
 * The community is write-only: the hub reports `community_set`, never the value. The field is never
 * filled; an empty field keeps the stored community while host and port stay the same.
 */

export type SnmpProblem = "community_required" | "community_too_long";

/** The longest community the hub accepts. */
export const SNMP_COMMUNITY_MAX = 64;

/** Which drivers read their status over SNMP; a page printer (IPP) reports its own. */
export const supportsDiscovery = (backend: string): boolean => backend === "ptouch" || backend === "brother_ql";

/** What the form sends for the `snmp` part of the connection, or why it cannot be sent. */
export function snmpPayload(
  storedSet: boolean,
  draft: { discover: boolean; community: string },
): { snmp: { discover: boolean; community?: string } } | { problem: SnmpProblem } {
  // A paste from a password manager often carries a blank or a newline; a field of blanks is "not entered". Inner spaces stay.
  const community = draft.community.trim();
  if (community.length > SNMP_COMMUNITY_MAX) return { problem: "community_too_long" };
  if (community === "") {
    if (draft.discover && !storedSet) return { problem: "community_required" };
    // No `community` key at all: the hub keeps the stored one (`public` for a new printer).
    return { snmp: { discover: draft.discover } };
  }
  return { snmp: { discover: draft.discover, community } };
}

/**
 * Did the SNMP target change? The hub sends a stored community only to the host and port it was stored for, so a
 * changed target needs the community typed again (R-296-5a). This is a hint before submit; the hub decides, with
 * a slightly smarter comparison (an IP address by value), and answers 422 `snmp_community_required` when it disagrees.
 */
export function targetChanged(stored: { host?: string; port?: number }, host: string, port: string): boolean {
  return host.trim().toLowerCase() !== (stored.host ?? "").trim().toLowerCase() || Number(port) !== (stored.port ?? 9100);
}

/** The state the hub reports for a stored connection. */
export function storedSnmp(connection: { snmp?: unknown }): { discover: boolean; communitySet: boolean } {
  const snmp = (connection.snmp ?? {}) as { discover?: unknown; community_set?: unknown };
  return { discover: snmp.discover === true, communitySet: snmp.community_set === true };
}
