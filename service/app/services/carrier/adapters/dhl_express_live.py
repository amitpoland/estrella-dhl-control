"""
dhl_express_live.py — Live DHL Express adapter.

DL-F1 scope
-----------
Implements the four send-side methods of :class:`CarrierAdapter`
against the DHL MyDHL API:

  * create_shipment    → POST /shipments
  * cancel_shipment    → DELETE /shipments/{awb}
  * fetch_label        → GET /shipments/{awb}/image
  * schedule_pickup    → POST /pickups

Parse-side methods (``parse_webhook_event`` / ``parse_push_payload``)
land from DL-E1 unchanged — they consume DHL Tracking-Unified-Push
events and remain transport-agnostic.

Hard rules (also enforced by source-grep tests)
-----------------------------------------------
* No environment variable reads. All credentials enter through the
  constructor.
* HTTP transport is httpx-compatible; the constructor accepts an
  injected ``http_client`` so tests run with a fake client and the
  module never touches the network.
* The ``Authorization`` header is constructed via httpx's basic-auth
  helper but never logged or printed — pinned by source-grep test.
* Daily-quota counter (DHL sandbox = 500/day) lives in
  :class:`DHLDailyQuota`. Exhaustion raises ``CarrierRateLimitError``
  BEFORE making the HTTP call, so a runaway retry loop on our side
  cannot exceed the budget.

Error mapping
-------------
  401 / 403          → CarrierAuthError
  429                → CarrierRateLimitError (after retry budget)
  5xx                → CarrierResponseError (after retry budget)
  network / timeout  → CarrierTransportError (after retry budget)
  malformed body     → CarrierResponseError
  4xx other          → returned to caller as (status, body) so domain
                       methods can decide (e.g., cancel returns
                       accepted=False instead of raising)
"""
from __future__ import annotations

import base64
import binascii
import json
import time
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from ..base import (
    CARRIER_DHL,
    CarrierEvent,
    CarrierShipmentRequest,
    RawCancelResponse,
    RawShipmentResponse,
)
from .base import (
    CarrierAdapterError,
    CarrierAuthError,
    CarrierRateLimitError,
    CarrierResponseError,
    CarrierTransportError,
)
from .dhl_express_live_request import build_create_shipment_body
from .dhl_express_quota import DHLDailyQuota


# ── Defaults ────────────────────────────────────────────────────────────────

_DEFAULT_TIMEOUT_S:    float = 4.0    # under DHL's 5s push budget
_DEFAULT_MAX_RETRIES:  int   = 3
_DEFAULT_DAILY_LIMIT:  int   = 500    # DHL sandbox quota
_SUPPORTED_LABEL_FMTS = frozenset({"pdf", "zpl"})

#: Backoff schedule (seconds) for retryable failures. Total worst-case
#: latency = sum(_RETRY_BACKOFF) ≈ 1.75s, leaving margin under any
#: 5-second SLA the route caller may impose.
_RETRY_BACKOFF: Tuple[float, ...] = (0.25, 0.5, 1.0)


def _make_default_httpx_client() -> Any:
    """Default sync httpx client. Imported lazily so test environments
    can monkey-patch this module without httpx wiring at module load."""
    import httpx
    return httpx.Client()


