# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The geometry of the mini scale at a crossing of the calibration page.

One place for the numbers: the printed page draws from them, ``GET /api/v1/info`` hands them to the
app, and the app's schematic draws to the same scale. A colour laser fills in a hairline gap, so the
white between two ticks has a floor (``MIN_GAP_MM``) that a test holds the pitch against.
"""

from __future__ import annotations

#: The scale reaches this far to each side of the crossing.
HALF_MM = 2.0
#: Distance between two ticks. Readers interpolate between ticks, so 0.5 mm still reads to ~0.1 mm.
STEP_MM = 0.5
#: Stroke width of every line on the page.
LINE_MM = 0.1
#: Tick lengths, across the scale: a half millimetre, a whole millimetre, the centre (the longest).
TICK_HALF_MM = 0.8
TICK_WHOLE_MM = 1.4
TICK_CENTRE_MM = 2.0
#: The least white between two ticks that survives a colour laser.
MIN_GAP_MM = 0.3
