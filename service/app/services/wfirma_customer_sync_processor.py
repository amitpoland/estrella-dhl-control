"""
Phase 3 — wFirma contractor snapshot + customer_master enrichment.

For each event that has a completed invoice snapshot, extracts
contractor_id from the stored invoice XML, fetches the contractor
profile from wFirma (read-only), stores an immutable customer
snapshot in wfirma_customer_snapshots, and enriches customer_master
via upsert_identity_only() (fill-when-empty semantics).

Called exclusively from wfirma_webhook_scheduler._run_customer_sync_tick().
Never raises — all exceptions are caught and produce "CUSTOMER_SYNC_FAILED".

State tracking columns on wfirma_webhook_processing:
  customer_synced_at      TEXT — ISO timestamp on success/skip; NULL = not done
  customer_sync_error     TEXT — last error message (truncated to 300 chars)
  customer_sync_attempts  INTEGER DEFAULT 0 — attempts so far; capped at MAX
"""
from __future__ import annotations

import json
import logging
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


def _extract_contractor_id_from_xml(raw_xml: str) -> Optional[str]:
    """
    Return the wFirma contractor numeric ID from a stored invoice XML, or None.

    The invoice XML embeds the buyer contractor as:
      <invoice>
        <contractor>
          <id>173845539</id>
          ...
        </contractor>
      </invoice>

    Returns None when the element is absent, empty, or equals "0"
    (wFirma uses 0 as the null sentinel for no receiver).
    """
    try:
        root = ET.fromstring(raw_xml)
    except ET.ParseError:
        return None
    invoice_node = root.find(".//invoice")
    if invoice_node is None:
        return None
    contractor_node = invoice_node.find("contractor")
    if contractor_node is None:
        return None
    id_el = contractor_node.find("id")
    if id_el is None:
        return None
    val = (id_el.text or "").strip()
    return val if val and val != "0" else None


