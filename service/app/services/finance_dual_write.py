"""
finance_dual_write.py — Phase 6F.5 — Proforma /post → finance_postings dual-write.

> **STATUS: WRITE-BEARING. FEATURE-FLAGGED. DEFAULT OFF.**
>
> When ``settings.finance_dual_write_enabled`` is True, ``dual_write_proforma_post``
> writes a synthetic ``postings`` row + zero-or-more ``charges`` rows into
> ``<storage_root>/finance_postings.sqlite`` AFTER the legacy ``mark_post_succeeded``
> commit returns. When ``finance_dual_write_shadow`` is True, the function computes
> the payload + sha1 keys and logs at INFO without persisting.
>
> Approval package: ``tasks/phase-6f-5-dual-write-approval-package.md``.
>
> Hard guarantees (enforced by callers + source-grep contract tests):
>   - The function is invoked ONLY after ``mark_post_succeeded`` returns.
>   - The function NEVER raises. Any exception is logged at WARNING and
>     swallowed. The caller's response is unaffected.
>   - The function NEVER mutates ``proforma_service_charges`` (legacy table).
>   - The function NEVER calls wFirma / FX / settlement / PZ engines.
>   - Default OFF: if the flag is False, the function returns immediately
>     without opening the finance DB file.
>
> Idempotency:
>   - charges:  ``[live:sha1=<sha1("live_psc:<batch>:<client>:<type>")>]`` prefix in
>               ``charges.notes``. Re-runs skip existing rows.
>   - postings: ``LIVE-<sha1("live_psc_posting:<batch>:<client>")[:16]>`` in
>               ``postings.wfirma_invoice_id``. Re-runs reuse the row.
>   - Namespaces are sha1-disjoint AND prefix-disjoint from 6F.2.a backfill
>     (``BACKFILL-`` / ``[backfill:sha1=...]``) and from real wFirma postings
>     (numeric / unprefixed). They cannot collide.
>
> Monetary safety:
>   - Amount conversion uses ``Decimal(str(amount)) * 100`` quantized
>     ``ROUND_HALF_EVEN``. Direct ``int(amount * 100)`` is FORBIDDEN.
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_EVEN
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import finance_postings_db as fpdb
from . import commercial_charge_authority


log = logging.getLogger(__name__)


# ── Constants ────────────────────────────────────────────────────────────────

#: Prefix for the live dual-write synthetic posting ``wfirma_invoice_id``.
#: MUST stay distinct from 6F.2.a's ``BACKFILL-`` prefix and from real
#: numeric wFirma invoice ids.
POSTING_LIVE_PREFIX = "LIVE-"

#: Prefix written into ``charges.notes`` so that dual-write rows are
#: detectable for idempotency probes and rollback.
CHARGES_LIVE_NOTE_PREFIX = "[live:sha1="

#: Allow-list of legacy charge types accepted by the proforma editor.
#: Mirrors ``proforma_service_charges_db.ALLOWED_CHARGE_TYPES``. Any other
#: value in the source draft is SKIPPED with a WARNING (never written).
_LEGACY_TO_NEW_CHARGE_TYPES: Dict[str, str] = {
    "freight":   "freight",
    "insurance": "insurance",
}


# ── Pure data shaping ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class _ChargeRow:
    """Internal representation of one charge tuple ready for insert."""
    batch_id:        str
    client_name:     str
    charge_type:     str
    amount_minor:    int
    currency:        str
    idempotency_sha1: str
    original_note:   str

    @property
    def notes(self) -> str:
        prefix = f"{CHARGES_LIVE_NOTE_PREFIX}{self.idempotency_sha1}]"
        if self.original_note:
            return f"{prefix}\n{self.original_note}"
        return prefix


@dataclass(frozen=True)
class _DualWritePayload:
    batch_id:             str
    client_name:          str
    currency:             str
    full_number:          str
    synthetic_posting_id: str
    charges:              Tuple[_ChargeRow, ...]
    issued_total_minor:   int


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _amount_to_minor(amount: Any) -> int:
    """Decimal-safe float → minor units (e.g. 3.49 → 349).

    Uses Decimal + ROUND_HALF_EVEN. NEVER ``int(amount * 100)`` — that would
    silently truncate half-cent values. Mirrors the Lesson-A-safe contract
    used in ``service/scripts/backfill_finance_postings.py``.
    """
    d = Decimal(str(amount))
    minor = (d * 100).quantize(Decimal("1"), rounding=ROUND_HALF_EVEN)
    return int(minor)


def _sha1_hex(material: str) -> str:
    return hashlib.sha1(material.encode("utf-8")).hexdigest()


def _idempotency_charge_sha1(batch_id: str, client_name: str, charge_type: str) -> str:
    return _sha1_hex(f"live_psc:{batch_id}:{client_name}:{charge_type}")


def _synthetic_posting_id(batch_id: str, client_name: str) -> str:
    h = _sha1_hex(f"live_psc_posting:{batch_id}:{client_name}")
    return f"{POSTING_LIVE_PREFIX}{h[:16]}"


def _build_payload(
    *,
    batch_id: str,
    client_name: str,
    currency: str,
    full_number: str,
    service_charges_json: Optional[str],
) -> Optional[_DualWritePayload]:
    """Shape the dual-write payload from posted-draft data.

    Returns None if mandatory fields are missing (caller skips with WARNING).
    """
    if not batch_id or not client_name:
        return None
    currency = (currency or "").strip().upper()
    if not currency:
        return None

    raw_list: List[Dict[str, Any]] = []
    if service_charges_json:
        try:
            parsed = json.loads(service_charges_json)
            if isinstance(parsed, list):
                raw_list = parsed
        except Exception:
            raw_list = []

    out: List[_ChargeRow] = []
    total_minor = 0
    for raw in raw_list:
        if not isinstance(raw, dict):
            continue
        ct = (raw.get("charge_type") or "").strip().lower()
        if ct not in _LEGACY_TO_NEW_CHARGE_TYPES:
            log.warning(
                "finance_dual_write skipping unknown charge_type=%s batch=%s client=%s",
                ct, batch_id, client_name,
            )
            continue
        # PR-6 — never post an UNRESOLVED charge: the wFirma document excludes it,
        # so finance must too (even if a stale amount lingers on the row). Keeps
        # the finance posting in lockstep with the commercial authority.
        if ((raw.get("resolution") or "").strip().lower()
                == commercial_charge_authority.RESOLUTION_UNRESOLVED):
            continue
        mapped_type = _LEGACY_TO_NEW_CHARGE_TYPES[ct]
        amount = raw.get("amount")
        if amount is None:
            continue
        try:
            minor = _amount_to_minor(amount)
        except Exception as exc:
            log.warning(
                "finance_dual_write amount parse failed batch=%s client=%s type=%s err=%s",
                batch_id, client_name, mapped_type, exc,
            )
            continue
        if minor == 0:
            continue
        ccy = (raw.get("currency") or currency or "").strip().upper() or currency
        sha = _idempotency_charge_sha1(batch_id, client_name, mapped_type)
        out.append(_ChargeRow(
            batch_id=batch_id,
            client_name=client_name,
            charge_type=mapped_type,
            amount_minor=minor,
            currency=ccy,
            idempotency_sha1=sha,
            original_note=(raw.get("note") or "").strip(),
        ))
        total_minor += minor

    return _DualWritePayload(
        batch_id=batch_id,
        client_name=client_name,
        currency=currency,
        full_number=full_number or "",
        synthetic_posting_id=_synthetic_posting_id(batch_id, client_name),
        charges=tuple(out),
        issued_total_minor=total_minor,
    )


# ── Idempotency probes (read-only) ───────────────────────────────────────────

def _find_existing_posting_id(db_path: Path, wfirma_invoice_id: str) -> Optional[int]:
    """Read-only probe. Returns existing posting id or None."""
    if not Path(db_path).exists():
        return None
    try:
        with sqlite3.connect(str(db_path)) as c:
            row = c.execute(
                "SELECT id FROM postings WHERE wfirma_invoice_id=?",
                (wfirma_invoice_id,),
            ).fetchone()
    except sqlite3.OperationalError:
        return None
    return int(row[0]) if row else None


def _charge_already_present(db_path: Path, idempotency_sha1: str) -> bool:
    if not Path(db_path).exists():
        return False
    try:
        with sqlite3.connect(str(db_path)) as c:
            row = c.execute(
                "SELECT id FROM charges WHERE notes LIKE ? LIMIT 1",
                (f"{CHARGES_LIVE_NOTE_PREFIX}{idempotency_sha1}]%",),
            ).fetchone()
    except sqlite3.OperationalError:
        return False
    return row is not None


# ── Public entrypoint ────────────────────────────────────────────────────────

def dual_write_proforma_post(
    *,
    db_path: Path,
    batch_id: str,
    client_name: str,
    currency: str,
    full_number: str,
    service_charges_json: Optional[str],
    enabled: bool,
    shadow: bool,
) -> Dict[str, Any]:
    """Idempotently dual-write one proforma post event to finance_postings.

    All arguments are explicit (no implicit settings read) so the function is
    fully testable. The caller (routes_proforma) is responsible for reading
    the two flags from ``settings`` and passing them through.

    Returns a small dict summarising the result. NEVER raises. On any
    exception, logs at WARNING and returns ``{"ok": False, "reason": "..."}``.

    Args:
        db_path: target ``finance_postings.sqlite`` path.
        batch_id, client_name, currency, full_number: drawn from the posted
            draft (``mark_post_succeeded`` return value).
        service_charges_json: the draft's raw service_charges_json string
            (may be empty/None — empty produces 0 charge rows but still
            creates the synthetic posting).
        enabled: ``settings.finance_dual_write_enabled``.
        shadow:  ``settings.finance_dual_write_shadow``.
    """
    # --- Flag check FIRST. Must precede any DB open / payload build / log. --
    if not enabled:
        return {"ok": True, "skipped": True, "reason": "flag_off"}

    try:
        payload = _build_payload(
            batch_id=batch_id,
            client_name=client_name,
            currency=currency,
            full_number=full_number,
            service_charges_json=service_charges_json,
        )
    except Exception as exc:
        log.warning(
            "finance_dual_write payload build failed draft batch=%s client=%s err=%s",
            batch_id, client_name, exc,
        )
        return {"ok": False, "reason": f"payload_build_failed: {exc}"}

    if payload is None:
        log.info(
            "finance_dual_write skipped: missing batch_id/client/currency batch=%s client=%s",
            batch_id, client_name,
        )
        return {"ok": True, "skipped": True, "reason": "missing_fields"}

    # --- Shadow mode: log + return without persisting. ---------------------
    if shadow:
        for ch in payload.charges:
            log.info(
                "finance_dual_write_shadow batch_id=%s client=%s charge_type=%s "
                "amount_minor=%d currency=%s sha1=%s would_skip=%s "
                "target_posting_id=%s",
                ch.batch_id, ch.client_name, ch.charge_type, ch.amount_minor,
                ch.currency, ch.idempotency_sha1,
                _charge_already_present(db_path, ch.idempotency_sha1),
                payload.synthetic_posting_id,
            )
        log.info(
            "finance_dual_write_shadow posting batch=%s client=%s currency=%s "
            "issued_total_minor=%d synthetic_posting_id=%s",
            payload.batch_id, payload.client_name, payload.currency,
            payload.issued_total_minor, payload.synthetic_posting_id,
        )
        return {
            "ok": True,
            "mode": "shadow",
            "synthetic_posting_id": payload.synthetic_posting_id,
            "charge_count": len(payload.charges),
        }

    # --- Live mode: open separate DB connection and persist idempotently. --
    try:
        fpdb.init_db(db_path)
    except Exception as exc:
        log.warning(
            "finance_dual_write init_db failed batch=%s client=%s err=%s",
            payload.batch_id, payload.client_name, exc,
        )
        return {"ok": False, "reason": f"init_db_failed: {exc}"}

    try:
        existing_posting_id = _find_existing_posting_id(db_path, payload.synthetic_posting_id)
        if existing_posting_id is None:
            posting = fpdb.create_posting(db_path, {
                "batch_id":           payload.batch_id,
                "client_name":        payload.client_name,
                "wfirma_invoice_id":  payload.synthetic_posting_id,
                "wfirma_doc_number":  payload.full_number,
                "posting_kind":       "proforma",
                "posted_at":          _now_utc(),
                "issued_total_minor": payload.issued_total_minor,
                "currency":           payload.currency,
            })
            posting_id = posting.id
            created_posting = True
        else:
            posting_id = existing_posting_id
            created_posting = False

        created_charges = 0
        skipped_charges = 0
        for ch in payload.charges:
            if _charge_already_present(db_path, ch.idempotency_sha1):
                skipped_charges += 1
                continue
            fpdb.create_charge(db_path, {
                "batch_id":     ch.batch_id,
                "client_name":  ch.client_name,
                "charge_type":  ch.charge_type,
                "amount_minor": ch.amount_minor,
                "currency":     ch.currency,
                "source":       "operator",
                "posting_id":   posting_id,
                "notes":        ch.notes,
            })
            created_charges += 1

        log.info(
            "finance_dual_write committed batch=%s client=%s synthetic_posting=%s "
            "posting_id=%d created_posting=%s created_charges=%d skipped_charges=%d",
            payload.batch_id, payload.client_name, payload.synthetic_posting_id,
            posting_id, created_posting, created_charges, skipped_charges,
        )
        return {
            "ok": True,
            "mode": "live",
            "posting_id": posting_id,
            "synthetic_posting_id": payload.synthetic_posting_id,
            "created_posting": created_posting,
            "created_charges": created_charges,
            "skipped_charges": skipped_charges,
        }

    except Exception as exc:
        # Failure isolation: never raise to caller. The legacy commit has
        # already succeeded and the operator-facing response is unaffected.
        log.warning(
            "finance_dual_write_failed batch=%s client=%s err=%s",
            payload.batch_id, payload.client_name, exc,
        )
        return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}


__all__ = [
    "dual_write_proforma_post",
    "POSTING_LIVE_PREFIX",
    "CHARGES_LIVE_NOTE_PREFIX",
]
