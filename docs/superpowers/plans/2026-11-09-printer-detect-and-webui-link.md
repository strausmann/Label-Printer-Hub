# Printer Detection from an Address and the Device Web Interface Link — Implementation Plan (1.6.0)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Release 1.6.0, in which an admin types only an address and the hub detects protocol, model and connection (#232). It also warns persistently when the protocol a printer's status depends on does not answer (#232). Admins get a button that opens the device's own web interface (#233).

**Architecture:**
- **#232 detection.** A read-only detector under `app/services/detection/` probes in parallel under one deadline: SNMP v2c, then v1; IPP path walk on 631, then ipps; TCP 9100; HTTP 80 and 443. It reuses the existing IPP probe (`probe_ipp`), the shared SNMP helper and the 1.5.0 identity normaliser (`pick_identity`). A pure ranking function turns the raw results into candidates and warning codes. A new admin route exposes it, and the add-printer form prefills from a chosen candidate.
- **SNMP version.** The SNMP helper gets one `snmp_get` primitive with a `version` parameter. It also handles SNMPv1 `noSuchName` correctly. Every SNMP call (producer, preflight, PJL discovery) takes the version stored in the tape connection.
- **#232 hint.** `PrinterStatus` reports which protocol the status depends on and whether it is missing or silent. The printer page renders a persistent hint from that.
- **#233.** A nullable `printers.web_ui_url` override and a pure `effective_web_ui_url(printer)`. The public `PrinterRead` carries the URL **only** for admin callers. The UI renders a link button only when the field is present.

**Tech Stack:** FastAPI / Starlette, SQLModel/SQLite, Alembic, pysnmp 7 asyncio API, httpx, asyncio, pytest; React + Vite + vitest + Playwright, lingui.

**Spec:** the issues, with comments:
- #232 https://github.com/strausmann/Label-Printer-Hub/issues/232 (incl. the 2026-11-09 correction: the HP answers SNMP **v1** only; try v2c, then v1; store the version that answered)
- #233 https://github.com/strausmann/Label-Printer-Hub/issues/233

Maintainer rulings of 2026-11-09 (binding):
- #232:
  - the detect endpoint is admin only and read-only on the device;
  - overall bound ≤ 10 s, probes in parallel;
  - it returns ranked candidates, a status per protocol, and warnings in de/en;
  - a persistent hint shows when the status protocol does not answer: SNMP for tape printers, IPP for page printers, and no SNMP warning for page printers;
  - a "Detect" button prefills the add form;
  - mDNS only if reachable from the container and cheap.
- #233:
  - the button sits on the overview and on the detail page, admin only;
  - the URL is derived from the host, with an optional `web_ui_url` override (`http`/`https`, no user info, ≤ 2048) that detection can prefill;
  - no host or URL reaches non-admin responses, and a test asserts it.
- **Non-goal:** storing device web-UI credentials in the hub.

---

## Preconditions on 1.5.0

This branch starts from `main` **after** the 1.5.0 merge. Plan of record: `docs/superpowers/plans/2026-11-09-api-v1-live-printers-manifest.md` on `feat/api-v1-status-manifest` (`3a6f41f` or later).

**Step 0 of the implementation:**

```bash
git fetch origin && git switch -c feat/printer-detect-webui origin/main
```

Then confirm that `git log origin/main --oneline | grep -E "chore\(release\): 1\.5\.0"` prints a line. If 1.5.0 is not merged, stop and report it. Do not build on the 1.5.0 branch.

This plan consumes these 1.5.0 interfaces, by their 1.5.0 names. Before Task 1, check each one exists with the stated signature (`grep -n`). A difference is reported, not patched around.

