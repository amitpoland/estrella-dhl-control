"""
InvoiceSnapshotProcessor — Phase 2A.1

Processes a single wFirma Faktury.* webhook event:
  1. Calls fetch_invoice_xml() (read-only wFirma GET)
  2. Parses XML into structured metadata
  3. Stores one immutable snapshot in wfirma_invoice_snapshots

Constraints
-----------
- READ-ONLY with respect to wFirma (fetch only, no writes)
- No business-table writes (no proforma_drafts, no wfirma.db)
- Idempotent: duplicate call for same event_id stores nothing (INSERT OR IGNORE)

Raises RuntimeError or ConnectionError on fetch failure — caller handles retry logic.
"""
from __future__ import annotations

import json
import logging
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


# ── XML helpers ────────────────────────────────────────────────────────────────


def _find_text(node: Optional[ET.Element], tag: str) -> str:
    if node is None:
        return ""
    el = node.find(tag)
    return (el.text or "").strip() if el is not None else ""


def _parse_invoice_xml(xml_text: str) -> dict:
    """
    Extract flat invoice metadata from wFirma XML response.
    Defensive — returns empty strings for missing elements; never raises.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return {}

    node = root.find(".//invoice")

    def _t(*tags: str) -> str:
        for tag in tags:
            v = _find_text(node, tag)
            if v:
                return v
        return ""

    return {
        "invoice_number": _t("fullnumber", "full_number", "number"),
        "document_type":  _t("type"),
        "currency":       _t("currency"),
        "net_amount":     _t("netto", "net"),
        "gross_amount":   _t("brutto", "gross"),
        "vat_amount":     _t("vat_sum", "vat_total"),
        "issue_date":     _t("date"),
        "sale_date":      _t("saledate", "sale_date"),
        "payment_due":    _t("paymentdate", "payment_date"),
        "payment_method": _t("paymentmethod", "payment_method"),
        "status":         _t("status"),
    }


def _extract_object_id(payload_json: str) -> Optional[str]:
    """
    Best-effort extraction of the wFirma invoice id from the webhook payload JSON.
    Tries the most common field names used by wFirma Faktury.* events.
    Returns None when no recognised field is found.
    """
    try:
        payload = json.loads(payload_json)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    return (
        payload.get("invoice_id")
        or payload.get("object_id")
        or payload.get("faktury_id")
        or None
    )


# ── Processor ─────────────────────────────────────────────────────────────────


class InvoiceSnapshotProcessor:
    """
    Processes Faktury.* webhook events by fetching wFirma XML and storing
    an immutable snapshot. One processor instance per scheduler tick.

    proc_db_path — path to wfirma_processing.db (created by wfirma_processing_db.init_db)
    """

    def __init__(self, proc_db_path: Path) -> None:
        self.proc_db_path = proc_db_path

    def process(
        self,
        event_id: str,
        object_id: str,
        payload_json: str,
        now: str,
    ) -> None:
        """
        Fetch XML for object_id and store one immutable snapshot.

        Raises RuntimeError on wFirma API error.
        Raises ConnectionError on network failure.
        Caller (scheduler) handles retry on any exception.
        """
        from .wfirma_client import fetch_invoice_xml
        from .wfirma_processing_db import insert_snapshot

        log.info(
            "wfirma_snapshot: fetching xml event_id=%s object_id=%s",
            event_id, object_id,
        )
        xml_text = fetch_invoice_xml(object_id)

        parsed = _parse_invoice_xml(xml_text)
        snapshot_id = str(uuid.uuid4())

        inserted = insert_snapshot(
            db_path=self.proc_db_path,
            snapshot_id=snapshot_id,
            event_id=event_id,
            object_id=object_id,
            fetched_at=now,
            raw_xml=xml_text,
            parsed=parsed,
            raw_payload=payload_json,
        )

        if inserted:
            log.info(
                "wfirma_snapshot: stored snapshot_id=%s event_id=%s "
                "object_id=%s invoice=%s",
                snapshot_id, event_id, object_id, parsed.get("invoice_number"),
            )
        else:
            log.info(
                "wfirma_snapshot: duplicate skipped event_id=%s object_id=%s",
                event_id, object_id,
            )
