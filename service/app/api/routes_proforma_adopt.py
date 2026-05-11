"""
routes_proforma_adopt.py — Adoption and enrichment of already-issued wFirma proformas.

POST /api/v1/proforma/adopt-issued/{batch_id}   — Phase 1: insert adopted rows
POST /api/v1/proforma/enrich-fullnumber/{batch_id} — Phase 2: backfill fullnumber from wFirma

Phase 1: Reads audit.proforma_issued[] and inserts rows into proforma_drafts so the
app can track existing wFirma proformas that were created outside the draft
lifecycle (e.g. via a different client or session).

Phase 2: For rows where wfirma_proforma_fullnumber is blank, fetches the canonical
proforma number from wFirma API (read-only GET invoices/get/{id}) and writes it back.
Requires WFIRMA_ACCESS_KEY, WFIRMA_SECRET_KEY, WFIRMA_APP_KEY, WFIRMA_COMPANY_ID.

Idempotency
-----------
  (batch_id, wfirma_proforma_id) already present  → skipped, not an error.
  (batch_id, client_name) present with a DIFFERENT wfirma_proforma_id → 409.
  All other entries → inserted.

Atomicity
---------
  Conflict detection runs before any INSERT. If any conflict is found the
  endpoint returns 409 and writes nothing.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from xml.etree import ElementTree as ET

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..core.config import settings
from ..core.logging import get_logger
from ..core.security import require_api_key
from ..services import wfirma_client as _wfirma

log = get_logger(__name__)
router = APIRouter(prefix="/api/v1/proforma", tags=["proforma"])
_auth = Depends(require_api_key)


# ── Request body ──────────────────────────────────────────────────────────────

class AdoptRequest(BaseModel):
    confirmed: bool = False
    operator:  str  = ""
    dry_run:   bool = False


# ── Helpers ───────────────────────────────────────────────────────────────────

def _audit_path(batch_id: str) -> Path:
    return settings.storage_root / "outputs" / batch_id / "audit.json"


def _proforma_db() -> Path:
    return settings.storage_root / "proforma_links.db"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_audit(batch_id: str) -> Dict[str, Any]:
    p = _audit_path(batch_id)
    if not p.exists():
        raise HTTPException(status_code=404,
                            detail=f"audit.json not found for {batch_id!r}.")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500,
                            detail=f"audit.json parse error: {exc}") from exc


def _timeline_posted_at(timeline: List[Dict], proforma_id: str) -> Optional[str]:
    """Return the ts of the proforma_issued timeline event for this proforma_id."""
    for ev in timeline:
        if ev.get("event") == "proforma_issued":
            d = ev.get("detail") or {}
            if str(d.get("wfirma_proforma_id", "")) == proforma_id:
                return ev.get("ts")
    return None


def _timeline_posted_by(timeline: List[Dict], proforma_id: str) -> str:
    for ev in timeline:
        if ev.get("event") == "proforma_issued":
            d = ev.get("detail") or {}
            if str(d.get("wfirma_proforma_id", "")) == proforma_id:
                return (d.get("operator") or ev.get("actor") or "").strip()
    return ""


# ── Adoption endpoint ─────────────────────────────────────────────────────────

@router.post("/adopt-issued/{batch_id}", dependencies=[_auth])
def adopt_issued_proformas(batch_id: str, body: AdoptRequest) -> JSONResponse:
    """
    Phase 1 adoption: read audit.proforma_issued[] and insert rows into
    proforma_drafts. No wFirma API calls. No invoice conversion.

    Returns a preview when dry_run=true (nothing written).
    confirmed=true is required; returns 400 otherwise.
    Conflicts (same batch+client, different wfirma_proforma_id) return 409
    and write nothing.
    """
    if "/" in batch_id or ".." in batch_id:
        raise HTTPException(status_code=400, detail="Invalid batch_id.")

    if not body.confirmed:
        raise HTTPException(
            status_code=400,
            detail=(
                "confirmed must be true. Run with dry_run=true first to review "
                "what would be adopted, then re-submit with confirmed=true."
            ),
        )

    audit    = _load_audit(batch_id)
    issued   = audit.get("proforma_issued") or []
    timeline = audit.get("timeline") or []

    if not issued:
        raise HTTPException(
            status_code=422,
            detail=f"audit.proforma_issued is empty for {batch_id!r}. Nothing to adopt.",
        )

    db_path = _proforma_db()
    if not db_path.exists():
        raise HTTPException(status_code=503, detail="proforma_links.db not found.")

    operator = (body.operator or "").strip()
    now      = _now_iso()

    # ── Pass 1: classify every entry before touching the DB ──────────────────
    to_adopt:  List[Dict[str, Any]] = []   # will be inserted
    to_skip:   List[Dict[str, Any]] = []   # already present, same ID
    conflicts: List[Dict[str, Any]] = []   # same client, different ID

    with sqlite3.connect(str(db_path), check_same_thread=False) as con:
        con.row_factory = sqlite3.Row

        for entry in issued:
            client_name       = (entry.get("client_name") or "").strip()
            wfirma_proforma_id = str(entry.get("wfirma_proforma_id") or "").strip()
            currency           = (entry.get("currency") or "").strip()
            line_count         = int(entry.get("line_count") or 0)

            if not client_name or not wfirma_proforma_id:
                log.warning("adopt-issued %s: skipping entry with missing fields: %s",
                            batch_id, entry)
                continue

            existing = con.execute(
                "SELECT id, wfirma_proforma_id, draft_state FROM proforma_drafts "
                "WHERE batch_id=? AND client_name=?",
                (batch_id, client_name),
            ).fetchone()

            if existing:
                existing_pid = (existing["wfirma_proforma_id"] or "").strip()
                if existing_pid == wfirma_proforma_id:
                    to_skip.append({
                        "client_name":        client_name,
                        "wfirma_proforma_id": wfirma_proforma_id,
                        "reason":             "already_adopted",
                        "draft_id":           existing["id"],
                        "draft_state":        existing["draft_state"],
                    })
                else:
                    conflicts.append({
                        "client_name":                    client_name,
                        "requested_wfirma_proforma_id":   wfirma_proforma_id,
                        "existing_wfirma_proforma_id":    existing_pid,
                        "existing_draft_id":              existing["id"],
                    })
            else:
                posted_at = _timeline_posted_at(timeline, wfirma_proforma_id)
                posted_by = _timeline_posted_by(timeline, wfirma_proforma_id)
                to_adopt.append({
                    "client_name":        client_name,
                    "wfirma_proforma_id": wfirma_proforma_id,
                    "currency":           currency,
                    "line_count":         line_count,
                    "posted_at":          posted_at,
                    "posted_by":          posted_by,
                })

        # Return 409 before any write if conflicts found.
        if conflicts:
            raise HTTPException(
                status_code=409,
                detail={
                    "error":     "proforma_conflict",
                    "message": (
                        "One or more clients already have a draft with a different "
                        "wfirma_proforma_id. Resolve manually before adopting."
                    ),
                    "conflicts": conflicts,
                },
            )

        # Dry-run: nothing written.
        if body.dry_run:
            return JSONResponse({
                "batch_id": batch_id,
                "dry_run":  True,
                "adopted":  [
                    {**e, "action": "would_insert"} for e in to_adopt
                ],
                "skipped":  to_skip,
            })

        # ── Pass 2: insert ────────────────────────────────────────────────────
        inserted: List[Dict[str, Any]] = []

        for e in to_adopt:
            notes = (
                f"Adopted from audit.proforma_issued — originally issued "
                f"outside app draft lifecycle on "
                f"{(e['posted_at'] or 'unknown date')[:10]}. "
                f"Line count at issuance: {e['line_count']}."
            )
            source_lines = json.dumps(
                [{"line_count": e["line_count"], "currency": e["currency"]}]
            )
            try:
                con.execute(
                    """
                    INSERT INTO proforma_drafts (
                        batch_id, client_name,
                        status, currency,
                        source_lines_json, wfirma_proforma_id,
                        notes, created_at, updated_at,
                        draft_state, draft_version,
                        wfirma_proforma_fullnumber,
                        buyer_override_json, ship_to_override_json,
                        payment_terms_json, remarks,
                        editable_lines_json, service_charges_json,
                        posted_at, posted_by
                    ) VALUES (
                        ?, ?,
                        'created', ?,
                        ?, ?,
                        ?, ?, ?,
                        'adopted_from_audit', 1,
                        '',
                        '{}', '{}',
                        '{}', '',
                        '[]', '[]',
                        ?, ?
                    )
                    """,
                    (
                        batch_id, e["client_name"],
                        e["currency"],
                        source_lines, e["wfirma_proforma_id"],
                        notes, now, now,
                        e["posted_at"], e["posted_by"],
                    ),
                )
            except sqlite3.IntegrityError as exc:
                # TOCTOU: another request inserted between pass 1 and pass 2.
                log.warning(
                    "adopt-issued %s/%s: IntegrityError on insert (race): %s",
                    batch_id, e["client_name"], exc,
                )
                to_skip.append({
                    "client_name":        e["client_name"],
                    "wfirma_proforma_id": e["wfirma_proforma_id"],
                    "reason":             "race_condition_skipped",
                })
                continue

            draft_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]

            con.execute(
                """
                INSERT INTO proforma_draft_events
                    (draft_id, event, detail_json, operator, occurred_at)
                VALUES (?, 'adopted_from_audit', ?, ?, ?)
                """,
                (
                    draft_id,
                    json.dumps({
                        "wfirma_proforma_id": e["wfirma_proforma_id"],
                        "source":             "audit.proforma_issued",
                        "line_count":         e["line_count"],
                        "currency":           e["currency"],
                    }),
                    operator,
                    now,
                ),
            )
            inserted.append({
                "client_name":        e["client_name"],
                "wfirma_proforma_id": e["wfirma_proforma_id"],
                "currency":           e["currency"],
                "line_count":         e["line_count"],
                "posted_at":          e["posted_at"],
                "action":             "inserted",
                "draft_id":           draft_id,
            })

    log.info(
        "adopt-issued %s: inserted=%d skipped=%d operator=%r dry_run=%s",
        batch_id, len(inserted), len(to_skip), operator, body.dry_run,
    )

    return JSONResponse({
        "batch_id": batch_id,
        "dry_run":  False,
        "adopted":  inserted,
        "skipped":  to_skip,
    })


# ── Phase 2: fullnumber enrichment ────────────────────────────────────────────

class EnrichRequest(BaseModel):
    confirmed: bool = False
    operator:  str  = ""
    dry_run:   bool = False


@router.post("/enrich-fullnumber/{batch_id}", dependencies=[_auth])
def enrich_proforma_fullnumbers(batch_id: str, body: EnrichRequest) -> JSONResponse:
    """
    Phase 2 enrichment: for each proforma_draft row in this batch where
    wfirma_proforma_fullnumber is blank, fetch the canonical proforma number
    from wFirma API (read-only GET invoices/get/{id}) and write it back.

    Requires WFIRMA_ACCESS_KEY, WFIRMA_SECRET_KEY, WFIRMA_APP_KEY,
    WFIRMA_COMPANY_ID to be set in .env — returns 503 if not configured.

    confirmed=true required; returns 400 otherwise.
    dry_run=true previews without writing.

    Idempotent: rows that already have a fullnumber are skipped.
    Per-row fetch errors are reported in 'failed' list; other rows still proceed.
    """
    if "/" in batch_id or ".." in batch_id:
        raise HTTPException(status_code=400, detail="Invalid batch_id.")

    if not body.confirmed:
        raise HTTPException(
            status_code=400,
            detail=(
                "confirmed must be true. Run with dry_run=true first to preview "
                "which fullnumbers would be fetched, then re-submit with confirmed=true."
            ),
        )

    # Guard: wFirma must be configured
    if not (settings.wfirma_access_key and settings.wfirma_secret_key
            and settings.wfirma_app_key):
        raise HTTPException(
            status_code=503,
            detail={
                "error":   "wfirma_not_configured",
                "message": (
                    "Set WFIRMA_ACCESS_KEY, WFIRMA_SECRET_KEY, WFIRMA_APP_KEY, "
                    "WFIRMA_COMPANY_ID in .env and restart the service."
                ),
            },
        )

    db_path = _proforma_db()
    if not db_path.exists():
        raise HTTPException(status_code=503, detail="proforma_links.db not found.")

    operator = (body.operator or "").strip()
    now      = _now_iso()

    # Load all rows for this batch that still have a blank fullnumber.
    with sqlite3.connect(str(db_path), check_same_thread=False) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            """
            SELECT id, client_name, wfirma_proforma_id
            FROM proforma_drafts
            WHERE batch_id = ?
              AND (wfirma_proforma_fullnumber IS NULL
                   OR wfirma_proforma_fullnumber = '')
            """,
            (batch_id,),
        ).fetchall()

    if not rows:
        return JSONResponse({
            "batch_id":  batch_id,
            "dry_run":   body.dry_run,
            "message":   "No rows with blank wfirma_proforma_fullnumber found. Nothing to enrich.",
            "enriched":  [],
            "skipped":   [],
            "failed":    [],
        })

    # Fetch fullnumber from wFirma for each row (read-only).
    preview:  List[Dict[str, Any]] = []
    to_write: List[Dict[str, Any]] = []
    failed:   List[Dict[str, Any]] = []

    for row in rows:
        draft_id         = row["id"]
        client_name      = row["client_name"]
        wfirma_proforma_id = row["wfirma_proforma_id"]

        if not wfirma_proforma_id:
            failed.append({
                "draft_id":           draft_id,
                "client_name":        client_name,
                "wfirma_proforma_id": wfirma_proforma_id,
                "error":              "blank wfirma_proforma_id — cannot fetch",
            })
            continue

        try:
            xml_text = _wfirma.fetch_invoice_xml(wfirma_proforma_id)
            root     = ET.fromstring(xml_text)
            node     = root.find(".//invoice")
            fullnumber = _wfirma._extract_fullnumber(node)
        except Exception as exc:
            log.warning(
                "enrich-fullnumber %s/%s: fetch failed: %s",
                batch_id, client_name, exc,
            )
            failed.append({
                "draft_id":           draft_id,
                "client_name":        client_name,
                "wfirma_proforma_id": wfirma_proforma_id,
                "error":              str(exc),
            })
            continue

        if not fullnumber:
            failed.append({
                "draft_id":           draft_id,
                "client_name":        client_name,
                "wfirma_proforma_id": wfirma_proforma_id,
                "error":              "wFirma returned no fullnumber field",
            })
            continue

        entry = {
            "draft_id":                 draft_id,
            "client_name":              client_name,
            "wfirma_proforma_id":       wfirma_proforma_id,
            "wfirma_proforma_fullnumber": fullnumber,
        }
        preview.append({**entry, "action": "would_update"})
        to_write.append(entry)

    if body.dry_run:
        return JSONResponse({
            "batch_id": batch_id,
            "dry_run":  True,
            "enriched": preview,
            "skipped":  [],
            "failed":   failed,
        })

    # Write — only update rows that are still blank (idempotent guard).
    written: List[Dict[str, Any]] = []

    with sqlite3.connect(str(db_path), check_same_thread=False) as con:
        con.row_factory = sqlite3.Row
        for e in to_write:
            rowcount = con.execute(
                """
                UPDATE proforma_drafts
                SET wfirma_proforma_fullnumber = ?,
                    updated_at                = ?
                WHERE id = ?
                  AND (wfirma_proforma_fullnumber IS NULL
                       OR wfirma_proforma_fullnumber = '')
                """,
                (e["wfirma_proforma_fullnumber"], now, e["draft_id"]),
            ).rowcount

            if rowcount == 0:
                # Already enriched by a concurrent request — treat as success.
                log.info(
                    "enrich-fullnumber %s/%s: row already enriched (concurrent write), skipping event.",
                    batch_id, e["client_name"],
                )
                written.append({**e, "action": "already_set"})
                continue

            con.execute(
                """
                INSERT INTO proforma_draft_events
                    (draft_id, event, detail_json, operator, occurred_at)
                VALUES (?, 'fullnumber_enriched', ?, ?, ?)
                """,
                (
                    e["draft_id"],
                    json.dumps({
                        "wfirma_proforma_fullnumber": e["wfirma_proforma_fullnumber"],
                        "wfirma_proforma_id":         e["wfirma_proforma_id"],
                        "source": "wfirma_api_fetch",
                    }),
                    operator,
                    now,
                ),
            )
            written.append({**e, "action": "updated"})

    log.info(
        "enrich-fullnumber %s: written=%d failed=%d operator=%r",
        batch_id, len(written), len(failed), operator,
    )

    return JSONResponse({
        "batch_id": batch_id,
        "dry_run":  False,
        "enriched": written,
        "skipped":  [],
        "failed":   failed,
    })