| From 1.5.0 | Exact interface | Used in |
|---|---|---|
| Task 2 (#226) | every route under `/api/v1/`; `ALLOWED_UNVERSIONED`; guard `tests/integration/api/test_route_versioning.py`; `tests/helpers/routes.py::iter_routes` | Tasks 5, 8; the guard must stay green |
| Task 6 (#224) | `app/services/printer_runtime.py`: `class PrinterRuntime` with `attach(printer, *, fatal=False)`, `detach(printer_id)`, `reconcile(printer_id)`, `is_polled(printer_id) -> bool`; module function `wiring_key(printer) -> tuple[object, ...]` containing the "snmp settings"; `app.state.printer_runtime`; the back-compat fields `app.state.printer_snmp_community` etc. | Task 1 (version flows through wiring), Task 6 |
| Task 7 (#224) | admin create/update/enable/disable call `printer_runtime.reconcile` before `hub.printers_changed` | Tasks 1, 8 (a changed `snmp.version` or `web_ui_url` takes effect live) |
| Task 8 (#227) | `app/services/status_freshness.py`: `stale_after_s(probe_interval_s) -> float`, `is_stale(updated_at, now, probe_interval_s) -> bool`; `PrinterStatus.stale: bool`, `PrinterStatus.polled: bool`; the stale/unpolled mask in `get_printer_status` | Task 6 |
| Task 12/13 (#228) | `POST /api/v1/printers/{printer_id}/test-print`; `TestPrintButton` | Rollout acceptance only (no code dependency) |
| Task 14 (#231) | `app/services/hardware_identity.py`: `HardwareIdentity(kind, value)`, `pick_identity(serial, ipp_uuid, mac) -> HardwareIdentity \| None` with its normalisation; `PreflightStatus.serial`, `PreflightStatus.mac`; `query_preflight` reading `prtGeneralSerialNumber.1` and `ifPhysAddress.1` in the same round trip; `"printer-uuid"` in `PRINTER_ATTRS`; `IppStatusRecord.printer_uuid`; migration head `20261109b1` | Tasks 1, 3, 4 |
| Task 16 (#231) | public `PrinterRead` (`app/schemas/printer.py`) fills `hardware_id*` only for `admin` callers | Task 8 uses the same filling place for `web_ui_url` |

Not duplicated here: route versioning, live wiring, freshness, hardware identity capture, and the test print.

## Global Constraints

- **Repo rules.** Public repo: English identifiers, comments and commits; Conventional Commits; no AI attribution; never `git add -A`. Stage explicit paths and read `git status --short` before each commit. No private network artefacts in code, tests, docs or commits; tests use `192.0.2.0/24` and `*.example.invalid` (`docs/policies/privacy.md`).
- **ADR 0004.** Model-specific facts live in `app/printer_models/<series>.py` only (Task 3 adds `backend` there, not a map in the detector).
- **Release.** 1.6.0, via `feat`/`fix` commits; no `BREAKING CHANGE:` footer, no `!`.
- **Routes.** New routes live under `/api/v1/`; the 1.5.0 versioning guard and `test_route_auth_coverage_guardrail.py` stay green without allow-list changes.
- **Tests.** Every regression test goes red against the unfixed code. Each task names its counter-test. Run it once and record the result in the task report.
- **Backend checks.** `ruff check .`, `ruff format --check .`, `mypy app/` (strict), `pytest -m "not slow" --cov=app --cov-fail-under=80` (gate only; per directory otherwise).
- **Frontend checks.** `pnpm typecheck`, `pnpm lint`, `pnpm test:coverage`, `pnpm build`, `pnpm e2e` (per spec).
- **Generated schema.** `frontend/src/api/schema.gen.ts` changes only via `pnpm gen:api`.
- **i18n.** Every new string goes in both `frontend/src/i18n/locales/{en,de}/messages.po`; German uses real umlauts. Copy pinned in this plan is used verbatim.
- **UI task protocol (Tasks 7, 9).** Before writing UI code, load `taste-skill:design-taste-frontend`, `emil-design-eng`, `mobile-native` and `break-ui`. At the end, run `impeccable:impeccable` on the changed screens. Take Playwright screenshots in light and dark, at 1280 px and 390 px, with the `SHOTS` pattern (`frontend/e2e/shell.spec.ts`). They are artifacts, not a gate.
- **Agent limits.** Each command runs under 170 s; no full suite outside the gate.
- **Outbound probe bounds (SSRF, binding for Tasks 2–5):**
  - fixed ports and schemes only: UDP 161 SNMP get, `ipp://…:631`, `ipps://…:631`, TCP 9100 connect, `http://…:80/`, `https://…:443/`;
  - no redirects followed;
  - `trust_env=False`;
  - no request body except the IPP Get-Printer-Attributes request;
  - IPP responses capped by the existing 1 MB client cap;
  - HTTP bodies never read;
  - connection targets are the validated resolved address, never a re-resolved name;
  - loopback, link-local, multicast, unspecified and reserved addresses are refused, including IPv4-mapped IPv6;
  - the host never appears in logs above debug.

## Review Focus

1. **A device that answers SNMP v1 only, like the HP CP1525N.** v2c times out, v1 answers. The result says `version: "v1"` and the whole run still ends inside the bound (Task 3 `test_v1_only_device_detected_with_version_v1`, Task 5 `test_v1_fallback_fits_in_deadline`).
2. **An IPP device that answers a non-IPP 404/HTML on one path and IPP on another.** The walk continues past non-IPP answers and stops at a connect failure, so a dead port is not tried four times (Task 4 `test_ipp_path_walk_skips_non_ipp_answers`, `test_ipp_path_walk_stops_on_unreachable`).
3. **A host that points at the hub itself or at cloud metadata** (`localhost`, `127.0.0.1`, `169.254.169.254`, `::ffff:127.0.0.1`, a name that resolves to loopback). The result is 422 and no probe is sent (Task 2 `test_blocked_addresses_rejected_without_probe`).
4. **A slow device whose answers arrive after the deadline.** The response comes back at the deadline; late probes are reported `not_reachable` with reason `deadline`; no task stays running (Task 5 `test_deadline_cancels_pending_probes`).
5. **A v1 tape printer whose agent lacks one OID** (no serial, no media OID). The status probe still succeeds; SNMPv1 `noSuchName` must not mark the printer offline (Task 1 `test_v1_missing_oid_does_not_fail_preflight`).

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/printer_backends/snmp_helper.py` (modify) | `SnmpVersion`, `snmp_get` primitive; every `query_*` takes `version` |
| `backend/app/schemas/printer_admin.py` (modify) | `SNMPConfig.version`; `web_ui_url` on create/update payloads; `validate_web_ui_url` |
| `backend/app/services/backend_router.py`, `printer_runtime.py`, `producers/status_probe_producer.py`, `ptouch_backend.py`, `brother_ql_backend.py` (modify) | carry `snmp.version` (and the configured community) to every SNMP call |
| `backend/app/printer_models/base.py`, `pt.py`, `ql.py`, `registry.py` (modify) | `backend` per driver; `ModelRegistry.match_device(descr, pjl)` |
| `backend/app/services/detection/__init__.py` | re-exports `detect_printer`, `DetectDeps` |
| `backend/app/services/detection/target.py` | host validation, resolution, address block list |
| `backend/app/services/detection/net_probes.py` | TCP 9100, HTTP 80/443 probes |
| `backend/app/services/detection/snmp_probe.py` | device reader, v2c then v1 |
| `backend/app/services/detection/ipp_probe.py` | IPP path walk + ipps |
| `backend/app/services/detection/ranking.py` | pure: raw results → candidates, capabilities, warnings |
| `backend/app/services/detection/detector.py` | orchestration under the deadline, concurrency limit |
| `backend/app/schemas/printer_detect.py` | request/response models |
| `backend/app/services/web_ui.py` | `effective_web_ui_url` |
| `backend/alembic/versions/2026_11_10_0001-20261110a1_printer_web_ui_url.py` | additive column |
| `backend/tests/helpers/fake_snmp_agent.py` | scriptable SNMP agent patched over `get_cmd` |
| `frontend/src/features/settings/{DetectPanel,SnmpFields}.tsx`, `detect.ts` | detect UI, SNMP fields, pure prefill + warning text |
| `frontend/src/features/printers/{StatusSourceHint,WebUiLink}.tsx` | persistent hint, web UI button |

---

## Task 1: SNMP version in the shared SNMP layer and the wiring

**Files:**
- Modify: `backend/app/printer_backends/snmp_helper.py`; `backend/app/schemas/printer_admin.py` (`SNMPConfig`); `backend/app/services/backend_router.py` (`SNMPConfig`); the 1.5.0 home of `_db_printers_to_configs` / `_resolve_model_id_from_config` (`printer_runtime.py`); `backend/app/services/producers/status_probe_producer.py`; `backend/app/printer_backends/ptouch_backend.py`, `brother_ql_backend.py`; `backend/app/api/routes/print.py` (live block, `printer_snmp_community`).
- Create: `backend/tests/helpers/fake_snmp_agent.py`
- Test: `backend/tests/unit/printer_backends/test_snmp_get.py`, `backend/tests/unit/services/test_snmp_version_wiring.py`

**Interfaces (produces):**
- `SnmpVersion = Literal["v1", "v2c"]`; `_MP_MODEL: dict[SnmpVersion, int] = {"v1": 0, "v2c": 1}`.
- `async snmp_get(host: str, oids: Sequence[str], *, community: str, version: SnmpVersion, timeout_s: float) -> dict[str, object | None]`. Missing OIDs come back as `None`, never as an exception.
  - **v2c:** per-varbind `noSuchObject`/`noSuchInstance`/`endOfMibView` → `None`.
  - **v1:** `error_status == 2` (`noSuchName`) with `error_index` k: the OID at k-1 is set to `None`, then the request is retried without it, at most `len(oids)` rounds.
  - Transport failure or any other error status raises `SnmpQueryError`.
- `query_preflight`, `query_loaded_tape_mm`, `query_model_pjl`, `query_live_status` keep their signatures. Each gains `version: SnmpVersion = "v2c"` and calls `snmp_get`. `query_preflight` keeps the 1.5.0 serial/MAC fields.
- `SNMPConfig.version: SnmpVersion = "v2c"` in both schemas. A stored connection without the key reads as `"v2c"`, so no data migration is needed: `connection` is a JSON column, which is why no DB migration is needed either.
- `StatusProbeProducer(..., snmp_version: SnmpVersion = "v2c")`.
- `PTouchBackend` and `BrotherQLBackend` get `__init__(..., snmp_community: str = "public", snmp_version: SnmpVersion = "v2c")`. `preflight_check()` defaults to them.
  - Today every `preflight_check()` caller (`print_service.py:68,153`, `ptouch_backend.py:274,325`) silently uses `"public"`; that is a pre-existing defect, fixed here because a v1 printer would otherwise fail every preflight.
- `app.state.printer_snmp_version` next to `printer_snmp_community`, recomputed where 1.5.0 recomputes the back-compat fields.
- `wiring_key` already contains "snmp settings"; check that `version` is inside it. If 1.5.0 encoded only `discover`/`community`, add `version`.

`fake_snmp_agent.py`:
- `FakeSnmpAgent(versions: set[SnmpVersion], values: dict[str, object], community: str = "public", delay_s: float = 0.0)`.
- `install(monkeypatch)` patches `app.printer_backends.snmp_helper.get_cmd` and `UdpTransportTarget.create`.
- It answers v1 like a real v1 agent: on the first missing OID it returns `noSuchName` with that index.
- It records `requests: list[tuple[SnmpVersion, list[str]]]`.
- A wrong community or version gets an `error_indication` (timeout).

- [ ] **Step 1: Failing tests:**
  - `test_snmp_get_v2c_missing_oid_is_none`: agent v2c lacks the serial OID. The result has `None` for it and the values for the others, in one request.
  - `test_snmp_get_v1_nosuchname_drops_and_retries`: agent v1 lacks OIDs 2 and 4 of 5. The result has the three values and two `None`s. `len(agent.requests) == 3`, and each retry omits the dropped OIDs.
  - `test_snmp_get_v1_uses_mpmodel_0`: the agent sees `mpModel == 0` for `version="v1"` and `1` for `"v2c"`.
  - `test_v1_missing_oid_does_not_fail_preflight` (Review Focus 5): v1 agent without the serial/MAC and media OIDs. `query_preflight(..., version="v1")` returns a status with `serial is None` and `loaded_tape_mm is None`, and does not raise.
  - `test_snmp_config_version_defaults_to_v2c` and `test_snmp_config_rejects_v3` (`"v3"` → `ValidationError`).
  - `test_stored_connection_without_version_wires_v2c`: row `connection.snmp = {discover: True, community: "public"}`. The producer the runtime builds has `snmp_version == "v2c"`.
  - `test_v1_tape_printer_probes_with_v1`: row with `version: "v1"`. After `attach`, the agent records only v1 requests.
  - `test_preflight_uses_configured_community`: backend built with `snmp_community="s3cr3t"`. `preflight_check()` reaches the agent with `"s3cr3t"`.
  - `test_version_change_rewires`: `PUT` with `snmp.version: "v1"` on a running v2c printer. Later probes are v1, because `wiring_key` differs.
  - Counter-tests:
    - `snmp_get` that treats v1 `noSuchName` as a failure → `test_v1_missing_oid_does_not_fail_preflight` red;
    - `preflight_check()` without the stored community → `test_preflight_uses_configured_community` red.
- [ ] **Step 2: Run** `pytest tests/unit/printer_backends/test_snmp_get.py tests/unit/services/test_snmp_version_wiring.py -v`. Expected: FAIL (`snmp_get`, `version` missing).
- [ ] **Step 3: Implement.** All existing `query_*` tests that patch `get_cmd` stay green; adjust only the patch targets if they move.
- [ ] **Step 4: Verify:** `pytest tests/unit/printer_backends tests/unit/services`, `pytest tests/integration -m "not slow"` per directory; ruff; mypy.
- [ ] **Step 5: Commit** `feat(printers): store and use the SNMP version per tape printer, v1 or v2c (#232)`.

## Task 2: Detection target guard and network probes

**Files:**
- Create: `backend/app/services/detection/target.py`, `backend/app/services/detection/net_probes.py`, `backend/app/services/detection/__init__.py`
- Test: `backend/tests/unit/services/detection/test_target.py`, `backend/tests/unit/services/detection/test_net_probes.py`

**Interfaces (produces):**
- `validate_host(raw: str) -> str`.
  - Accepts: an IPv4 literal, a bare IPv6 literal (no brackets), or a DNS name (labels `[A-Za-z0-9-]{1,63}`, not starting or ending with `-`, dot-separated, total ≤ 253).
  - Rejects: a scheme, `/`, `@`, `:` on a non-IPv6 value (a port), whitespace, control characters. Each rejection raises `ValueError` with a fixed message per rule that never contains the value.
- `async resolve_target(host: str, *, resolver: Resolver, timeout_s: float) -> IPv4Address | IPv6Address`.
  - `Resolver = Callable[[str], Awaitable[list[str]]]`; the default is `loop.getaddrinfo(host, None, type=SOCK_STREAM)`.
  - Every resolved address is checked. If any one is blocked, it raises `TargetNotAllowedError`, so a name with one public and one loopback record is refused.
  - It returns the first address.
  - Unresolvable or timed out → `TargetUnresolvableError`.
- `is_blocked(addr) -> bool`: `is_loopback or is_link_local or is_multicast or is_unspecified or is_reserved`, evaluated on `addr.ipv4_mapped` when present. Private ranges are allowed, because printers live there.
- `ProbeState = Literal["reachable", "not_reachable", "not_tried"]`; `ProbeReason = Literal["timeout", "refused", "unreachable", "invalid_response", "tls_failed", "deadline", "not_needed"]`; `@dataclass(frozen=True) class ProbeOutcome(state: ProbeState, reason: ProbeReason | None = None)`.
- `async probe_tcp(address: str, port: int, *, timeout_s: float, opener: TcpOpener) -> ProbeOutcome`. `TcpOpener` defaults to `asyncio.open_connection`. It connects and closes the writer at once, writing **no** bytes.
- `@dataclass(frozen=True) class HttpOutcome(outcome: ProbeOutcome, redirects_to_https: bool)`.
- `async probe_http(address: str, host_header: str, scheme: Literal["http", "https"], *, timeout_s: float, transport: httpx.AsyncBaseTransport | None) -> HttpOutcome`.
  - It sends `GET /` to `{scheme}://{address-literal}/` with `Host: host_header`, through `httpx.AsyncClient(follow_redirects=False, trust_env=False, verify=False, timeout=timeout_s)`.
  - It opens with `client.stream` and closes without reading the body.
  - Any HTTP status counts as `reachable`.
  - `redirects_to_https` is true when the status is 301/302/307/308 and the `Location` parses to `https` with the same host (compared lower-case against `host_header` or the address).
  - `verify=False` is safe here because nothing is sent and only the status line is used. Comment that next to the call.

- [ ] **Step 1: Failing tests:**
  - `test_validate_host_accepts`: `"192.0.2.10"`, `"2001:db8::10"`, `"printer-1.example.invalid"`.
  - `test_validate_host_rejects`: `"http://x"`, `"x:9100"`, `"a@b"`, `"x/y"`, `" x"`, `"x\n"`, `"-x"`, 254 characters. The message never contains the input.
  - `test_blocked_addresses`: `127.0.0.1`, `::1`, `169.254.169.254`, `fe80::1`, `224.0.0.1`, `0.0.0.0`, `240.0.0.1`, `::ffff:127.0.0.1` are blocked; `192.0.2.10`, `2001:db8::10`, `fd00::5` and an RFC 1918 address are not. Build the RFC 1918 address as `ipaddress.IPv4Address((10 << 24) + 5)`, because the CI privacy scan rejects private IPv4 literals.
  - `test_name_with_one_blocked_record_is_refused`: the resolver returns `["192.0.2.10", "127.0.0.1"]` → `TargetNotAllowedError`.
  - `test_unresolvable_host`: the resolver raises `OSError` → `TargetUnresolvableError`; a resolver that sleeps 5 s with `timeout_s=0.1` raises the same.
  - `test_tcp_probe_open_sends_nothing`: a fake opener records writes. Result `reachable` and `writes == []`.
  - `test_tcp_probe_refused_and_timeout`: `ConnectionRefusedError` → `not_reachable/refused`; a sleeping opener → `not_reachable/timeout`.
  - `test_http_probe_does_not_follow_redirect`: `httpx.MockTransport` answers 302 `Location: https://printer-1.example.invalid/`. Exactly one request, `reachable`, `redirects_to_https is True`.
  - `test_http_probe_redirect_to_other_host_is_not_https_hint`: `Location: https://other.example.invalid/` → `redirects_to_https is False`.
  - `test_http_probe_uses_get_only_and_reads_no_body`: the mock records the method `GET`; a body generator that raises if iterated is never iterated.
  - Counter-test: a `probe_http` with `follow_redirects=True` → `test_http_probe_does_not_follow_redirect` red (two requests).
- [ ] **Step 2: Run** `pytest tests/unit/services/detection -v`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Verify** the same, plus ruff and mypy.
- [ ] **Step 5: Commit** `feat(printers): bounded target guard and network probes for printer detection (#232)`.

## Task 3: SNMP device reader, v2c then v1, and the model match

**Files:**
- Create: `backend/app/services/detection/snmp_probe.py`
- Modify: `backend/app/printer_models/base.py` (Protocol attribute), `pt.py` (`backend = "ptouch"`), `ql.py` (`backend = "brother_ql"`), `registry.py` (`match_device`); `register` validates that `backend` is a non-empty string.
- Test: `backend/tests/unit/services/detection/test_snmp_probe.py`, `backend/tests/unit/printer_models/test_registry_match_device.py`

**Interfaces:**
- Consumes: `snmp_get`, `SnmpVersion` (Task 1); `pick_identity` (1.5.0); `parse_loaded_tape_mm`; `BROTHER_PJL_OID`.
- Produces:
  - `PrinterModel.backend: str` (ClassVar on the drivers).
  - `ModelRegistry.match_device(device_descr: str | None, pjl: str | None) -> type[PrinterModel] | None`: first `find_by_snmp_oid_value(device_descr)`, then `find_by_pjl(pjl)`. `ModelNotFoundError` → `None`. It calls `ensure_discovered()` first.
  - `DEVICE_OIDS` (pinned):

    | OID | Name |
    |---|---|
    | `1.3.6.1.2.1.1.1.0` | sysDescr |
    | `1.3.6.1.2.1.25.3.2.1.3.1` | hrDeviceDescr.1 |
    | `1.3.6.1.2.1.43.5.1.1.17.1` | prtGeneralSerialNumber.1 |
    | `1.3.6.1.2.1.2.2.1.6.1` | ifPhysAddress.1 |
    | `1.3.6.1.2.1.2.2.1.6.2` | ifPhysAddress.2 |
    | `1.3.6.1.2.1.43.8.2.1.13.1.1` | prtInputMediaName.1.1 |
    | `BROTHER_PJL_OID` | Brother PJL |

  - `@dataclass(frozen=True) class SnmpDevice(version: SnmpVersion, sys_descr: str | None, device_descr: str | None, serial: str | None, mac: str | None, media_name: str | None, pjl: str | None)`.
  - Text fields go through `sanitise_text(..., max_len=120)`. If the value is longer than the sanitiser accepts, it is cut to 120 first (the sanitiser raises on input over its factor). An empty value becomes `None`.
  - `mac` = the first non-zero of `ifPhysAddress.1`, `.2`, normalised like `pick_identity` (lower-case `aa:bb:…`).
  - `async read_snmp_device(address: str, *, community: str, timeout_s: float) -> tuple[SnmpDevice | None, ProbeOutcome]`.
    - It tries v2c with the full `DEVICE_OIDS` in one `snmp_get`. On `SnmpQueryError` it tries v1.
    - Both fail → `(None, not_reachable/timeout)`.
    - The first success wins; v1 is not tried after a v2c success.
    - A success where every value is `None` counts as an answer, because the agent spoke.

- [ ] **Step 1: Failing tests** (with `FakeSnmpAgent`):
  - `test_brother_pt_detected_v2c`: agent v2c with `hrDeviceDescr = "Brother PT-P750W"`, serial, MAC bytes, `prtInputMediaName = '12mm(0.47")'`. Result: `version == "v2c"`, `device_descr` contains `PT-P750W`, `media_name` set, one request. `match_device(...)` returns a class with `backend == "ptouch"` and `model_id == "PT-P750W"`.
  - `test_brother_ql_detected_v2c`: `"62mm / 2.4\""`, model `QL-820NWB`, so `backend == "brother_ql"`.
  - `test_v1_only_device_detected_with_version_v1` (Review Focus 1): agent `versions={"v1"}`, HP-like values, no media OID, no PJL OID, MAC only in `.2`. Result `version == "v1"`, `serial` set, `mac` from `.2`. The agent saw v2c attempts first, then v1. `match_device(...) is None`.
  - `test_no_snmp_answer`: agent with `versions=set()` → `(None, not_reachable)`.
  - `test_device_strings_are_sanitised_and_cut`: a `sysDescr` of 5000 characters with `\x1b[2J` → length ≤ 120, no control characters.
  - `test_wrong_community_is_no_answer`: the agent expects `"private"` → `None`.
  - `test_register_rejects_driver_without_backend`.
  - Counter-test: a reader that stops after v2c → `test_v1_only_device_detected_with_version_v1` red.
- [ ] **Step 2: Run** the two test files. Expected: FAIL.
- [ ] **Step 3: Implement.** Update the `snmp_model_oid_value_substr` docstring in `base.py`: it now also matches `hrDeviceDescr`.
- [ ] **Step 4: Verify** `pytest tests/unit/printer_models tests/unit/services/detection`; ruff; mypy.
- [ ] **Step 5: Commit** `feat(printers): read model, serial and media of a device over SNMP v2c or v1 (#232)`.

## Task 4: IPP path walk and ipps for detection

**Files:**
- Create: `backend/app/services/detection/ipp_probe.py`
- Modify: `backend/app/printer_backends/ipp/attributes.py` (`ProbeSummary.printer_uuid: str | None = None`, filled in `summarise` with the 1.5.0 uuid normalisation); `backend/tests/helpers/fake_ipp_printer.py` (`paths: set[str] | None = None`; any other path → HTTP 404 `text/html`; `printer_uuid: str | None`, only if 1.5.0 did not add it).
- Test: `backend/tests/unit/services/detection/test_ipp_probe.py`, plus one assertion in the existing `/ipp/probe` integration test that `printer_uuid` is in the summary.

**Interfaces:**
- Consumes: `probe_ipp(connection, *, queue_timeout_s, transport_factory, unreachable_status, log_name)` (`printer_admin_service.py:124`, unchanged); `IppConnection`; `IppTransportFactory`; the `app.sheets.errors` IPP errors.
- Produces:
  - `IPP_PATHS = ("/ipp/print", "/ipp/printer", "/ipp", "/")` (pinned order).
  - `@dataclass(frozen=True) class IppFound(scheme: Literal["ipp", "ipps"], path: str, summary: ProbeSummary)`.
  - `async probe_ipp_paths(address: str, *, attempt_timeout_s: int, transport_factory: IppTransportFactory | None) -> tuple[IppFound | None, ProbeOutcome, IppFound | None, ProbeOutcome]`. It returns `(ipp_found, ipp_outcome, ipps_found, ipps_outcome)`.
  - The walk, for each path in order:
    - it calls `probe_ipp(IppConnection(uri=f"ipp://{literal}:631{path}", tls_verify=True), queue_timeout_s=attempt_timeout_s, transport_factory=..., log_name="detect")`;
    - `IppUnreachableApiError` stops the walk with `not_reachable/unreachable`;
    - `IppRejectedError` and `IppBadResponseApiError` move to the next path;
    - all four rejected → `not_reachable/invalid_response`;
    - the first summary wins.
  - ipps: only after an ipp hit, one attempt at `ipps://{literal}:631{path}` with `tls_verify=True`. Success → `reachable`. Failure → `not_reachable/tls_failed`. With no ipp hit, ipps is `not_tried/not_needed`.
  - Candidates are never offered with `tls_verify=False`; the admin can still choose that by hand.
  - `{literal}` is the resolved address, bracketed for IPv6.

- [ ] **Step 1: Failing tests** (`FakeIppPrinter` behind `httpx.ASGITransport`, routed by `transport_factory`):
  - `test_ipp_detects_ipp_print_path`: fake with `paths={"/ipp/print"}` → `path == "/ipp/print"`, one Get-Printer-Attributes.
  - `test_ipp_detects_ipp_printer_path`: `paths={"/ipp/printer"}` → `path == "/ipp/printer"`; the fake saw `/ipp/print` (404) first.
  - `test_ipp_path_walk_skips_non_ipp_answers` (Review Focus 2): `paths={"/"}` → found at `/` after three 404s.
  - `test_ipp_path_walk_stops_on_unreachable`: the transport raises `httpx.ConnectError` → exactly one attempt, `not_reachable/unreachable`.
  - `test_ipps_tried_only_after_ipp_hit`; `test_ipps_tls_failure_reported` (the transport raises `ssl.SSLError` for `https` → `tls_failed`, and the ipp hit is kept).
  - `test_detect_ipp_is_read_only`: every `fake.received[*]` operation is Get-Printer-Attributes.
  - `test_probe_summary_has_printer_uuid`: the fake reports `urn:uuid:ABC…` → `summary.printer_uuid == "abc…"`.
  - Counter-test: a walk that stops at the first non-IPP answer → `test_ipp_detects_ipp_printer_path` red.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement;** `pnpm gen:api` (`ProbeSummary` changed).
- [ ] **Step 4: Verify** `pytest tests/unit/services/detection tests/integration/api/test_admin_printers_ipp.py`; ruff; mypy.
- [ ] **Step 5: Commit** `feat(printers): find the IPP path a printer answers on, and ipps when TLS verifies (#232)`.

## Task 5: Detector, ranking and the detect endpoint

**Files:**
- Create: `backend/app/services/detection/ranking.py`, `backend/app/services/detection/detector.py`, `backend/app/schemas/printer_detect.py`
- Modify: `backend/app/api/routes/admin_printers_api.py` (route registered **before** the `/{slug}` routes; docstring route list)
- Test: `backend/tests/unit/services/detection/test_ranking.py`, `backend/tests/integration/api/test_printer_detect_api.py`

**Interfaces:**

Schemas (`printer_detect.py`, all `extra="forbid"`):
- `DetectRequest {host: str (1..253, validate_host), snmp_community: str = "public" (1..64, printable ASCII)}`.
- `ProtocolStatus {state: ProbeState, reason: ProbeReason | None}`.
- `DetectProtocols {snmp: ProtocolStatus, ipp: ProtocolStatus, ipps: ProtocolStatus, raw: ProtocolStatus, http: ProtocolStatus, https: ProtocolStatus}`, plus `snmp_version: SnmpVersion | None`.
- `DetectDevice {make_and_model: str | None, model_id: str | None, identity_kind: Literal["serial", "ipp_uuid", "mac"] | None, identity: str | None, mac: str | None}`. This is admin only and inventory data.
- `DetectTapeConnection {host: str, port: int = 9100, snmp: {discover: bool, version: SnmpVersion}}`. It has **no community field**: the client keeps what it sent.
- `DetectCandidate`:
  - `{backend: Literal["ptouch", "brother_ql", "ipp"], model: str | None, connection: DetectTapeConnection | IppConnection, probe: ProbeSummary | None, web_ui_url: str | None, suggested_name: str, suggested_slug: str}`;
  - `connection` for IPP uses the host **as typed** (`ipp://{host}:631{path}`), not the resolved literal.
- `DetectCapabilities {raw_print: bool, ipp: bool, ipps: bool, web_ui: bool, tape_width_mm: int | None, trays: list[str], color: bool | None}`.
- `DetectWarningCode = Literal["snmp_not_answering", "raw_port_closed", "ipp_not_answering", "ipp_pdf_unsupported", "model_unknown", "nothing_answered"]`.
- `DetectResult {host: str, protocols: DetectProtocols, device: DetectDevice, candidates: list[DetectCandidate], capabilities: DetectCapabilities, warnings: list[DetectWarningCode]}`.

Ranking (pure):
- `rank(host: str, snmp: SnmpDevice | None, snmp_outcome: ProbeOutcome, model: type[PrinterModel] | None, ipp: IppFound | None, ipps: IppFound | None, raw: ProbeOutcome, http: HttpOutcome, https: HttpOutcome) -> tuple[list[DetectCandidate], DetectCapabilities, DetectDevice, list[DetectWarningCode]]`.
- Rank order (pinned):
  1. tape candidate (model matched, raw `reachable`);
  2. ipps candidate;
  3. ipp candidate;
  4. tape candidate with raw closed.
- An IPP summary with `pdf_supported == False` gives **no** candidate and the warning `ipp_pdf_unsupported`.
- Tape candidate `snmp.discover = True` and `version = snmp.version`. Without an SNMP answer there is no tape candidate, because no model is known.
- Warnings (pinned rules):
  - `snmp_not_answering` when SNMP is silent **and** the best candidate is not an IPP candidate. This covers no candidate at all, and raw 9100 open with no model. A page printer never gets an SNMP warning.
  - `raw_port_closed` when a tape model matched and raw is closed.
  - `ipp_not_answering` when there is no tape candidate and IPP is silent.
  - `model_unknown` when SNMP answered, `model is None`, and there is no IPP candidate.
  - `nothing_answered` when every protocol is `not_reachable`. In that case it is the only warning.
- `web_ui_url` on a candidate is `https://{host}/` when `http.redirects_to_https`, or when https is reachable and http is not. Otherwise it is `None`, because the derived `http://{host}/` needs no override.
- `device`: `identity` from `pick_identity(snmp.serial, ipp.summary.printer_uuid, snmp.mac)`; `make_and_model` = IPP make-and-model, else `device_descr`; `model_id` = matched `model_id`.
- `suggested_name`: `model_id`, else make-and-model, cut to 60. `suggested_slug`: lower-case it, map each run of non-`[a-z0-9]` to `-`, strip `-`, cut to 64, pad to 3 with `-1` if shorter. Uniqueness is left to the create route (409 as today).

Detector:
- `DETECT_DEADLINE_S = 8.5`, `RESOLVE_TIMEOUT_S = 1.0`, with `assert DETECT_DEADLINE_S + RESOLVE_TIMEOUT_S <= 10`. Per-probe timeouts: SNMP 2.0 s per version, IPP 2 s per attempt, TCP 2 s, HTTP 2.5 s.
- `@dataclass class DetectDeps(resolver: Resolver, tcp_opener: TcpOpener, http_transport: httpx.AsyncBaseTransport | None, ipp_transport_factory: IppTransportFactory | None)`; `default_deps()`. The SNMP seam is `get_cmd`, patched by `FakeSnmpAgent`.
- `async detect_printer(host: str, *, community: str, deps: DetectDeps, deadline_s: float = DETECT_DEADLINE_S) -> DetectResult`.
  - It resolves first, then runs the SNMP, IPP, TCP 9100, HTTP and HTTPS probes as tasks with `asyncio.wait(timeout=deadline_s)`.
  - It cancels and awaits the pending tasks. A cancelled probe → `not_reachable/deadline`.
  - Then it calls `match_device` and `rank`.
- Concurrency: module `asyncio.Semaphore(2)`. When the semaphore is full, the route answers 429 `{"error_code": "detect_busy"}` and does not queue.
- Logs: one info line `printer detect by %s: %d candidates, %d warnings` (`_audit_user`). The host appears only at debug. The community never appears.

Route:
- `POST /api/v1/admin/printers/detect`, `AdminAuthDep`, body `DetectRequest`, `200 DetectResult`.
- `422 invalid_host` (validation), `422 host_not_allowed`, `422 host_unresolvable`, `429 detect_busy`. Each error has fixed text without the host.
- Deps come from `app.state.detect_deps` (test injection, like `ipp_transport_factory`), else `default_deps()`, with `ipp_transport_factory` from `_ipp_transport_factory(request)`.

- [ ] **Step 1: Failing tests:**
  - Ranking table, `test_ranking.py`:
    - `test_brother_with_raw_ranks_tape_first`;
    - `test_hp_like_ranks_ipp_and_no_snmp_warning`: SNMP v1 answered, no model, IPP hit → one IPP candidate, `warnings == []`;
    - `test_page_printer_without_snmp_gets_no_snmp_warning`;
    - `test_tape_without_raw_warns_raw_port_closed_and_ranks_last`;
    - `test_pdf_unsupported_gives_no_candidate`;
    - `test_nothing_answered_is_the_only_warning`;
    - `test_https_redirect_prefills_web_ui_url`;
    - `test_plain_http_gives_no_override`;
    - `test_ipps_ranks_before_ipp`;
    - `test_slug_suggestion` (`"PT-P750W"` → `"pt-p750w"`, `"HP LaserJet CP1525N"` → `"hp-laserjet-cp1525n"`).
  - Integration, `test_printer_detect_api.py`, with `FakeSnmpAgent` plus a fake IPP printer plus fake TCP/HTTP via `app.state.detect_deps`:
    - `test_brother_like_device_detects_ptouch`: candidate[0] `backend == "ptouch"`, `model == "PT-P750W"`, `connection.snmp.version == "v2c"`, `capabilities.tape_width_mm == 12`.
    - `test_brother_ql_like_device_detects_brother_ql`.
    - `test_ipp_device_on_ipp_print` and `test_ipp_device_on_ipp_printer`: the candidate URI ends with the answering path and uses the typed host.
    - `test_v1_fallback_fits_in_deadline` (Review Focus 1): SNMP v2c times out after its 2 s, v1 answers; `protocols.snmp_version == "v1"`; elapsed < 10 s.
    - `test_dead_host_all_not_reachable_within_bound`: every fake blocks; `deadline_s=1.0` injected. Every protocol is `not_reachable`, warnings `["nothing_answered"]`, elapsed < 1.5 s. Plus `test_default_bound_is_at_most_10s` on the constants.
    - `test_deadline_cancels_pending_probes` (Review Focus 4): one fake answers after 3 s with `deadline_s=1.0` → reason `deadline`; afterwards `asyncio.all_tasks()` contains no detection task.
    - `test_blocked_addresses_rejected_without_probe` (Review Focus 3): `localhost`, `127.0.0.1`, `169.254.169.254`, `::ffff:127.0.0.1` → 422 `host_not_allowed`; the SNMP agent, TCP opener and HTTP transport recorded nothing.
    - `test_detect_is_read_only`: across a full run, the SNMP agent saw only GET requests, the IPP fake only Get-Printer-Attributes, the TCP fake zero bytes written, the HTTP mock only `GET`. Plus a source guard `test_detection_never_imports_snmp_set`: no `set_cmd` in `app/services/detection/` or `snmp_helper.py`.
    - `test_detect_needs_admin`: `read` and `print` keys → 403.
    - `test_response_never_echoes_community`: community `"c0mmunity-7f3a"` → that string is absent from the response body and from caplog.
    - `test_detect_logs_do_not_contain_host` (caplog at INFO).
    - `test_detect_busy_is_429`: hold the semaphore twice, then a third request → 429.
    - `test_detect_route_is_versioned_and_admin_guarded`: the 1.5.0 versioning guard and the auth guardrail test both pass.
  - Counter-tests:
    - remove the block-list check → `test_blocked_addresses_rejected_without_probe` red;
    - rank IPP before tape → `test_brother_like_device_detects_ptouch` red;
    - put `community` into `DetectTapeConnection` → `test_response_never_echoes_community` red.
- [ ] **Step 2: Run** `pytest tests/unit/services/detection/test_ranking.py tests/integration/api/test_printer_detect_api.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement;** `pnpm gen:api`.
- [ ] **Step 4: Verify** per directory; ruff; mypy; the versioning guard.
- [ ] **Step 5: Commit** `feat(printers): detect protocol, model and connection from an address (#232)`.

## Task 6: Status source and its problem in the printer status (#232 hint, backend)

**Files:**
- Modify: `backend/app/schemas/printer.py` (`PrinterStatus`), `backend/app/api/routes/printers.py` (`get_printer_status`)
- Test: `backend/tests/integration/api/test_printer_status_source.py`

**Decisions:**
- New fields: `status_source: Literal["snmp", "ipp"]` (tape → `snmp`, ipp → `ipp`) and `status_source_problem: Literal["not_configured", "not_answering"] | None`.
- Visible to every scope; the fields carry no host.
- Rules, evaluated in this order on the raw cache row, **before** the 1.5.0 stale/unpolled mask:
  1. printer disabled → `None`;
  2. tape and `connection.snmp.discover` false → `not_configured`;
  3. `runtime.is_polled(id)` false for any other reason (runtime degraded) → `None`, because 1.5.0's "Not monitored" already covers it;
  4. no cache row yet → `None` (first probe pending);
  5. `is_stale(...)` → `None` (1.5.0's "Status unknown" covers it);
  6. raw cache `online is False` → `not_answering`;
  7. otherwise `None`.
- A page printer whose SNMP is silent never gets a problem, because only IPP feeds its status.

- [ ] **Step 1: Failing tests:**
  - `test_tape_created_with_snmp_not_answering_shows_problem`: `POST /api/v1/admin/printers` (tape, `snmp.discover: true`), with `FakeSnmpAgent(versions=set())`. After the t=0 probe (`_until` helper), status `status_source == "snmp"` and `status_source_problem == "not_answering"`.
  - `test_tape_without_snmp_is_not_configured`.
  - `test_tape_answering_snmp_has_no_problem`.
  - `test_page_printer_ipp_down_is_not_answering`: the fake IPP transport refuses → `status_source == "ipp"`, `not_answering`.
  - `test_page_printer_without_snmp_has_no_problem`: IPP answers, no SNMP agent → `None`.
  - `test_disabled_printer_has_no_problem`; `test_stale_row_has_no_problem`.
  - `test_problem_visible_to_read_key`.
  - `test_problem_uses_raw_cache_not_masked_status`: fresh tape row with `online: False`, then patch the 1.5.0 mask to null `online`. `status_source_problem` is still `"not_answering"`.
  - Counter-tests:
    - read `online` after the mask → `test_problem_uses_raw_cache_not_masked_status` red;
    - derive the problem from `discover` alone → `test_tape_created_with_snmp_not_answering_shows_problem` red.
- [ ] **Step 2: Run.** Expected: FAIL (fields missing).
- [ ] **Step 3: Implement;** `pnpm gen:api`.
- [ ] **Step 4: Verify** `pytest tests/integration/api -m "not slow"` (split if over 170 s); ruff; mypy.
- [ ] **Step 5: Commit** `feat(status): report which protocol a printer's status depends on and whether it answers (#232)`.

## Task 7: Detect in the add form, SNMP fields, warnings and the persistent hint (UI)

**Files:**
- Create: `frontend/src/features/settings/DetectPanel.tsx` (+ `DetectPanel.test.tsx`), `frontend/src/features/settings/detect.ts` (+ `detect.test.ts`), `frontend/src/features/settings/SnmpFields.tsx` (+ test), `frontend/src/features/printers/StatusSourceHint.tsx` (+ test)
- Modify: `frontend/src/features/settings/PrinterForm.tsx`, `IppPrinterFields.tsx` (`useIppDraft` gains `adoptProbe`), `api.ts` (`useDetectPrinter`, types `DetectResult`, `DetectCandidate`, `DetectWarningCode`), `frontend/src/features/printers/PrinterDetail.tsx` (hint under the header), both catalogs.
- Test: `frontend/e2e/settings.spec.ts` (detect flow, `page.route` mock of `**/api/v1/admin/printers/detect`, as the existing `ipp/probe` mock), `frontend/e2e/printers.spec.ts` (hint).

**Interfaces:**
- `useDetectPrinter()`: a mutation that posts `{host, snmp_community}` to `/api/v1/admin/printers/detect`.
- `interface PrefillValues { backend: "ptouch" | "brother_ql" | "ipp"; model?: string; host?: string; port?: number; snmp?: { discover: boolean; community: string; version: "v1" | "v2c" }; uri?: string; tlsVerify?: boolean; probe?: IppProbeSummary; webUiUrl?: string; name?: string; slug?: string }`.
- `prefillFromCandidate(candidate: DetectCandidate, ctx: { community: string; name: string; slug: string }) -> PrefillValues`:
  - `name`/`slug` come from the suggestion only when `ctx` has them empty;
  - `snmp.community = ctx.community`, because the server never returns it.
- `useIppDraft(...).adoptProbe(uri: string, tlsVerify: boolean, summary: IppProbeSummary)`: sets the URI and the verified probe (`probed`) and merges the trays with `mergeTrays`. No second "Read printer" is needed.
- `useDetectWarningText(): (code: DetectWarningCode, community: string) => string`; `useProtocolStateText()`.
- `SnmpFields({ value, onChange })`: switch "Read status over SNMP", community text input (≤ 64), version select v2c/v1.
  - It is shown for tape backends on create and edit, and the tape `connection` payload becomes `{host, port, snmp: {discover, community, version}}`.
  - Today the form keeps whatever `snmp` the row had and offers no field for it, so new tape printers are saved with `discover: false` (#227's root cause).
- `StatusSourceHint({ status })`: renders when `status_source_problem !== null`, otherwise nothing. Admins and non-admins see the same text.

**Decisions:**
- `DetectPanel` shows only when adding (`printer === null`), at the top of the form. It has the address input, an optional community input (default `public`) and the "Detect" button.
- While the run is going it shows a progress line. The result shows the protocol table (protocol, state text, `v1`/`v2c` for SNMP), the warnings, and one row per candidate with a "Use" button. The first candidate is marked "Best match".
- "Use" calls `prefill(prefillFromCandidate(...))` in `PrinterForm`, setting the existing state hooks. The form stays fully editable.
- When there are no candidates, the address is still copied into Host.
- Warnings are a `role="status"` list, not toasts; they stay until the next detection.
- Pinned copy (en / de):

| Key | en | de |
|---|---|---|
| button | Detect | Erkennen |
| address | Address (IP or host name) | Adresse (IP oder Hostname) |
| community | SNMP community | SNMP-Community |
| running | Detecting the printer… | Drucker wird erkannt … |
| best | Best match | Beste Übereinstimmung |
| use | Use | Übernehmen |
| state reachable / not_reachable / not_tried | answers / no answer / not tried | antwortet / keine Antwort / nicht versucht |
| `snmp_not_answering` | SNMP does not answer. Without it the hub cannot read status, tape width or serial number. Enable SNMP v1 or v2c on the device with community “{community}”, or enter the community the device uses. | SNMP antwortet nicht. Ohne SNMP kann der Hub weder Status noch Bandbreite noch Seriennummer lesen. Aktiviere SNMP v1 oder v2c am Gerät mit der Community „{community}“ oder trage die Community ein, die das Gerät nutzt. |
| `raw_port_closed` | Port 9100 is closed. This device cannot print raw tape jobs. | Port 9100 ist geschlossen. Dieses Gerät kann keine Rohdaten-Bandaufträge drucken. |
| `ipp_not_answering` | IPP does not answer on port 631. The hub needs IPP to print pages and to read the status of a page printer. | IPP antwortet nicht auf Port 631. Der Hub braucht IPP, um Seiten zu drucken und den Status eines Seitendruckers zu lesen. |
| `ipp_pdf_unsupported` | The printer answers IPP but does not accept PDF, so the hub cannot print on it. | Der Drucker antwortet per IPP, nimmt aber kein PDF an. Der Hub kann deshalb nicht darauf drucken. |
| `model_unknown` | The device answers SNMP, but its model is not one the hub supports for tape printing. | Das Gerät antwortet per SNMP, aber sein Modell unterstützt der Hub nicht für den Banddruck. |
| `nothing_answered` | Nothing answered at this address. Check the address and that the device is switched on and in the same network. | Unter dieser Adresse hat nichts geantwortet. Prüfe die Adresse und ob das Gerät eingeschaltet und im selben Netz ist. |
| hint snmp/not_configured | Status is not monitored: SNMP is switched off for this printer. Turn on SNMP in the printer settings so the hub can read status, tape width and serial number. | Status wird nicht überwacht: SNMP ist für diesen Drucker ausgeschaltet. Schalte SNMP in den Druckereinstellungen ein, damit der Hub Status, Bandbreite und Seriennummer lesen kann. |
| hint snmp/not_answering | SNMP does not answer. Without it the hub cannot read status, tape width or serial number. Check that the printer is on and that SNMP v1 or v2c is enabled with the configured community. | SNMP antwortet nicht. Ohne SNMP kann der Hub weder Status noch Bandbreite noch Seriennummer lesen. Prüfe, ob der Drucker eingeschaltet ist und SNMP v1 oder v2c mit der eingestellten Community aktiv ist. |
| hint ipp/not_answering | IPP does not answer. Without it the hub cannot read the status of this page printer or print on it. Check that the printer is on and that IPP is enabled. | IPP antwortet nicht. Ohne IPP kann der Hub den Status dieses Seitendruckers nicht lesen und nicht darauf drucken. Prüfe, ob der Drucker eingeschaltet und IPP aktiv ist. |
| snmp switch / version | Read status over SNMP / SNMP version | Status per SNMP lesen / SNMP-Version |

- [ ] **Step 1: Failing tests:**
  - `prefillFromCandidate tape keeps typed community`;
  - `… ipp sets uri and probe`;
  - `… does not overwrite a typed name`;
  - `warning text en and de for every code`: iterate over all `DetectWarningCode` values; both locales are non-empty and distinct from the code;
  - `DetectPanel use fills the form`: after "Use", Host, Model, Driver and the SNMP fields hold the candidate's values;
  - `DetectPanel ipp candidate counts as read`: saving does not ask for "Read the printer once";
  - `SnmpFields round-trip`: the payload contains `version: "v1"` after selecting v1;
  - `StatusSourceHint renders per source and problem` (three texts) and `… renders nothing without problem`;
  - e2e `detect prefills the add form`, with the mocked result of one ptouch candidate and one warning;
  - e2e `hint on a tape printer without SNMP`: an e2e tape printer without SNMP shows the not_configured text.
  - Counter-test: `prefillFromCandidate` that reads a community from the candidate → `… keeps typed community` red.
- [ ] **Step 2: Run** `pnpm exec vitest run src/features/settings src/features/printers/StatusSourceHint.test.tsx`. Expected: FAIL.
- [ ] **Step 3: Implement** (UI task protocol; `break-ui` with a 253-character host, a 120-character make-and-model, six warnings at once, and eight candidates).
- [ ] **Step 4: Verify** the frontend checks; screenshots of the detect result (tape, IPP, nothing answered) and of the hint.
- [ ] **Step 5: Commit** `feat(ui): detect a printer from its address and warn when its status cannot be read (#232)`.

## Task 8: `web_ui_url` override, effective URL, admin-only exposure (#233, backend)

**Files:**
- Create: `backend/alembic/versions/2026_11_10_0001-20261110a1_printer_web_ui_url.py` (`revision = "20261110a1"`, `down_revision = "20261109b1"`, adds nullable `web_ui_url String(2048)` to `printers`), `backend/app/services/web_ui.py`
- Modify: `backend/app/models/printer.py` (`web_ui_url: str | None`), `backend/app/schemas/printer_admin.py` (create/update payloads + `validate_web_ui_url`), `backend/app/services/printer_admin_service.py` (`_payload_to_row`, `_apply_update_patch`, audit view), `backend/app/api/routes/admin_printers_api.py` (`PrinterRead.web_ui_url`, `web_ui_url_effective`), `backend/app/schemas/printer.py` (public `PrinterRead.web_ui_url: str | None = None`), `backend/app/api/routes/printers.py` (list + detail fill it for admin only, in the same place 1.5.0 fills `hardware_id`)
- Test: `backend/tests/unit/services/test_web_ui.py`, `backend/tests/unit/schemas/test_web_ui_url.py`, `backend/tests/integration/api/test_web_ui_url_api.py`, `backend/tests/integration/db/test_alembic_web_ui_url.py`

**Interfaces:**
- `MAX_WEB_UI_URL_LENGTH = 2048`.
- `validate_web_ui_url(value: str) -> str`:
  - it strips the value, then requires `check_http_url` (`app/sheets/text.py`);
  - it rejects `0x7F`, user info (`@` in the netloc or `parsed.username is not None`), a missing hostname and length > 2048;
  - each rule has a fixed message that never repeats the value.
- Create payload `web_ui_url: str | None = None`. Update payload `web_ui_url: str | None`, where a field that is **absent** leaves the value unchanged, explicit `null` or `""` clears it (`model_fields_set`). A validation failure is 422 with the pydantic error and **no input echo** (the `input` key stripped as `error_handlers.py` does for sheets; extend `SHEET_PREFIXES`-style handling to `/api/v1/admin/printers`, or assert it is already stripped).
- `effective_web_ui_url(printer: Printer) -> str | None`:
  - `printer.web_ui_url` when set;
  - else for ipp `http://{host}/` with `host = urlsplit(to_http_url(uri)).hostname`;
  - else for tape `http://{connection.host}/`;
  - an IPv6 host is bracketed;
  - a missing or unparsable host → `None`.
- Exposure:
  - public `PrinterRead.web_ui_url` = `effective_web_ui_url(p)` iff `auth.scope == "admin"`, else `None`;
  - admin `PrinterRead` has `web_ui_url` (the stored override) and `web_ui_url_effective`;
  - `PrinterStatus` and the SSE events gain nothing.
- A change of `web_ui_url` is not in `wiring_key`, so it needs no re-wire.
- The audit view includes `web_ui_url`. It cannot carry credentials, because user info is refused.

- [ ] **Step 1: Failing tests:**
  - `test_derived_url_ipp` (`ipp://printer-1.example.invalid:631/ipp/print` → `http://printer-1.example.invalid/`), `test_derived_url_tape`, `test_derived_url_ipv6_bracketed`, `test_override_wins`.
  - `test_web_ui_url_rejects`: `javascript:alert(1)`, `data:text/html,x`, `http://user:pw@h/`, `http://u@h/`, `ftp://h/`, `http:///x`, 2049 characters, `http://h/\x7f` → 422 via the create route. The body never contains the submitted value.
  - `test_web_ui_url_accepts_https_port_path` (`https://printer-1.example.invalid:8443/web/`).
  - `test_update_absent_keeps_null_clears`.
  - `test_admin_sees_effective_url` (list and detail).
  - `test_non_admin_never_sees_host_or_url`:
    - for `read` and `print` keys, read the JSON of `GET /api/v1/printers`, `GET /api/v1/printers/{id}` and `GET /api/v1/printers/{id}/status` for an IPP printer (URI host `ipp-host.example.invalid`, override `https://override-host.example.invalid:8443/`) and a tape printer (override `https://tape-override.example.invalid/`);
    - assert that the serialised text contains none of `ipp-host.example.invalid`, `override-host.example.invalid`, `tape-override.example.invalid`, and that `web_ui_url` is `null`;
    - the tape `connection.host` is pre-existing visible data and uses a different name, so the assertion targets what this feature adds.
  - Migration upgrade/downgrade on empty and populated DB (pattern `tests/integration/db/test_alembic_sheet_migration.py`), and `alembic heads` shows a single head.
  - Counter-test: fill `web_ui_url` regardless of scope → `test_non_admin_never_sees_host_or_url` red.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement;** `pnpm gen:api`.
- [ ] **Step 4: Verify** per directory; `alembic upgrade head && alembic downgrade -1 && alembic upgrade head` on a temp DB; ruff; mypy.
- [ ] **Step 5: Commit** `feat(printers): optional web interface address per printer, derived from the host by default (#233)`.

## Task 9: "Open printer web interface" button and the form field (#233, UI)

**Files:**
- Create: `frontend/src/features/printers/WebUiLink.tsx` (+ `WebUiLink.test.tsx`)
- Modify: `PrinterCard.tsx` (card actions), `PrinterDetail.tsx` (header actions, next to `PauseResumeButton`), `frontend/src/features/settings/PrinterForm.tsx` (field "Web interface address" for both backends; detection prefill sets it via `PrefillValues.webUiUrl`), both catalogs.
- Test: `frontend/e2e/printers.spec.ts`.

**Decisions:**
- `WebUiLink({ url }: { url: string | null | undefined })` renders `null` unless `url` is a string starting with `http://` or `https://`. The check repeats the server rule, as defence in depth against a `javascript:` value from any source.
- It renders an `<a href={url} target="_blank" rel="noopener noreferrer">` styled as the secondary button, with an external-link icon and the visible text below.
- Rendering depends on `printer.web_ui_url` from the API, which only admins receive. The component does not read the session, so the server is the gate.
- On the card it is a compact icon button with an `aria-label` equal to the text and a tooltip, so it does not crowd 390 px cards. On the detail page it shows the full text.
- The form validates client-side with the same rules as the server, to give early feedback. The server stays authoritative and its 422 text is shown.
- Pinned copy (en / de):
  - "Open printer web interface" / "Weboberfläche des Druckers öffnen";
  - field "Web interface address" / "Adresse der Weboberfläche";
  - description "Leave empty to use http://<host>/. Only http and https." / "Leer lassen für http://<Host>/. Nur http und https.";
  - error "Use an http or https address without user name or password, at most 2048 characters." / "Verwende eine http- oder https-Adresse ohne Benutzername und Passwort, höchstens 2048 Zeichen."
- Device credentials are never stored or asked for (non-goal). The form has no field for them.

- [ ] **Step 1: Failing tests:**
  - `WebUiLink renders an external link with target and rel`;
  - `WebUiLink renders nothing for null`;
  - `WebUiLink renders nothing for javascript:`;
  - `PrinterForm sends web_ui_url and clears it with empty`;
  - e2e `admin sees the web interface button on overview and detail`: `href === "http://192.0.2.10/"` for the e2e tape printer, `target === "_blank"`, `rel === "noopener noreferrer"`;
  - e2e `read user sees no web interface button`: create a read key via `POST /api/v1/admin/api-keys {scopes: ["read"]}` with the main key, sign in with `signInWith`, and assert that the button count is 0 on overview and detail.
  - Counter-test: render on `session.scope` instead of `url` while the server sends `null` → no change. That proves the server is the gate; record it. Then render without the scheme check → `… nothing for javascript:` red.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** (UI task protocol; `break-ui` with a 2048-character URL in the form, a 60-character printer name on a 390 px card, and both badges plus the pause button in the card actions).
- [ ] **Step 4: Verify** the frontend checks; screenshots of card and detail, admin and read.
- [ ] **Step 5: Commit** `feat(ui): open the printer's own web interface from the overview and detail page (#233)`.

## Task 10: Docs

**Files:**
- Modify: the printers admin page under `docs/` (adding a printer, Detect, SNMP version, the hint, the web UI link); `README.md` feature list; `docs/architecture.md` (one line on detection and its probe bounds); a new ADR `docs/decisions/00NN-bounded-outbound-probes-for-detection.md`.
  - The ADR records the SSRF bounds from Global Constraints, why private ranges are allowed but loopback, link-local and metadata are not, why redirects are never followed, and why mDNS is out of scope.
- Check: `grep -rn "ipp/probe" docs/` → mention detect next to it.

- [ ] **Step 1: Write** the pages. Example values use `192.0.2.0/24` and `example.invalid`.
- [ ] **Step 2: Verify** that the privacy-scan pattern from CI, run locally, has no hits.
- [ ] **Step 3: Commit** `docs: printer detection, SNMP version, status hint and web interface link (#232 #233)`.

## Order and dependencies

```
Step 0 (1.5.0 merged, preconditions checked)
Task 1 → Task 3 → Task 5 → Task 7
Task 2 → Task 5
Task 4 → Task 5
Task 6 → Task 7
Task 8 → Task 9
Task 7, Task 9 → Task 10
```

- Tasks 7 and 9 both modify `PrinterForm.tsx` and `PrinterDetail.tsx`, so they run strictly sequentially, 7 first.
- Tasks 5 and 8 both modify `admin_printers_api.py`, so they run sequentially.
- Task 8's migration is the only one in 1.6.0 and chains on `20261109b1`.

## Gate, review and shipping (controller)

1. **Full gate** in a frozen clone, with no parallel load:
   - backend: `pytest -m "not slow" --cov=app --cov-fail-under=80`, ruff, mypy, and `alembic upgrade head` plus `downgrade -1`;
   - frontend: typecheck, lint, test:coverage, build, e2e.
2. **Whole-branch review** with the four lenses:
   - **Taint:**
     - the admin-given host and the community never reach logs above debug or non-admin responses;
     - `web_ui_url` only in admin views;
     - device strings (sysDescr, make-and-model) are sanitised before any response;
     - the detect response carries the serial, so it stays admin only.
   - **Outcome:** run detect against the e2e fakes and check that the output matches the ranking rules, not only the plan.
   - **Unchanged dependencies:** `probe_ipp` timeouts and error mapping as reused; `ModelRegistry` discovery; the 1.5.0 status mask order.
   - **Runtime/temporal:** deadline cancellation, the semaphore, the v2c→v1 sequence inside the deadline, and the re-wire on an SNMP version change.
3. **`security-audit`** on the changed surface. It covers:
   - the outbound probes to an admin-given host: no redirects, timeouts, size caps (IPP 1 MB, HTTP no body read), fixed schemes and ports, the block list incl. IPv4-mapped IPv6, the resolve-once rule, the concurrency limit;
   - `web_ui_url` validation and rendering (`javascript:`, `data:`, user info, `rel`);
   - admin-only exposure;
   - the configured-community fix in preflight.
   - HIGH or CRITICAL findings block the release.
4. **PR** with the Codex review, then merge.
5. **Release and rollout:**
   1. Back up the DB.
   2. Release 1.6.0 via `workflow_dispatch`; bump the Kept pin. The migration `20261110a1` runs on start.
   3. As admin, run Detect against each production device, read-only:
      - the PT-P750W and the QL-820NWB must rank `ptouch` / `brother_ql` with `v2c` and the right width;
      - the HP CP1525N must rank IPP with no SNMP warning and `snmp_version: "v1"` in the protocol table.
      - Compare with the facts of 2026-11-09. Do not save over existing printers.
   4. Check that each existing printer page shows no hint; the Brothers poll SNMP v2c.
   5. Open each printer's web interface from the overview as admin, and confirm the button is absent for a read key.
   6. Optionally, add a throw-away printer through Detect against one device, run the 1.5.0 test print, then disable it.
6. **Release notes:**
   - Detect, with its probes and that it never writes to the device;
   - the SNMP version field; tape printers default to v2c;
   - the configured SNMP community is now used for the print preflight too;
   - the status-source hint;
   - the web interface button and the `web_ui_url` override;
   - that device web-UI credentials are not stored.

## Out of scope

- **mDNS/DNS-SD.** The hub runs in a container on a bridge network by default, where multicast from the LAN does not arrive. Making it work needs host networking or an mDNS reflector, which is not cheap. The four-path IPP walk covers what the `rp=` key would give. Revisit if a device answers IPP on a path outside `IPP_PATHS`.
- **Device web-UI credentials** (non-goal, maintainer ruling).
- **SNMPv3.** No device in scope needs it; `SnmpVersion` rejects `"v3"`.
- **Proxying the device web UI.** The link opens the device directly from the browser (#233).
- **Block list for the existing `/ipp/probe`.** It stays as it is in 1.6.0. See the open points.

## Open points for the maintainer (not blocking this plan)

- **Pre-existing exposure.** For tape printers, `_connection_view` (`app/api/routes/printers.py`) returns the stored `connection`, including `host` and `snmp.community`, unchanged to `read` and `print` callers. #233 only forbids adding host or URL through the new feature, so this plan does not change it. The new `snmp.version` key is not secret. Proposal: a follow-up issue to reduce the non-admin tape connection to `{port}` or nothing, after checking the Hangar client.
- **`/ipp/probe` block list.** Should the existing IPP probe get the same address block list as Detect? Proposal: yes, in the same follow-up, since it is the same SSRF class.