def sync_customer_from_snapshot(
    *,
    event_id: str,
    proc_db: Path,
    cm_db: Path,
    now: str,
) -> str:
    """
    Full contractor fetch + customer_master upsert for one event.

    Steps:
      1. Read raw_xml from wfirma_invoice_snapshots.
      2. Extract <contractor><id> from invoice XML.
      3. Call fetch_contractor_by_id() — READ-ONLY wFirma GET.
      4. Store immutable row in wfirma_customer_snapshots.
      5. Call upsert_identity_only() on customer_master.
      6. Set customer_synced_at in wfirma_webhook_processing.

    Returns one of:
      "CUSTOMER_SYNCED"        happy path: contractor fetched + CM updated
      "CUSTOMER_SYNC_SKIPPED"  no contractor_id in XML, or contractor missing
                               name/country — recorded as success, no retry
      "CUSTOMER_SYNC_FAILED"   any error — caller increments attempt counter
    """
    from .wfirma_processing_db import (
        get_snapshot_by_event,
        insert_customer_snapshot,
        set_customer_sync_success,
        increment_customer_sync_attempts,
    )
    from .wfirma_client import fetch_contractor_by_id
    from .customer_master_db import upsert_identity_only

    # ── Step 1: load invoice snapshot ─────────────────────────────────────────
    snapshot = get_snapshot_by_event(proc_db, event_id)
    if snapshot is None:
        log.warning("customer_sync: no invoice snapshot for event_id=%s", event_id)
        increment_customer_sync_attempts(
            proc_db, event_id, "invoice_snapshot_missing", now
        )
        return "CUSTOMER_SYNC_FAILED"

    raw_xml = snapshot.get("raw_xml") or ""
    if not raw_xml:
        log.warning("customer_sync: empty raw_xml for event_id=%s", event_id)
        increment_customer_sync_attempts(
            proc_db, event_id, "raw_xml_empty", now
        )
        return "CUSTOMER_SYNC_FAILED"

    # ── Step 2: extract contractor_id from stored XML ─────────────────────────
    contractor_id = _extract_contractor_id_from_xml(raw_xml)
    if not contractor_id:
        log.info(
            "customer_sync: no contractor_id in invoice XML event_id=%s — skipped",
            event_id,
        )
        set_customer_sync_success(proc_db, event_id, now, skipped=True)
        return "CUSTOMER_SYNC_SKIPPED"

    # ── Step 3: fetch contractor from wFirma (read-only GET) ──────────────────
    try:
        result = fetch_contractor_by_id(contractor_id)
    except Exception as exc:
        log.warning(
            "customer_sync: fetch_contractor_by_id raised event_id=%s contractor_id=%s: %s",
            event_id, contractor_id, exc,
        )
        increment_customer_sync_attempts(
            proc_db, event_id, f"fetch_exception:{exc}"[:300], now
        )
        return "CUSTOMER_SYNC_FAILED"

    if not result.ok:
        log.warning(
            "customer_sync: fetch_contractor_by_id not ok event_id=%s contractor_id=%s: %s",
            event_id, contractor_id, result.error,
        )
        increment_customer_sync_attempts(
            proc_db, event_id, (result.error or "fetch_failed")[:300], now
        )
        return "CUSTOMER_SYNC_FAILED"

    # ── Step 4: store immutable customer snapshot ─────────────────────────────
    snapshot_id = str(uuid.uuid4())
    snap_fields = {
        "contractor_id": result.contractor_id or contractor_id,
        "name":          result.name or "",
        "nip":           result.nip or "",
        "country":       result.country or "",
        "email":         result.email or "",
        "phone":         result.phone or "",
        "mobile":        result.mobile or "",
        "street":        result.street or "",
        "city":          result.city or "",
        "zip":           result.zip or "",
        "regon":         result.regon or "",
        "bank_account":  result.account_number or "",
        "payment_days":  result.payment_days or "",
        "language_id":   result.translation_language_id or "",
    }
    try:
        insert_customer_snapshot(
            proc_db,
            snapshot_id=snapshot_id,
            event_id=event_id,
            contractor_id=contractor_id,
            fetched_at=now,
            raw_json=json.dumps(snap_fields, ensure_ascii=False),
            fields=snap_fields,
        )
    except Exception as exc:
        log.warning(
            "customer_sync: snapshot insert error event_id=%s: %s", event_id, exc
        )
        increment_customer_sync_attempts(
            proc_db, event_id, f"snapshot_insert:{exc}"[:300], now
        )
        return "CUSTOMER_SYNC_FAILED"

    # ── Step 5: enrich customer_master ────────────────────────────────────────
    name = (result.name or "").strip()
    country = (result.country or "").strip().upper()

    if not name or not country or len(country) != 2:
        log.info(
            "customer_sync: contractor %s missing name=%r or country=%r — skip CM upsert event_id=%s",
            contractor_id, result.name, result.country, event_id,
        )
        set_customer_sync_success(proc_db, event_id, now, skipped=True)
        return "CUSTOMER_SYNC_SKIPPED"

    payment_terms_days: Optional[int] = None
    if result.payment_days:
        try:
            payment_terms_days = int(result.payment_days)
        except (TypeError, ValueError):
            pass

    try:
        upsert_identity_only(
            cm_db,
            bill_to_contractor_id=contractor_id,
            bill_to_name=name,
            country=country,
            nip=result.nip or None,
            bill_to_email=result.email or None,
            bill_to_phone=result.phone or None,
            bill_to_mobile=result.mobile or None,
            bank_account=result.account_number or None,
            payment_terms_days=payment_terms_days,
            default_language_id=result.translation_language_id or None,
            bill_to_street=result.street or None,
            bill_to_city=result.city or None,
            bill_to_postal_code=result.zip or None,
            regon=result.regon or None,
            sync_source="webhook",
        )
    except Exception as exc:
        log.warning(
            "customer_sync: upsert_identity_only error event_id=%s contractor_id=%s: %s",
            event_id, contractor_id, exc,
        )
        increment_customer_sync_attempts(
            proc_db, event_id, f"upsert_error:{exc}"[:300], now
        )
        return "CUSTOMER_SYNC_FAILED"

    # ── Step 6: mark success ──────────────────────────────────────────────────
    set_customer_sync_success(proc_db, event_id, now, skipped=False)
    log.info(
        "customer_sync: CUSTOMER_SYNCED event_id=%s contractor_id=%s name=%r",
        event_id, contractor_id, name,
    )
    return "CUSTOMER_SYNCED"
