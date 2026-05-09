"""
carrier — outbound shipping (DHL / FedEx / UPS) lifecycle, label storage,
shipment registry, and carrier-adapter protocol.

This package is the Layer-1/Layer-2 boundary for outbound carriers. It is
deliberately separate from the inbound customs/clearance flow under
``app.services.dhl_*`` (those modules deal with ZC429 / DHL clearance
emails for incoming shipments — a fundamentally different problem).

Design contract
---------------
- Pure-logic state engine (no DB writes, no I/O).
- Content-addressed label store on disk.
- SQLite shipment registry mirrors ``intake_lineage`` discipline:
  append-only transition history; no destructive updates.
- ``CarrierAdapter`` Protocol is the only place an adapter touches HTTP.
  The coordinator (DL-D) owns state, evidence, and execution-engine
  integration; adapters know carrier wire format and nothing else.

DL-A scope: skeleton only. No HTTP client, no live DHL calls, no routes.
"""
from __future__ import annotations
