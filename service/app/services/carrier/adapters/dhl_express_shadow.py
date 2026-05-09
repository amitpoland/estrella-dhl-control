"""
dhl_express_shadow.py — DHL shadow-mode wrapper adapter.

DL-F2 scope
-----------
Wraps a stub adapter and a live adapter. Every Protocol method on
the wrapper:

  1. Calls the stub for the canonical response.
  2. Calls the live adapter purely for observation. Live failures
     are caught and recorded; they NEVER propagate to the operator.
  3. Compares stub vs live at the shape/metadata level only.
  4. Persists one row to the shadow log SQLite store.
  5. Returns the stub's response. The live response NEVER reaches
     the registry, label store, or coordinator state.

Hard rules (also enforced by source-grep tests)
-----------------------------------------------
* No env reads.
* No HTTP client imports.
* No print/log of the Authorization header (or any credential).
* No write to carrier_shipment_db / carrier_label_store / coordinator
  state. Shadow rows go ONLY to dhl_shadow_db.
* parse_webhook_event delegates to the live parser and writes NO
  shadow row (webhook parsing is read-only and observed through the
  webhook receiver's own evidence trail).
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional

from ..base import (
    CARRIER_DHL,
    CarrierEvent,
    CarrierShipmentRequest,
    PackageSpec,
    RawCancelResponse,
    RawShipmentResponse,
)
from .base import (
    CarrierAdapter,
    CarrierAdapterError,
    CarrierRateLimitError,
    CarrierResponseError,
)


# ── Outcome value sets ──────────────────────────────────────────────────────

_OK:           str = "ok"
_ERROR:        str = "error"
_SKIPPED:      str = "skipped"

_DIFF_MATCH:            str = "match"
_DIFF_LIVE_ONLY_ERROR:  str = "live_only_error"
_DIFF_STUB_ONLY_ERROR:  str = "stub_only_error"
_DIFF_BOTH_ERROR:       str = "both_error"
_DIFF_SHAPE_DIFF:       str = "shape_diff"
_DIFF_UNKNOWN:          str = "unknown"

#: Error class names that DL-F2 records verbatim. Anything outside the
#: allowlist becomes "Exception" so unexpected runtime types cannot
#: leak class metadata that hints at internal paths.
_SAFE_ERROR_CLASSES = frozenset({
    "CarrierAdapterError",
    "CarrierAuthError",
    "CarrierRateLimitError",
    "CarrierTransportError",
    "CarrierResponseError",
})


# ── Internal call-outcome record ────────────────────────────────────────────

@dataclass(frozen=True)
class _CallOutcome:
    """What happened when we invoked one adapter method.

    ``value`` is set only on success; ``exc`` only on failure.
    Mutually exclusive but a defensive ``ok`` boolean makes the
    intent obvious at the call sites.
    """
    ok:           bool
    value:        Any
    exc:          Optional[BaseException]
    duration_ms:  int


# ── Shadow adapter ──────────────────────────────────────────────────────────

class DHLExpressShadowAdapter:
    """Wraps a stub + live adapter; records both outcomes; returns stub.

    Construction
    ------------
    ``stub`` and ``live`` MUST satisfy the :class:`CarrierAdapter`
    Protocol. Either argument missing the surface raises ``TypeError``.

    ``shadow_store`` is an optional injection for tests. The default
    routes calls to the module-level :mod:`dhl_shadow_db` singleton
    via a small shim. Tests pass a fake object exposing a single
    ``record_call_outcome(**kwargs)`` method so writes are observable
    without booting SQLite.

    ``actor`` defaults to ``"system:shadow"`` — the value that lands
    in every shadow row's ``actor`` column unless overridden.
    """

    carrier: str = CARRIER_DHL

    def __init__(
        self,
        *,
        stub:          CarrierAdapter,
        live:          CarrierAdapter,
        shadow_store:  Optional[Any] = None,
        clock:         Optional[Callable[[], float]] = None,
        actor:         str = "system:shadow",
    ) -> None:
        if not isinstance(stub, CarrierAdapter):
            raise TypeError(
                "stub does not satisfy CarrierAdapter Protocol"
            )
        if not isinstance(live, CarrierAdapter):
            raise TypeError(
                "live does not satisfy CarrierAdapter Protocol"
            )
        self._stub:          CarrierAdapter      = stub
        self._live:          CarrierAdapter      = live
        self._store:         Optional[Any]       = shadow_store
        self._monotonic:     Callable[[], float] = clock or time.monotonic
        self._actor:         str                 = actor or "system:shadow"

    # ── Read-only read-throughs (test surface) ─────────────────────────────

    @property
    def stub(self) -> CarrierAdapter:
        return self._stub

    @property
    def live(self) -> CarrierAdapter:
        return self._live

    # ── Protocol method: create_shipment ────────────────────────────────────

    def create_shipment(
        self,
        request: CarrierShipmentRequest,
    ) -> RawShipmentResponse:
        request_hash = self._hash_create(request)
        stub_outcome = self._invoke(lambda: self._stub.create_shipment(request))
        live_outcome = self._invoke(lambda: self._live.create_shipment(request))
        diff_outcome, diff_notes = self._classify_create(stub_outcome, live_outcome)
        self._record(
            method        = "create_shipment",
            request_hash  = request_hash,
            stub_outcome  = stub_outcome,
            live_outcome  = live_outcome,
            diff_outcome  = diff_outcome,
            diff_notes    = diff_notes,
            shape_extract = _extract_shipment_shape,
        )
        if not stub_outcome.ok:
            assert stub_outcome.exc is not None
            raise stub_outcome.exc
        return stub_outcome.value

    # ── Protocol method: cancel_shipment ────────────────────────────────────

    def cancel_shipment(
        self,
        awb: str,
        *,
        reason: str = "",
    ) -> RawCancelResponse:
        request_hash = self._hash_cancel(awb, reason)
        stub_outcome = self._invoke(
            lambda: self._stub.cancel_shipment(awb, reason=reason)
        )
        live_outcome = self._invoke(
            lambda: self._live.cancel_shipment(awb, reason=reason)
        )
        diff_outcome, diff_notes = self._classify_cancel(stub_outcome, live_outcome)
        self._record(
            method        = "cancel_shipment",
            request_hash  = request_hash,
            stub_outcome  = stub_outcome,
            live_outcome  = live_outcome,
            diff_outcome  = diff_outcome,
            diff_notes    = diff_notes,
            shape_extract = _extract_cancel_shape,
        )
        if not stub_outcome.ok:
            assert stub_outcome.exc is not None
            raise stub_outcome.exc
        return stub_outcome.value

    # ── Protocol method: fetch_label ────────────────────────────────────────

    def fetch_label(
        self,
        awb: str,
        *,
        fmt: str = "pdf",
    ) -> bytes:
        request_hash = self._hash_fetch(awb, fmt)
        stub_outcome = self._invoke(
            lambda: self._stub.fetch_label(awb, fmt=fmt)
        )
        live_outcome = self._invoke(
            lambda: self._live.fetch_label(awb, fmt=fmt)
        )
        diff_outcome, diff_notes = self._classify_fetch_label(
            stub_outcome, live_outcome, fmt=fmt,
        )
        self._record(
            method        = "fetch_label",
            request_hash  = request_hash,
            stub_outcome  = stub_outcome,
            live_outcome  = live_outcome,
            diff_outcome  = diff_outcome,
            diff_notes    = diff_notes,
            shape_extract = lambda x: _extract_label_bytes_shape(x, fmt=fmt),
        )
        if not stub_outcome.ok:
            assert stub_outcome.exc is not None
            raise stub_outcome.exc
        return stub_outcome.value

    # ── Protocol method: schedule_pickup ────────────────────────────────────

    def schedule_pickup(
        self,
        awb: str,
        *,
        when_iso: str,
        location: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        request_hash = self._hash_pickup(awb, when_iso)
        stub_outcome = self._invoke(
            lambda: self._stub.schedule_pickup(
                awb, when_iso=when_iso, location=location,
            )
        )
        live_outcome = self._invoke(
            lambda: self._live.schedule_pickup(
                awb, when_iso=when_iso, location=location,
            )
        )
        diff_outcome, diff_notes = self._classify_pickup(stub_outcome, live_outcome)
        self._record(
            method        = "schedule_pickup",
            request_hash  = request_hash,
            stub_outcome  = stub_outcome,
            live_outcome  = live_outcome,
            diff_outcome  = diff_outcome,
            diff_notes    = diff_notes,
            shape_extract = _extract_pickup_shape,
        )
        if not stub_outcome.ok:
            assert stub_outcome.exc is not None
            raise stub_outcome.exc
        return stub_outcome.value

    # ── Protocol method: parse_webhook_event ────────────────────────────────

    def parse_webhook_event(
        self,
        body: bytes,
        headers: Optional[Mapping[str, str]] = None,
    ) -> CarrierEvent:
        """Webhook parsing is read-only and observed via the receiver's
        own evidence trail. Shadow mode does NOT write a row here.
        Delegates straight to the live parser."""
        return self._live.parse_webhook_event(body, headers=headers)

    # ── Internal: invocation + classification ──────────────────────────────

    def _invoke(self, fn: Callable[[], Any]) -> _CallOutcome:
        """Run *fn* and capture (value, exc, duration_ms).

        Catches ``BaseException`` so an unexpected runtime type never
        propagates from the live adapter into the operator path. The
        caller decides whether to re-raise (stub failures) or ignore
        (live failures).
        """
        t0 = self._monotonic()
        try:
            value = fn()
        except BaseException as exc:
            ms = int((self._monotonic() - t0) * 1000)
            return _CallOutcome(ok=False, value=None, exc=exc, duration_ms=ms)
        ms = int((self._monotonic() - t0) * 1000)
        return _CallOutcome(ok=True, value=value, exc=None, duration_ms=ms)

    @staticmethod
    def _safe_class_name(exc: BaseException) -> str:
        name = type(exc).__name__
        return name if name in _SAFE_ERROR_CLASSES else "Exception"

    # ── Diff classification (per method) ───────────────────────────────────

    @staticmethod
    def _classify_create(
        stub: _CallOutcome,
        live: _CallOutcome,
    ) -> tuple:
        if stub.ok and live.ok:
            stub_rsp: RawShipmentResponse = stub.value
            live_rsp: RawShipmentResponse = live.value
            notes: List[str] = []
            if stub_rsp.label_format != live_rsp.label_format:
                notes.append(
                    f"label_format stub={stub_rsp.label_format!r} "
                    f"live={live_rsp.label_format!r}"
                )
            if not stub_rsp.label_bytes:
                notes.append("stub_label_size=0")
            if not live_rsp.label_bytes:
                notes.append("live_label_size=0")
            if stub_rsp.carrier != live_rsp.carrier:
                notes.append(
                    f"carrier stub={stub_rsp.carrier!r} "
                    f"live={live_rsp.carrier!r}"
                )
            if notes:
                return _DIFF_SHAPE_DIFF, "; ".join(notes)
            return _DIFF_MATCH, ""
        if stub.ok and not live.ok:
            return _DIFF_LIVE_ONLY_ERROR, _live_skipped_note(live)
        if not stub.ok and live.ok:
            return _DIFF_STUB_ONLY_ERROR, ""
        return _DIFF_BOTH_ERROR, ""

    @staticmethod
    def _classify_cancel(
        stub: _CallOutcome,
        live: _CallOutcome,
    ) -> tuple:
        if stub.ok and live.ok:
            stub_rsp: RawCancelResponse = stub.value
            live_rsp: RawCancelResponse = live.value
            if bool(stub_rsp.accepted) != bool(live_rsp.accepted):
                return _DIFF_SHAPE_DIFF, (
                    f"accepted stub={stub_rsp.accepted} "
                    f"live={live_rsp.accepted}"
                )
            return _DIFF_MATCH, ""
        if stub.ok and not live.ok:
            return _DIFF_LIVE_ONLY_ERROR, _live_skipped_note(live)
        if not stub.ok and live.ok:
            return _DIFF_STUB_ONLY_ERROR, ""
        return _DIFF_BOTH_ERROR, ""

    @staticmethod
    def _classify_fetch_label(
        stub: _CallOutcome,
        live: _CallOutcome,
        *,
        fmt: str,
    ) -> tuple:
        if stub.ok and live.ok:
            stub_bytes: bytes = stub.value or b""
            live_bytes: bytes = live.value or b""
            notes = []
            if not stub_bytes:
                notes.append("stub_label_size=0")
            if not live_bytes:
                notes.append("live_label_size=0")
            if notes:
                return _DIFF_SHAPE_DIFF, "; ".join(notes)
            return _DIFF_MATCH, ""
        if stub.ok and not live.ok:
            return _DIFF_LIVE_ONLY_ERROR, _live_skipped_note(live)
        if not stub.ok and live.ok:
            return _DIFF_STUB_ONLY_ERROR, ""
        return _DIFF_BOTH_ERROR, ""

    @staticmethod
    def _classify_pickup(
        stub: _CallOutcome,
        live: _CallOutcome,
    ) -> tuple:
        if stub.ok and live.ok:
            return _DIFF_MATCH, ""
        if stub.ok and not live.ok:
            return _DIFF_LIVE_ONLY_ERROR, _live_skipped_note(live)
        if not stub.ok and live.ok:
            return _DIFF_STUB_ONLY_ERROR, ""
        return _DIFF_BOTH_ERROR, ""

    # ── Request-hash helpers ───────────────────────────────────────────────

    @staticmethod
    def _hash_create(request: CarrierShipmentRequest) -> str:
        """Per DL-F2 plan: seed = batch_id|reference|n_packages|pkg|service."""
        from . import dhl_shadow_db as dsdb
        first_sig = ""
        if request.packages:
            p = request.packages[0]
            first_sig = (
                f"{p.weight_kg}|{p.length_cm}|{p.width_cm}|{p.height_cm}"
            )
        return dsdb.compute_request_hash(
            "create_shipment",
            request.batch_id,
            request.reference,
            len(request.packages),
            first_sig,
            request.service_code,
        )

    @staticmethod
    def _hash_cancel(awb: str, reason: str) -> str:
        from . import dhl_shadow_db as dsdb
        return dsdb.compute_request_hash(
            "cancel_shipment", "dhl", awb, reason or "",
        )

    @staticmethod
    def _hash_fetch(awb: str, fmt: str) -> str:
        from . import dhl_shadow_db as dsdb
        return dsdb.compute_request_hash(
            "fetch_label", "dhl", awb, (fmt or "pdf").lower(),
        )

    @staticmethod
    def _hash_pickup(awb: str, when_iso: str) -> str:
        from . import dhl_shadow_db as dsdb
        return dsdb.compute_request_hash(
            "schedule_pickup", "dhl", awb, when_iso or "",
        )

    # ── Persist ────────────────────────────────────────────────────────────

    def _record(
        self,
        *,
        method:         str,
        request_hash:   str,
        stub_outcome:   _CallOutcome,
        live_outcome:   _CallOutcome,
        diff_outcome:   str,
        diff_notes:     str,
        shape_extract:  Callable[[Any], Dict[str, Any]],
    ) -> None:
        """Build the row payload and call the store. Failures here are
        swallowed — the operator action must never crash because the
        shadow store is unavailable."""
        try:
            stub_shape = (
                shape_extract(stub_outcome.value) if stub_outcome.ok else {}
            )
            live_shape = (
                shape_extract(live_outcome.value) if live_outcome.ok else {}
            )
            stub_status = _OK if stub_outcome.ok else _ERROR
            if live_outcome.ok:
                live_status = _OK
            elif _is_quota_skip(live_outcome.exc):
                live_status = _SKIPPED
            else:
                live_status = _ERROR

            self._invoke_store(
                method              = method,
                request_hash        = request_hash,
                actor               = self._actor,
                stub_status         = stub_status,
                stub_awb            = stub_shape.get("awb", ""),
                stub_label_format   = stub_shape.get("label_format", ""),
                stub_label_size     = int(stub_shape.get("label_size", 0)),
                stub_error_class    = (
                    self._safe_class_name(stub_outcome.exc)
                    if not stub_outcome.ok and stub_outcome.exc is not None
                    else ""
                ),
                stub_error_summary  = (
                    str(stub_outcome.exc)
                    if not stub_outcome.ok and stub_outcome.exc is not None
                    else ""
                ),
                live_status         = live_status,
                live_awb            = live_shape.get("awb", ""),
                live_label_format   = live_shape.get("label_format", ""),
                live_label_size     = int(live_shape.get("label_size", 0)),
                live_http_status    = 0,
                live_error_class    = (
                    self._safe_class_name(live_outcome.exc)
                    if not live_outcome.ok and live_outcome.exc is not None
                    else ""
                ),
                live_error_summary  = (
                    str(live_outcome.exc)
                    if not live_outcome.ok and live_outcome.exc is not None
                    else ""
                ),
                live_duration_ms    = live_outcome.duration_ms,
                diff_outcome        = diff_outcome,
                diff_notes          = diff_notes,
            )
        except Exception:
            # Never fail the operator action because the shadow log
            # write blew up. Mirrors the manifest-message non-fatal
            # pattern in carrier_coordinator.
            return

    def _invoke_store(self, **kwargs) -> None:
        """Dispatch to the injected store or the module singleton."""
        if self._store is not None:
            self._store.record_call_outcome(**kwargs)
            return
        # Default path: module-level singleton. Imported locally so a
        # parse-only consumer that builds the wrapper without booting
        # SQLite never imports this module at import time.
        from . import dhl_shadow_db as dsdb
        dsdb.record_call_outcome(**kwargs)


# ── Helpers (module-private) ────────────────────────────────────────────────

def _is_quota_skip(exc: Optional[BaseException]) -> bool:
    """True iff the live failure was a daily-quota refusal made by
    the live adapter BEFORE the HTTP call. Distinct from generic
    rate-limit errors arriving from the carrier (also
    CarrierRateLimitError). Both translate to live_status="skipped"
    for shadow-row purposes — operators see one obvious bucket."""
    return isinstance(exc, CarrierRateLimitError)


def _live_skipped_note(live: _CallOutcome) -> str:
    """Decorate the diff_notes column when the live call was skipped
    or errored. Truncation happens later in the DB module."""
    if live.exc is None:
        return ""
    if _is_quota_skip(live.exc):
        return f"live_skipped: {type(live.exc).__name__}"
    return f"live_error: {type(live.exc).__name__}"


# ── Shape extractors ────────────────────────────────────────────────────────

def _extract_shipment_shape(rsp: RawShipmentResponse) -> Dict[str, Any]:
    if rsp is None:
        return {}
    return {
        "awb":           rsp.awb or "",
        "label_format":  (rsp.label_format or "").lower(),
        "label_size":    len(rsp.label_bytes) if rsp.label_bytes else 0,
    }


def _extract_cancel_shape(rsp: RawCancelResponse) -> Dict[str, Any]:
    if rsp is None:
        return {}
    return {
        "awb":           rsp.awb or "",
        "label_format":  "",
        "label_size":    0,
    }


def _extract_label_bytes_shape(value: bytes, *, fmt: str) -> Dict[str, Any]:
    return {
        "awb":           "",
        "label_format":  (fmt or "").lower(),
        "label_size":    len(value) if value else 0,
    }


def _extract_pickup_shape(rsp: Dict[str, Any]) -> Dict[str, Any]:
    if rsp is None:
        return {}
    awb = ""
    if isinstance(rsp, dict):
        awb = str(rsp.get("awb") or rsp.get("consignmentNumber") or "")
    return {
        "awb":           awb,
        "label_format":  "",
        "label_size":    0,
    }
