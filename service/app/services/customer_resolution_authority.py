"""customer_resolution_authority.py — derive customer resolution from the
packing-upload selection authority chain.

When the operator uploads a sales packing list, they pick the client from
Customer Master via the intake dropdown. That selection is persisted in
``packing_contractor_resolution`` (status=``confirmed``, role=``client``,
matched_master_type=``customer_master``, matched_master_id=<wFirma
contractor_id>). At readiness check time, the proforma draft's free-text
``client_name`` may differ from the master record's ``bill_to_name`` (e.g.
operator typed "DiamondGroup GmbH" while the master row is "DG GmbH" with
NIP DE266491614 → wFirma contractor 52808306). The pre-existing name-only
``_resolve_customer`` in routes_proforma.py would return ``found=False`` in
that case and produce a false-positive "unresolved customer" blocker.

This module is the authority chain: **the operator's packing-upload
selection outranks every name-based fallback.** NIP and contractor_id
outrank display name. Display-name divergence becomes an advisory note,
never a blocker.

Designed as a pure read-only function. No I/O writes. No mutation of
either database. Returns ``None`` when no packing-master selection exists;
callers fall through to their existing name-matching logic.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional


_VALID_CONFIRMED_STATUSES = ("confirmed",)
_VALID_MASTER_TYPE        = "customer_master"


def _normalise_matched_master_id(raw: Any) -> str:
    """Polymorphic-input normaliser (Lesson A pattern) for the
    ``packing_contractor_resolution.matched_master_id`` column.

    SQLite stores this column with dynamic affinity. Production rows in
    ``packing_resolutions.sqlite`` carry INTEGER values (e.g. ``52808306``),
    not TEXT. Calling ``.strip()`` on an int raises ``AttributeError`` —
    the helper would then bubble the exception up to the caller, hit the
    ``_resolve_customer`` try/except fallback in routes_proforma.py, and
    silently never resolve via packing-master authority.

    Coerce to str regardless of input type. Mirrors the
    ``_normalise_recipient`` precedent for builder→consumer polymorphic
    inputs (Lesson A, ``service/app/services/dhl_proactive_dispatch_p2.py``).
    """
    if raw is None:
        return ""
    if isinstance(raw, int):
        return str(raw)
    if isinstance(raw, str):
        return raw.strip()
    # Defensive: anything else (float, bytes, etc.) — coerce via str()
    return str(raw).strip()


def _normalize_name(s: Optional[str]) -> str:
    """Case-insensitive whitespace-collapsed comparison key.

    Mirrors the lighter normalisation used by the existing name resolver
    in routes_proforma.py (``_normalize_client_name``) so the "names
    differ?" advisory test is consistent with the rest of the system.
    """
    if not s:
        return ""
    return " ".join(s.strip().split()).lower()


def derive_customer_resolution_via_packing(
    *,
    batch_id: Optional[str],
    client_name: Optional[str],
    customer_master_db_path: Path,
    packing_resolution_db_path: Path,
) -> Optional[Dict[str, Any]]:
    """Return a resolution dict when the packing upload already selected a
    Customer Master client for this batch; ``None`` otherwise.

    The returned dict shape::

        {
          "wfirma_customer_id":      str,
          "resolved_master_name":    str,   # customer_master.bill_to_name
          "customer_master_id":      int,   # customer_master.id
          "parsed_packing_name":     str,   # packing_contractor_resolution.parsed_name
          "parsed_packing_nip":      str,   # packing_contractor_resolution.parsed_tax_id
          "parsed_packing_country":  str,
          "matched_master_id":       str,   # raw value from packing_contractor_resolution
          "match_strategy":          "packing_master",
          "advisory":                str | "",  # operator-facing note when proforma
                                                 # client_name differs from master name
        }

    Returns ``None`` when:
      * batch_id is empty
      * packing_resolutions DB is missing
      * no confirmed client-role packing resolution exists for the batch
      * the resolution did not match against ``customer_master``
      * the matched customer_master row no longer exists
      * the customer_master row has no ``bill_to_contractor_id`` (= no
        wFirma contractor mapping — falls through to other resolvers
        rather than asserting authority with a missing wFirma id)

    No exceptions are raised under normal operation. Database errors
    propagate to the caller, which is expected to wrap with try/except
    (the production readiness path always does).
    """
    if not (batch_id or "").strip():
        return None
    pr_path = Path(packing_resolution_db_path)
    cm_path = Path(customer_master_db_path)
    if not pr_path.is_file() or not cm_path.is_file():
        return None

    # 1. Find the confirmed client-role packing resolution for this batch.
    with sqlite3.connect(str(pr_path)) as pr_conn:
        pr_conn.row_factory = sqlite3.Row
        row = pr_conn.execute(
            "SELECT * FROM packing_contractor_resolution "
            "WHERE batch_id = ? AND role = 'client'",
            (batch_id.strip(),),
        ).fetchone()
    if row is None:
        return None

    if (row["status"] or "").strip() not in _VALID_CONFIRMED_STATUSES:
        return None
    if (row["matched_master_type"] or "").strip() != _VALID_MASTER_TYPE:
        return None
    # ── Lesson A: matched_master_id is sometimes stored as INTEGER in
    # production (sqlite affinity), not TEXT. Normalise to str via the
    # _normalise_X pattern from CLAUDE.md / Engineering Lessons / Lesson A.
    matched_master_id = _normalise_matched_master_id(row["matched_master_id"])
    if not matched_master_id:
        return None

    # 2. Look up the customer_master row. The packing layer historically
    #    stores ``matched_master_id`` as the wFirma ``bill_to_contractor_id``
    #    (TEXT in customer_master.sqlite), not the customer_master.id
    #    surrogate. We accept either, with bill_to_contractor_id winning
    #    because that's the operator-confirmed selection and what the
    #    downstream wFirma proforma needs.
    with sqlite3.connect(str(cm_path)) as cm_conn:
        cm_conn.row_factory = sqlite3.Row
        cm_row = cm_conn.execute(
            "SELECT id, bill_to_contractor_id, bill_to_name, country, nip "
            "FROM customer_master WHERE bill_to_contractor_id = ?",
            (matched_master_id,),
        ).fetchone()
        if cm_row is None:
            # Fallback: try as a numeric customer_master.id (defensive — the
            # packing layer SHOULD use bill_to_contractor_id but tolerate
            # the alternative).
            try:
                cm_row = cm_conn.execute(
                    "SELECT id, bill_to_contractor_id, bill_to_name, country, nip "
                    "FROM customer_master WHERE id = ?",
                    (int(matched_master_id),),
                ).fetchone()
            except ValueError:
                cm_row = None
    if cm_row is None:
        return None

    wfirma_contractor_id = (cm_row["bill_to_contractor_id"] or "").strip()
    if not wfirma_contractor_id:
        # Master row exists but has no wFirma mapping yet — do not assert
        # packing-master authority because the proforma post-step needs
        # a real wFirma contractor_id. Fall through to other resolvers.
        return None

    master_name = (cm_row["bill_to_name"] or "").strip()

    # 3. Build the advisory note for name mismatch. The advisory is
    #    informational (operator-facing); it never converts to a blocker.
    proforma_norm = _normalize_name(client_name)
    master_norm   = _normalize_name(master_name)
    parsed_norm   = _normalize_name(row["parsed_name"])

    advisory = ""
    if proforma_norm and master_norm and proforma_norm != master_norm:
        # Proforma free-text differs from master record. NIP +
        # contractor_id are the authority; this is display-only drift.
        advisory = (
            f"Proforma client name {client_name!r} differs from Customer "
            f"Master {master_name!r} (wFirma contractor {wfirma_contractor_id}, "
            f"NIP {cm_row['nip']!r}). Resolved via packing-upload selection — "
            f"VAT/contractor_id outrank display name."
        )
    elif proforma_norm and parsed_norm and proforma_norm != parsed_norm:
        # Proforma matches master but differs from what the invoice parser
        # extracted. Minor drift — note for transparency.
        advisory = (
            f"Proforma client name {client_name!r} differs from invoice-"
            f"parsed name {row['parsed_name']!r}; Customer Master selection "
            f"({master_name!r}, contractor {wfirma_contractor_id}) is authoritative."
        )

    return {
        "wfirma_customer_id":     wfirma_contractor_id,
        "resolved_master_name":   master_name,
        "customer_master_id":     int(cm_row["id"]),
        "parsed_packing_name":    (row["parsed_name"] or "").strip(),
        "parsed_packing_nip":     (row["parsed_tax_id"] or "").strip(),
        "parsed_packing_country": (row["parsed_country"] or "").strip(),
        "matched_master_id":      matched_master_id,
        "match_strategy":         "packing_master",
        "advisory":               advisory,
    }


def derive_customer_authority_for_draft(
    *,
    batch_id: Optional[str],
    client_name: Optional[str],
    documents_db_path: Path,
    customer_master_db_path: Path,
) -> Optional[Dict[str, Any]]:
    """Resolve a proforma draft via its originating sales-packing-list
    document's upload-time client selection. Per-DOCUMENT authority —
    the correct granularity for multi-client shipments.

    Authority chain walked here:

        proforma_draft (batch_id + client_name)
            ↓ join by (batch_id, client_name, document_type='sales_packing_list')
        sales_documents.document_id
            ↓ join
        shipment_documents.client_contractor_id  ← operator's upload-time pick
            ↓ join
        customer_master.bill_to_contractor_id
            ↓
        wFirma contractor + master record

    Why this exists alongside ``derive_customer_resolution_via_packing``:
    the older per-batch helper (PR #296+#297) reads
    ``packing_contractor_resolution`` which has UNIQUE(batch_id, role) →
    exactly ONE client per batch. For multi-client shipments (5 distinct
    proforma drafts on one batch) that helper returns the SAME contractor
    for every draft → wrong-routes 4 of 5 invoices. The per-document path
    here uses the operator's individual selection per sales packing list,
    which is the correct granularity.

    Returns same shape as ``derive_customer_resolution_via_packing``
    (with match_strategy='per_document_upload') so callers can use them
    interchangeably. Returns ``None`` when:
      * batch_id or client_name empty
      * DB files missing
      * no sales_packing_list document for this (batch_id, client_name)
      * the document has no client_contractor_id (operator skipped pick)
      * customer_master has no matching row (data gap — caller falls
        through to name-based resolver, which will likely produce a
        meaningful blocker for the operator)
    """
    if not (batch_id or "").strip() or not (client_name or "").strip():
        return None
    docs_path = Path(documents_db_path)
    cm_path   = Path(customer_master_db_path)
    if not docs_path.is_file() or not cm_path.is_file():
        return None

    # 1. Find the per-client sales_packing_list document.
    #    sales_documents stores client_name verbatim from the upload
    #    intake; the join is by (batch_id, client_name) string equality.
    with sqlite3.connect(str(docs_path)) as conn:
        conn.row_factory = sqlite3.Row
        sd_row = conn.execute(
            "SELECT id, document_id, client_name FROM sales_documents "
            "WHERE batch_id = ? AND client_name = ? "
            "AND document_type = 'sales_packing_list' "
            "LIMIT 1",
            (batch_id.strip(), client_name.strip()),
        ).fetchone()
        if sd_row is None or not sd_row["document_id"]:
            return None
        sales_document_uuid = sd_row["id"]
        shipment_doc_id     = sd_row["document_id"]

        # 2. Read client_contractor_id from the shipment_documents row.
        ship_row = conn.execute(
            "SELECT client_contractor_id, file_name "
            "FROM shipment_documents WHERE id = ?",
            (shipment_doc_id,),
        ).fetchone()
        if ship_row is None:
            return None
        client_contractor_id = (ship_row["client_contractor_id"] or "").strip()
        if not client_contractor_id:
            return None
        source_file_name = ship_row["file_name"] or ""

    # 3. Look up customer_master by bill_to_contractor_id.
    with sqlite3.connect(str(cm_path)) as conn:
        conn.row_factory = sqlite3.Row
        cm_row = conn.execute(
            "SELECT id, bill_to_contractor_id, bill_to_name, country, nip "
            "FROM customer_master WHERE bill_to_contractor_id = ?",
            (client_contractor_id,),
        ).fetchone()
    if cm_row is None:
        # The operator picked a wFirma contractor that has no
        # customer_master mirror. We do NOT assert authority because
        # downstream proforma needs the master record's NIP / country
        # for posting. Caller falls through to name resolver, which
        # will likely produce a meaningful blocker.
        return None

    master_name = (cm_row["bill_to_name"] or "").strip()

    # 4. Build the result. The advisory note when proforma name differs
    #    from the master record uses the same wording as the per-batch
    #    helper so the frontend renders both uniformly.
    proforma_norm = _normalize_name(client_name)
    master_norm   = _normalize_name(master_name)

    advisory = ""
    if proforma_norm and master_norm and proforma_norm != master_norm:
        advisory = (
            f"Proforma client name {client_name!r} differs from Customer "
            f"Master {master_name!r} (wFirma contractor {client_contractor_id}, "
            f"NIP {cm_row['nip']!r}). Resolved via per-document upload "
            f"selection on {source_file_name!r} — VAT/contractor_id "
            f"outrank display name."
        )

    return {
        "wfirma_customer_id":     client_contractor_id,
        "resolved_master_name":   master_name,
        "customer_master_id":     int(cm_row["id"]),
        "parsed_packing_name":    (sd_row["client_name"] or "").strip(),
        "parsed_packing_nip":     "",  # sales_documents doesn't carry NIP
        "parsed_packing_country": (cm_row["country"] or "").strip(),
        "matched_master_id":      client_contractor_id,
        "match_strategy":         "per_document_upload",
        "advisory":               advisory,
        "source_document_id":     shipment_doc_id,
        "source_file_name":       source_file_name,
    }


__all__ = [
    "derive_customer_resolution_via_packing",
    "derive_customer_authority_for_draft",
]
