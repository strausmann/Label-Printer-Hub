#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pre-generates the QR codes drawn on the paper mockups (M3, M9) into qr-data.json.

The codes are real: segno encodes the LYC1 payloads of spec section 7.2 in alphanumeric mode at the pinned
versions (page codes 5-M, cell codes 1-M). Needs `pip install segno`. The build (build.mjs) only reads the JSON.
Payload values are invented demo values.
"""
import json
import segno

RUN_BY_PASS = {1: 12, 2: 13, 3: 14}
CELLS = 65  # Avery Zweckform 6121: 5 columns x 13 rows


def path(payload: str, version: int) -> dict:
    q = segno.make(payload, error="m", version=version, mode="alphanumeric", micro=False)
    rows = []
    for y, row in enumerate(q.matrix):
        x = 0
        while x < len(row):
            if row[x]:
                start = x
                while x < len(row) and row[x]:
                    x += 1
                rows.append(f"M{start} {y}h{x - start}v1h-{x - start}z")
            else:
                x += 1
    return {"n": len(q.matrix), "d": "".join(rows)}


out: dict[str, dict] = {}
for k, run in RUN_BY_PASS.items():
    for cell in range(1, CELLS + 1):
        p = f"LYC1:{run}:{cell}:K{k}"
        out[p] = path(p, 1)
    corr = "41:-66:120:-80:21000"
    page = f"LYC1:{run}:0:A6121:1:{corr}:K{k}"
    out[page] = path(page, 5)
# the longest page payload of section 7.2, drawn in the zoom of M3
longest = "LYC1:999999:0:AAAAAAAAAA:1000000:-1000:-1000:-50000:-50000:-2000000:K99:PX100000:PY100000:MT100000:ML100000"
out[longest] = path(longest, 5)
for forbidden in ("@", "://", "mailto:", "tel:", "sms:", "WIFI:", "geo:", "BEGIN:"):
    assert not any(forbidden in key for key in out), forbidden
json.dump(out, open("qr-data.json", "w"), separators=(",", ":"))
print(len(out), "codes")
