"""
carrier.adapters — concrete carrier integrations.

Each carrier (DHL, FedEx, UPS, …) implements the
:class:`carrier.adapters.base.CarrierAdapter` Protocol. Adapters are
intentionally narrow: they translate a coordinator-level
``CarrierShipmentRequest`` into the carrier's wire format and back,
and they parse webhook events. They never touch:

  * the SQLite shipment registry,
  * the label store on disk,
  * audit JSON,
  * the execution-engine queue,
  * Cliq, SMTP, or any operator-facing surface.

That separation lets DL-F (live DHL) flip a single env flag without
risking shadow writes anywhere else.

DL-A scope: Protocol definition only — no concrete adapter yet.
"""
from __future__ import annotations
