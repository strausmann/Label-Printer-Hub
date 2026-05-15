"""Printer-backend layer — transport implementations behind a common Protocol.

The registry (Phase 5) will live here; this module currently re-exports the
exception hierarchy so other layers can `from app.printer_backends.exceptions
import PrinterError, ...` immediately.
"""
