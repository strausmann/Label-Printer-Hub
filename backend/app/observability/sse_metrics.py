# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Prometheus metrics shared by the SSE streams."""

from __future__ import annotations

from prometheus_client import Counter, Gauge

sse_connections_total = Counter(
    "printer_hub_sse_connections_total",
    "Total SSE connections opened",
    ["printer_id"],
)

sse_events_published_total = Counter(
    "printer_hub_sse_events_published_total",
    # Inkrementiert pro SSE-Subscriber, nicht pro publish()-Call: ein
    # publish() mit N aktiven Clients erhoeht den Counter um N. Der
    # Metric-Name ist aus historischen Gruenden behalten (Grafana-
    # Dashboards) — semantisch ist es "delivered to subscriber",
    # nicht "published once" (siehe Audit #67 Hinweis).
    "Total SSE events delivered to subscribers (one increment per subscriber per publish)",
    ["channel"],
)

sse_events_dropped_total = Counter(
    "printer_hub_sse_events_dropped_total",
    "Total events dropped due to slow subscribers",
    ["channel", "subscriber_id"],
)

sse_active_subscribers = Gauge(
    "printer_hub_sse_active_subscribers",
    "Current number of active SSE subscribers",
)