class DHLExpressLiveAdapter:
    """DHL Express adapter — live HTTP via injected ``http_client``.

    Constructor
    -----------
    ``base_url``           — sandbox or production base URL.
    ``username``           — Basic-auth username from DHL onboarding.
    ``password``           — Basic-auth password.
    ``account_number``     — DHL account / payer number.
    ``timeout_s``          — per-request timeout in seconds (default 4).
    ``http_client``        — any object exposing ``request(method, url,
                              json=, params=, auth=, timeout=)`` and
                              returning a Response with ``status_code``,
                              ``headers``, ``json()``, ``text``. Default
                              is ``httpx.Client()``.
    ``sleep``              — callable used between retries; default
                              ``time.sleep``. Tests inject a no-op.
    ``daily_limit``        — daily call cap (sandbox 500; production
                              negotiated).
    ``clock``              — passed through to the quota helper for
                              UTC-day rollover testing.
    """

    carrier: str = CARRIER_DHL

    def __init__(
        self,
        *,
        base_url:        str = "",
        username:        str = "",
        password:        str = "",
        account_number:  str = "",
        timeout_s:       float = _DEFAULT_TIMEOUT_S,
        http_client:     Optional[Any] = None,
        sleep:           Optional[Callable[[float], None]] = None,
        daily_limit:     int = _DEFAULT_DAILY_LIMIT,
        clock:           Optional[Callable[[], Any]] = None,
        max_retries:     int = _DEFAULT_MAX_RETRIES,
    ) -> None:
        # Defaults are empty strings so the adapter can be constructed
        # for parse-only use (e.g. by the webhook receiver, which only
        # calls parse_push_payload). Send-side methods check
        # ``_send_ready`` and raise CarrierResponseError when called on
        # an adapter constructed without credentials.
        self._base_url:       str   = (base_url or "").rstrip("/")
        self._username:       str   = username or ""
        self._password:       str   = password or ""
        self._account_number: str   = account_number or ""
        self._timeout_s:      float = float(timeout_s)
        self._max_retries:    int   = int(max_retries)
        # http_client is only built lazily on the first send-side call.
        # Parse-only consumers never trigger the httpx import.
        self._client:         Any   = http_client
        self._sleep:          Callable[[float], None] = sleep or time.sleep
        self._quota:          DHLDailyQuota = DHLDailyQuota(
            daily_limit=daily_limit,
            clock=clock,
        )

    @property
    def _send_ready(self) -> bool:
        """True iff all credentials + base URL are non-empty."""
        return bool(
            self._base_url
            and self._username.strip()
            and self._password.strip()
            and self._account_number.strip()
        )

    def _require_send_ready(self) -> None:
        """Send-side methods call this first. Parse-only consumers
        constructed with default empty credentials get a clear domain
        error rather than an obscure HTTP failure."""
        if not self._send_ready:
            raise CarrierResponseError(
                "DHLExpressLiveAdapter constructed without credentials; "
                "send-side methods are unavailable. The adapter is "
                "parse-only in this configuration."
            )

    def _ensure_client(self) -> Any:
        """Lazily build the default httpx client when a send-side
        method needs it."""
        if self._client is None:
            self._client = _make_default_httpx_client()
        return self._client

    # ── Public read helpers (test surface) ──────────────────────────────────

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def quota(self) -> DHLDailyQuota:
        return self._quota

    # ── create_shipment ─────────────────────────────────────────────────────

    def create_shipment(
        self,
        request: CarrierShipmentRequest,
    ) -> RawShipmentResponse:
        self._require_send_ready()
        body = build_create_shipment_body(
            request, account_number=self._account_number,
        )
        status, payload = self._request("POST", "/shipments", json_body=body)
        if status >= 400:
            raise CarrierResponseError(
                f"DHL create_shipment {status}: {self._summarise(payload)}"
            )
        awb = (payload.get("shipmentTrackingNumber") or "").strip()
        if not awb:
            raise CarrierResponseError(
                "DHL response missing shipmentTrackingNumber"
            )
        documents = payload.get("documents") or []
        if not isinstance(documents, list) or not documents:
            raise CarrierResponseError(
                "DHL response missing label documents"
            )
        first = documents[0] or {}
        content_b64 = (first.get("content") or "").strip()
        if not content_b64:
            raise CarrierResponseError(
                "DHL response label content is empty"
            )
        try:
            label_bytes = base64.b64decode(content_b64)
        except (binascii.Error, ValueError) as exc:
            raise CarrierResponseError(
                f"DHL response label not base64: {exc}"
            ) from exc
        label_format = (first.get("imageFormat") or "pdf").lower().strip()
        return RawShipmentResponse(
            awb            = awb,
            carrier        = self.carrier,
            label_bytes    = label_bytes,
            label_format   = label_format,
            label_filename = f"{awb}.{label_format}",
            raw            = dict(payload),
        )

    # ── cancel_shipment ─────────────────────────────────────────────────────

    def cancel_shipment(
        self,
        awb: str,
        *,
        reason: str = "",
    ) -> RawCancelResponse:
        self._require_send_ready()
        if not (awb or "").strip():
            raise CarrierResponseError("awb is required")
        status, body = self._request(
            "DELETE", f"/shipments/{awb}",
            params={"requestorName": (reason or "system").strip()[:60]},
        )
        if status in (200, 204):
            return RawCancelResponse(
                carrier=self.carrier, awb=awb, accepted=True,
                reason=reason or "accepted",
                raw=dict(body) if isinstance(body, dict) else {"text": body},
            )
        if status in (404, 409):
            raw = dict(body) if isinstance(body, dict) else {"text": body}
            return RawCancelResponse(
                carrier=self.carrier, awb=awb, accepted=False,
                reason=str(raw.get("detail") or raw.get("title")
                            or f"DHL {status}"),
                raw=raw,
            )
        raise CarrierResponseError(
            f"DHL cancel_shipment {status}: {self._summarise(body)}"
        )

    # ── fetch_label ─────────────────────────────────────────────────────────

    def fetch_label(
        self,
        awb: str,
        *,
        fmt: str = "pdf",
    ) -> bytes:
        self._require_send_ready()
        if not (awb or "").strip():
            raise CarrierResponseError("awb is required")
        fmt_norm = (fmt or "pdf").lower().strip()
        if fmt_norm not in _SUPPORTED_LABEL_FMTS:
            raise CarrierResponseError(
                f"unsupported label format {fmt!r} "
                f"(supported: {sorted(_SUPPORTED_LABEL_FMTS)})"
            )
        status, body = self._request(
            "GET", f"/shipments/{awb}/image",
            params={"typeCode": "label", "imageFormat": fmt_norm.upper()},
        )
        if status >= 400:
            raise CarrierResponseError(
                f"DHL fetch_label {status}: {self._summarise(body)}"
            )
        documents = body.get("documents") or []
        if not isinstance(documents, list) or not documents:
            raise CarrierResponseError(
                "DHL fetch_label response missing documents"
            )
        first = documents[0] or {}
        content_b64 = (first.get("content") or "").strip()
        if not content_b64:
            raise CarrierResponseError(
                "DHL fetch_label response label content is empty"
            )
        try:
            return base64.b64decode(content_b64)
        except (binascii.Error, ValueError) as exc:
            raise CarrierResponseError(
                f"DHL fetch_label response not base64: {exc}"
            ) from exc

    # ── schedule_pickup ─────────────────────────────────────────────────────

    def schedule_pickup(
        self,
        awb: str,
        *,
        when_iso: str,
        location: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        self._require_send_ready()
        if not (awb or "").strip():
            raise CarrierResponseError("awb is required")
        if not (when_iso or "").strip():
            raise CarrierResponseError("when_iso is required")
        body_in: Dict[str, Any] = {
            "plannedPickupDateAndTime": when_iso,
            "accounts": [{
                "typeCode": "shipper",
                "number":   self._account_number,
            }],
            "consignmentNumber": awb,
        }
        if location:
            body_in["pickupAddress"] = dict(location)
        status, payload = self._request(
            "POST", "/pickups", json_body=body_in,
        )
        if status >= 400:
            raise CarrierResponseError(
                f"DHL schedule_pickup {status}: {self._summarise(payload)}"
            )
        return dict(payload)

    # ── HTTP transport with retries ─────────────────────────────────────────

    def _request(
        self,
        method:    str,
        path:      str,
        *,
        json_body: Optional[Dict[str, Any]] = None,
        params:    Optional[Dict[str, Any]] = None,
    ) -> Tuple[int, Any]:
        """Issue one DHL request with bounded retries.

        Returns ``(status_code, body)`` for 2xx and 4xx (non-auth, non-
        rate-limit). Raises:
          * CarrierRateLimitError — daily quota exhausted (no HTTP) or
            429 after retries.
          * CarrierAuthError      — 401 / 403.
          * CarrierTransportError — network/timeout after retries.
          * CarrierResponseError  — 5xx after retries, or malformed
            success body.
        """
        # Quota is checked BEFORE the HTTP call so a runaway retry loop
        # cannot burn the daily budget.
        self._quota.consume_or_raise()

        url = f"{self._base_url}{path}"
        # Built but never logged. Pinned by source-grep test.
        auth = (self._username, self._password)

        client = self._ensure_client()
        attempt = 0
        while True:
            try:
                resp = client.request(
                    method, url,
                    json=json_body,
                    params=params,
                    auth=auth,
                    timeout=self._timeout_s,
                )
            except CarrierAdapterError:
                raise
            except Exception as exc:
                if attempt < self._max_retries:
                    self._sleep(_RETRY_BACKOFF[
                        min(attempt, len(_RETRY_BACKOFF) - 1)
                    ])
                    attempt += 1
                    continue
                raise CarrierTransportError(
                    f"DHL transport failed after {attempt} retries: "
                    f"{type(exc).__name__}: {exc}"
                ) from exc

            status = getattr(resp, "status_code", 0)
            if status in (200, 201):
                return status, self._parse_json(resp)
            if status == 204:
                return status, {}
            if status in (401, 403):
                raise CarrierAuthError(
                    f"DHL auth failed (HTTP {status})"
                )
            if status == 429:
                if attempt < self._max_retries:
                    retry_after = self._retry_after_seconds(resp)
                    self._sleep(retry_after)
                    attempt += 1
                    continue
                raise CarrierRateLimitError(
                    f"DHL rate-limited (HTTP 429) after "
                    f"{self._max_retries} retries"
                )
            if 500 <= status < 600:
                if attempt < self._max_retries:
                    self._sleep(_RETRY_BACKOFF[
                        min(attempt, len(_RETRY_BACKOFF) - 1)
                    ])
                    attempt += 1
                    continue
                raise CarrierResponseError(
                    f"DHL server error (HTTP {status}) after "
                    f"{self._max_retries} retries"
                )
            # 4xx other than 401/403/429 — caller decides.
            return status, self._safe_parse_json(resp)

    # ── Response helpers ────────────────────────────────────────────────────

    @staticmethod
    def _parse_json(resp: Any) -> Dict[str, Any]:
        """Parse a 2xx response body. Malformed → CarrierResponseError."""
        try:
            payload = resp.json()
        except Exception as exc:
            raise CarrierResponseError(
                f"DHL response body is not valid JSON: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise CarrierResponseError(
                f"DHL response body is not a JSON object "
                f"(got {type(payload).__name__})"
            )
        return payload

    @staticmethod
    def _safe_parse_json(resp: Any) -> Any:
        """Parse a 4xx response body without raising — used so domain
        methods (cancel_shipment) can inspect the body and translate
        to a domain-level signal."""
        try:
            payload = resp.json()
            if isinstance(payload, dict):
                return payload
            return {"text": payload}
        except Exception:
            text = getattr(resp, "text", "")
            return {"text": text}

    @staticmethod
    def _retry_after_seconds(resp: Any) -> float:
        """Decode a Retry-After header. Falls back to 1.0s when absent
        or malformed."""
        headers = getattr(resp, "headers", {}) or {}
        try:
            raw = headers.get("Retry-After") or headers.get("retry-after") or ""
        except AttributeError:
            raw = ""
        try:
            return max(0.0, float(raw))
        except (ValueError, TypeError):
            return 1.0

    @staticmethod
    def _summarise(payload: Any) -> str:
        """Tight one-line summary of a 4xx body for error messages.
        Truncates at 200 chars so log lines stay scannable."""
        try:
            s = json.dumps(payload, default=str, sort_keys=True)
        except Exception:
            s = str(payload)
        if len(s) > 200:
            s = s[:197] + "..."
        return s

    # ── Parse a single-shipment webhook body ───────────────────────────────

    def parse_webhook_event(
        self,
        body: bytes,
        headers: Optional[Mapping[str, str]] = None,
    ) -> CarrierEvent:
        """Parse a single-shipment webhook body into one ``CarrierEvent``.

        Used for unit-test parity with the stub adapter; production
        DHL pushes carry a ``shipments[]`` array and should be parsed
        via :meth:`parse_push_payload`.

        Raises :class:`CarrierResponseError` for empty / non-JSON /
        non-object bodies and for shipments missing required fields.
        """
        payload = self._decode_object(body)
        # If the body has a shipments[] envelope, take the first row
        # and parse it. That keeps this method useful as a Protocol-
        # compatible fallback for tests.
        if "shipments" in payload:
            ships = payload.get("shipments") or []
            if not isinstance(ships, list) or not ships:
                raise CarrierResponseError(
                    "DHLExpressLiveAdapter: shipments[] is empty"
                )
            shipment = ships[0]
        else:
            shipment = payload
        ev = self._parse_one_shipment(shipment, raw_headers=bool(headers))
        if ev is None:
            raise CarrierResponseError(
                "DHLExpressLiveAdapter: shipment missing required fields "
                "(id / status.timestamp / status.statusCode)"
            )
        return ev

    # ── Parse a full DHL push envelope ────────────────────────────────────

    def parse_push_payload(
        self,
        body: bytes,
        headers: Optional[Mapping[str, str]] = None,
    ) -> Tuple[List[CarrierEvent], int]:
        """Parse the DHL push envelope into a list of ``CarrierEvent``.

        Returns ``(events, dropped_count)``. ``dropped_count`` is the
        number of shipments that lacked required fields and were
        skipped — the caller may surface this in a warning timeline
        event but should NOT 5xx (DHL retry-budget protection).

        Raises :class:`CarrierResponseError` for envelope-level
        failures (empty body, non-JSON, non-object, missing
        ``shipments`` array). Per-shipment validation failures are
        non-fatal.
        """
        payload = self._decode_object(body)
        ships = payload.get("shipments")
        if not isinstance(ships, list):
            raise CarrierResponseError(
                "DHLExpressLiveAdapter: payload missing 'shipments' array"
            )
        events: List[CarrierEvent] = []
        dropped = 0
        for shipment in ships:
            if not isinstance(shipment, dict):
                dropped += 1
                continue
            ev = self._parse_one_shipment(shipment, raw_headers=bool(headers))
            if ev is None:
                dropped += 1
                continue
            events.append(ev)
        return events, dropped

    # ── Internal helpers ──────────────────────────────────────────────────

    @staticmethod
    def _decode_object(body: bytes) -> Dict[str, Any]:
        """Decode and validate the top-level body shape."""
        if not body:
            raise CarrierResponseError(
                "DHLExpressLiveAdapter: empty webhook body"
            )
        try:
            payload = json.loads(body)
        except (ValueError, TypeError) as exc:
            raise CarrierResponseError(
                f"DHLExpressLiveAdapter: invalid JSON in webhook body: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise CarrierResponseError(
                "DHLExpressLiveAdapter: webhook body must be a JSON object, "
                f"got {type(payload).__name__}"
            )
        return payload

    @staticmethod
    def _parse_one_shipment(
        shipment: Dict[str, Any],
        *,
        raw_headers: bool,
    ) -> Optional[CarrierEvent]:
        """Convert one shipment dict into a ``CarrierEvent`` or None
        if required fields are missing."""
        awb = (shipment.get("id") or "").strip()
        status = shipment.get("status") or {}
        if not isinstance(status, dict):
            return None
        status_code = (status.get("statusCode") or "").strip()
        timestamp   = (status.get("timestamp")  or "").strip()
        if not awb or not status_code or not timestamp:
            return None
        location    = (status.get("location")    or "").strip()
        description = (
            status.get("description")
            or status.get("status")
            or ""
        ).strip()
        return CarrierEvent(
            carrier      = CARRIER_DHL,
            awb          = awb,
            event_code   = status_code,
            occurred_at  = timestamp,
            location     = location,
            description  = description,
            raw          = {
                "live":         True,
                "carrier":      CARRIER_DHL,
                "headers_seen": raw_headers,
                "shipment":     dict(shipment),
            },
        )
