"""
proforma_invoice_link_db.py — local link table between an approved proforma
and the final wFirma invoice we issue from it.

wFirma exposes NO native conversion endpoint and stores no parent/child
relationship between a proforma and its final invoice (probe results dated
2026-05-03 — see app/tools/probe_proforma_to_invoice_api.py). This table
is the only audit trace that connects them.

Pure CRUD. Pure SQLite. No wFirma I/O lives here.

Schema (locked):
    proforma_invoice_links
        id                 INTEGER PRIMARY KEY AUTOINCREMENT
        proforma_id        TEXT    NOT NULL  UNIQUE   wFirma id
        proforma_number    TEXT    NOT NULL           e.g. "PROF 90/2026"
        invoice_id         TEXT                       wFirma id of final invoice
        invoice_number     TEXT                       e.g. "FV 12/2026"
        converted_at       TEXT    NOT NULL           UTC ISO timestamp
        operator           TEXT    NOT NULL           who confirmed the live write
        source_total       TEXT    NOT NULL           proforma total at conversion
        invoice_total      TEXT                       final invoice total (set on success)
        currency           TEXT    NOT NULL
        status             TEXT    NOT NULL           pending | issued | failed | rolled_back
        notes              TEXT

The UNIQUE on proforma_id is the duplicate-conversion guard. Trying to
re-convert the same proforma will raise sqlite3.IntegrityError, which the
caller turns into a ProformaAlreadyConverted exception.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# Module logger. Several defensive ``except`` branches (draft-birth block
# lifecycle, canonical-name migration) call ``log.warning`` — without this
# binding those branches would raise NameError instead of logging.
log = logging.getLogger(__name__)


# ── Public types ──────────────────────────────────────────────────────────────

VALID_STATUSES = ("pending", "issued", "failed", "rolled_back")


@dataclass(frozen=True)
class ProformaInvoiceLink:
    """One row in proforma_invoice_links."""
    proforma_id:      str
    proforma_number:  str
    converted_at:     str               # ISO 8601 UTC
    operator:         str
    source_total:     Decimal
    currency:         str
    status:           str               # one of VALID_STATUSES
    invoice_id:       Optional[str]     = None
    invoice_number:   Optional[str]     = None
    invoice_total:    Optional[Decimal] = None
    notes:            Optional[str]     = None
    wfirma_pz_doc_id: Optional[str]     = None
    id:               Optional[int]     = None


class ProformaAlreadyConverted(Exception):
    """Raised when a caller tries to insert a second link for the same
    proforma_id. Carries the existing row for the operator to inspect."""

    def __init__(self, message: str, existing: ProformaInvoiceLink) -> None:
        super().__init__(message)
        self.existing = existing


# ── Validation ────────────────────────────────────────────────────────────────

def validate(link: ProformaInvoiceLink) -> List[str]:
    """Return a list of human-readable blockers; empty if OK."""
    blockers: List[str] = []
    if not (link.proforma_id or "").strip():
        blockers.append("proforma_id is required")
    if not (link.proforma_number or "").strip():
        blockers.append("proforma_number is required")
    if not (link.operator or "").strip():
        blockers.append("operator is required")
    if not (link.currency or "").strip():
        blockers.append("currency is required")
    if link.currency and link.currency not in ("PLN", "USD", "EUR"):
        blockers.append(f"currency must be PLN/USD/EUR, got {link.currency!r}")
    if link.status not in VALID_STATUSES:
        blockers.append(f"status must be one of {VALID_STATUSES}, got {link.status!r}")
    try:
        if Decimal(link.source_total) <= 0:
            blockers.append(f"source_total must be > 0, got {link.source_total}")
    except Exception:  # noqa: BLE001
        blockers.append(f"source_total is not a valid decimal: {link.source_total!r}")
    if link.invoice_total is not None:
        try:
            if Decimal(link.invoice_total) <= 0:
                blockers.append(f"invoice_total must be > 0 when set, got {link.invoice_total}")
        except Exception:  # noqa: BLE001
            blockers.append(f"invoice_total is not a valid decimal: {link.invoice_total!r}")
    # status=issued requires invoice_id + invoice_number + invoice_total
    if link.status == "issued":
        if not (link.invoice_id or "").strip():
            blockers.append("status=issued requires invoice_id")
        if not (link.invoice_number or "").strip():
            blockers.append("status=issued requires invoice_number")
        if link.invoice_total is None:
            blockers.append("status=issued requires invoice_total")
    return blockers


# ── DB lifecycle ─────────────────────────────────────────────────────────────

def _connect(db_path: Path, isolation_level: str = "") -> sqlite3.Connection:
    """Tuned connection — WAL + busy_timeout per the dhl_thread_lock idiom
    (dhl_thread_lock.py:126-129; infra health pass d67d3722 finding #2):
    this DB has FastAPI-handler AND APScheduler (enrichment) writers, so
    every connection must wait out a competing writer (busy_timeout FIRST,
    so the WAL flip itself waits) instead of failing 'database is locked'
    immediately. isolation_level default matches sqlite3.connect's own."""
    conn = sqlite3.connect(str(db_path), timeout=30.0,
                           isolation_level=isolation_level)
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(db_path: Path) -> None:
    """Create the table if missing. Idempotent. Runs additive migrations."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS proforma_invoice_links (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                proforma_id     TEXT NOT NULL UNIQUE,
                proforma_number TEXT NOT NULL,
                invoice_id      TEXT,
                invoice_number  TEXT,
                converted_at    TEXT NOT NULL,
                operator        TEXT NOT NULL,
                source_total    TEXT NOT NULL,
                invoice_total   TEXT,
                currency        TEXT NOT NULL,
                status          TEXT NOT NULL,
                notes           TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pil_status ON proforma_invoice_links(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pil_invoice_id ON proforma_invoice_links(invoice_id)")
        # Additive migration: wfirma_pz_doc_id column (added 2026-05)
        try:
            conn.execute("ALTER TABLE proforma_invoice_links ADD COLUMN wfirma_pz_doc_id TEXT")
        except sqlite3.OperationalError as exc:
            if "duplicate column" not in str(exc).lower():
                raise
        # Phase 1: also ensure the drafts table + events table exist.
        _ensure_drafts_table(conn)
        # C-3g: service-charge product metadata registry (PROFORMA authority).
        # Holds ONLY display/config metadata for service-charge line emission
        # (freight/insurance). The wFirma identity (wfirma_product_id) is NOT
        # stored here — wfirma_product_mirror is the sole identity authority.
        # Replaces the retired wfirma_products cache dependency for service
        # charges (Phase-C C-3g; C-1d declared residuals 1+2).
        conn.execute("""
            CREATE TABLE IF NOT EXISTS service_product_registry (
                charge_type  TEXT PRIMARY KEY,
                product_name TEXT NOT NULL DEFAULT '',
                vat_rate     TEXT NOT NULL DEFAULT '23',
                unit         TEXT NOT NULL DEFAULT 'szt.',
                updated_at   TEXT NOT NULL
            )
        """)
        conn.commit()


# ── Helpers ──────────────────────────────────────────────────────────────────

def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row_to_link(row: sqlite3.Row) -> ProformaInvoiceLink:
    keys = row.keys()
    return ProformaInvoiceLink(
        id               = row["id"],
        proforma_id      = row["proforma_id"],
        proforma_number  = row["proforma_number"],
        invoice_id       = row["invoice_id"],
        invoice_number   = row["invoice_number"],
        converted_at     = row["converted_at"],
        operator         = row["operator"],
        source_total     = Decimal(row["source_total"]),
        invoice_total    = Decimal(row["invoice_total"]) if row["invoice_total"] else None,
        currency         = row["currency"],
        status           = row["status"],
        notes            = row["notes"],
        wfirma_pz_doc_id = row["wfirma_pz_doc_id"] if "wfirma_pz_doc_id" in keys else None,
    )


# ── CRUD ──────────────────────────────────────────────────────────────────────

def create_pending_link(db_path: Path, link: ProformaInvoiceLink) -> int:
    """Insert a NEW link in 'pending' state. Raises ProformaAlreadyConverted
    if a row already exists for this proforma_id.

    Returns the new row id.
    """
    init_db(db_path)
    blockers = validate(link)
    if blockers:
        raise ValueError(f"link validation failed: {'; '.join(blockers)}")

    if not link.converted_at:
        link = replace(link, converted_at=_now_utc_iso())

    with _connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.execute(
                """
                INSERT INTO proforma_invoice_links
                    (proforma_id, proforma_number, invoice_id, invoice_number,
                     converted_at, operator, source_total, invoice_total,
                     currency, status, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    link.proforma_id,
                    link.proforma_number,
                    link.invoice_id,
                    link.invoice_number,
                    link.converted_at,
                    link.operator,
                    str(link.source_total),
                    str(link.invoice_total) if link.invoice_total is not None else None,
                    link.currency,
                    link.status,
                    link.notes,
                ),
            )
            conn.commit()
            return int(cur.lastrowid)
        except sqlite3.IntegrityError as exc:
            existing = get_link_by_proforma(db_path, link.proforma_id)
            raise ProformaAlreadyConverted(
                f"proforma_id={link.proforma_id} already has a link "
                f"(status={existing.status if existing else 'unknown'})",
                existing=existing,
            ) from exc


def mark_issued(db_path: Path,
                proforma_id: str,
                *,
                invoice_id: str,
                invoice_number: str,
                invoice_total: Decimal,
                notes: Optional[str] = None) -> None:
    """Promote a pending link to issued, recording the wFirma final invoice id."""
    if not invoice_id or not invoice_number:
        raise ValueError("invoice_id and invoice_number are required to mark issued")
    if Decimal(invoice_total) <= 0:
        raise ValueError(f"invoice_total must be > 0, got {invoice_total}")
    with _connect(db_path) as conn:
        cur = conn.execute(
            """
            UPDATE proforma_invoice_links
               SET invoice_id    = ?,
                   invoice_number= ?,
                   invoice_total = ?,
                   status        = 'issued',
                   notes         = COALESCE(?, notes)
             WHERE proforma_id   = ?
            """,
            (str(invoice_id), str(invoice_number), str(invoice_total),
             notes, str(proforma_id)),
        )
        conn.commit()
        if cur.rowcount == 0:
            raise KeyError(f"no link row for proforma_id={proforma_id!r}")


def mark_failed(db_path: Path, proforma_id: str, *, notes: str) -> None:
    """Promote a pending link to failed (e.g. wFirma rejected the add)."""
    if not (notes or "").strip():
        raise ValueError("notes is required when marking failed")
    with _connect(db_path) as conn:
        cur = conn.execute(
            """
            UPDATE proforma_invoice_links
               SET status = 'failed',
                   notes  = ?
             WHERE proforma_id = ?
            """,
            (notes, str(proforma_id)),
        )
        conn.commit()
        if cur.rowcount == 0:
            raise KeyError(f"no link row for proforma_id={proforma_id!r}")


def record_invoice_identity(db_path: Path,
                            proforma_id: str,
                            *,
                            invoice_id: str,
                            invoice_number: str = "") -> None:
    """Capture the wFirma invoice identity on the link row WITHOUT changing
    its status.

    R-2 split-brain repair support: called immediately after invoices/add
    returns an id, BEFORE verify-after-create and mark_issued run. If a
    later local step fails (verify mismatch, mark_issued crash), the row
    stays 'pending'/'failed' but now durably carries the id of the REAL
    remote invoice, so the reconcile workflow can re-fetch and repair it.

    Idempotent for the same invoice_id. Refuses to overwrite a DIFFERENT
    already-captured invoice_id (identity conflict — operator must inspect).
    Raises KeyError if no link row exists for this proforma_id.
    """
    iid = (invoice_id or "").strip()
    if not iid:
        raise ValueError("invoice_id is required to record invoice identity")
    existing = get_link_by_proforma(db_path, proforma_id)
    if existing is None:
        raise KeyError(f"no link row for proforma_id={proforma_id!r}")
    if (existing.invoice_id or "").strip() and existing.invoice_id != iid:
        raise ValueError(
            f"proforma_id={proforma_id!r} already carries "
            f"invoice_id={existing.invoice_id!r}; refusing to overwrite "
            f"with {iid!r}"
        )
    with _connect(db_path) as conn:
        conn.execute(
            """
            UPDATE proforma_invoice_links
               SET invoice_id     = ?,
                   invoice_number = COALESCE(NULLIF(?, ''), invoice_number)
             WHERE proforma_id    = ?
            """,
            (iid, (invoice_number or "").strip(), str(proforma_id)),
        )
        conn.commit()


def get_link_by_proforma(db_path: Path, proforma_id: str) -> Optional[ProformaInvoiceLink]:
    if not Path(db_path).exists():
        return None
    with _connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT * FROM proforma_invoice_links WHERE proforma_id = ? LIMIT 1",
            (str(proforma_id),),
        )
        row = cur.fetchone()
        return _row_to_link(row) if row else None


def get_link_by_invoice(db_path: Path, invoice_id: str) -> Optional[ProformaInvoiceLink]:
    if not Path(db_path).exists():
        return None
    with _connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT * FROM proforma_invoice_links WHERE invoice_id = ? LIMIT 1",
            (str(invoice_id),),
        )
        row = cur.fetchone()
        return _row_to_link(row) if row else None


def get_pz_doc_id(db_path: Path, proforma_id: str) -> Optional[str]:
    """Return the stored wfirma_pz_doc_id for the given proforma_id, or None."""
    link = get_link_by_proforma(db_path, proforma_id)
    return link.wfirma_pz_doc_id if link else None


def set_pz_doc_id(db_path: Path, proforma_id: str, pz_doc_id: str) -> None:
    """
    Store the wFirma PZ document id for a proforma.

    Raises ValueError if a different pz_doc_id is already set (duplicate guard).
    Raises KeyError if no link row exists for this proforma_id.
    """
    existing = get_pz_doc_id(db_path, proforma_id)
    if existing is not None:
        if existing == pz_doc_id:
            return  # idempotent
        raise ValueError(
            f"proforma_id={proforma_id!r} already has pz_doc_id={existing!r}; "
            f"refusing to overwrite with {pz_doc_id!r}"
        )
    with _connect(db_path) as conn:
        cur = conn.execute(
            "UPDATE proforma_invoice_links SET wfirma_pz_doc_id = ? WHERE proforma_id = ?",
            (str(pz_doc_id), str(proforma_id)),
        )
        conn.commit()
        if cur.rowcount == 0:
            raise KeyError(f"no link row for proforma_id={proforma_id!r}")


def list_links(db_path: Path,
               *,
               status: Optional[str] = None,
               limit:  int = 100) -> List[ProformaInvoiceLink]:
    if not Path(db_path).exists():
        return []
    where = ""
    args: List = []
    if status:
        if status not in VALID_STATUSES:
            raise ValueError(f"status must be one of {VALID_STATUSES}, got {status!r}")
        where = "WHERE status = ?"
        args.append(status)
    args.append(int(limit))
    with _connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            f"SELECT * FROM proforma_invoice_links {where} ORDER BY id DESC LIMIT ?",
            tuple(args),
        )
        return [_row_to_link(r) for r in cur.fetchall()]


# ─────────────────────────────────────────────────────────────────────────────
# Proforma drafts — pre-create staging keyed by (batch_id, client_name)
# ─────────────────────────────────────────────────────────────────────────────
# `proforma_invoice_links` (above) is keyed by the WFIRMA proforma_id and is
# only useful AFTER a proforma exists in wFirma. The drafts table below
# captures the BEFORE state: a local idempotency record built from the
# read-only preview, before any live wFirma call. Once a live call succeeds
# (in a future task) the matching drafts row is promoted to status='issued'
# with `wfirma_proforma_id` populated, and a parallel `proforma_invoice_links`
# row is created for the eventual final-invoice conversion.

DRAFT_STATUSES = ("pending_local", "issued", "failed")

# Phase 2.5 — formal compatibility surface for the legacy ``status`` column.
#
# ``DRAFT_STATUSES`` (above) is the original Phase-1 set and is intentionally
# frozen. Phase 2 introduced one additional legacy value (``'draft'``) used
# by ``auto_create_draft_from_sales_packing`` so the schema-time backfill
# does not clobber explicitly-set ``draft_state`` rows on re-init. We expose
# both the frozen set AND the extended set so writers can validate inputs
# without breaking the Phase-1 contract test that pins ``DRAFT_STATUSES``.
KNOWN_LEGACY_STATUSES = DRAFT_STATUSES + ("draft",)

# Phase 1 of editable Proforma Draft lifecycle. The new state machine
# is read-only at this stage — Phase 2 wires writers. The legacy
# ``DRAFT_STATUSES`` set (above) is preserved unchanged for
# write-side compatibility; this set is the canonical surface for
# read-side validation in the new lifecycle.
DRAFT_LIFECYCLE_STATES = (
    "draft", "editing", "approved",
    "posting", "posted", "post_failed",
    "cancelled", "superseded",
    "converted",
)


@dataclass(frozen=True)
class ProformaDraft:
    """One row in proforma_drafts.

    Phase 1 extension: the dataclass surfaces both the legacy ``status``
    field (write-side compat for existing routes) AND the new
    ``draft_state`` field plus all editable-lifecycle metadata. New
    fields are optional with safe defaults so legacy callers that only
    pass ``batch_id``/``client_name``/``status`` still work.
    """
    batch_id:           str
    client_name:        str
    status:             str            # one of DRAFT_STATUSES (legacy)
    currency:           str            = ""
    exchange_rate:      Optional[float] = None
    source_lines_json:  str            = "[]"
    wfirma_proforma_id: Optional[str]  = None
    notes:              Optional[str]  = None
    created_at:         Optional[str]  = None
    updated_at:         Optional[str]  = None
    id:                 Optional[int]  = None
    # Phase 1 — editable lifecycle (read-only this phase; written
    # by phase-2+ helpers). Defaults match the schema migration so
    # constructing a ProformaDraft from legacy data is a no-op.
    draft_state:                str           = "posted"
    draft_version:              int           = 1
    supersedes_draft_id:        Optional[int] = None
    superseded_by_draft_id:     Optional[int] = None
    approved_at:                Optional[str] = None
    approved_by:                Optional[str] = None
    posted_at:                  Optional[str] = None
    locked_at:                  Optional[str] = None
    wfirma_proforma_fullnumber: str           = ""
    buyer_override_json:        str           = "{}"
    ship_to_override_json:      str           = "{}"
    payment_terms_json:         str           = "{}"
    remarks:                    str           = ""
    editable_lines_json:        str           = "[]"
    service_charges_json:       str           = "[]"
    # ── Phase 5 — posting lifecycle metadata ─────────────────────
    posting_started_at:         Optional[str] = None
    posting_started_by:         Optional[str] = None
    post_failed_at:             Optional[str] = None
    posted_by:                  Optional[str] = None
    # ── Phase 6 — packing-upload auto-sync metadata ───────────────
    last_packing_sync_at:       Optional[str] = None
    packing_sync_warning:       Optional[str] = None
    # ── Phase 7 — commercial document fields ─────────────────────────
    fx_rate_date:      Optional[str] = None   # returned NBP table effective date (YYYY-MM-DD)
    fx_rate_source:    str           = "NBP"  # rate source label: NBP | manual | identity
    # PR-4 NBP authority — the requested accounting date the fetch was keyed to
    # (the proforma issue date, or today when blank) and the NBP table number.
    # Kept distinct from fx_rate_date because the engine may return a prior
    # working-day table — the two dates are not always the same.
    fx_accounting_date: Optional[str] = None  # requested accounting date (YYYY-MM-DD)
    fx_table_number:    Optional[str] = None  # NBP Table A number, e.g. "A/089/2026"
    incoterm:        Optional[str]   = None   # per-shipment incoterm (DAP/FCA/…)
    insurance_eur:   Optional[float] = None   # declared shipment insurance EUR
    # ── PR-5 transport-document weight override ──────────────────────
    # Operator manual net/gross weight for the CMR / Packing List. The EXTRACTED
    # packing weight (packing_lines, grams) stays the historical authority; these
    # become the EFFECTIVE value only after an explicit save, and are stored in
    # KILOGRAMS (transport-document unit). weight_source_revision records the
    # extracted-source fingerprint at confirm time so a later re-import can flag
    # drift without silently overwriting the override.
    manual_net_weight:      Optional[float] = None   # kg
    manual_gross_weight:    Optional[float] = None   # kg
    weight_override_reason: Optional[str]   = None
    weight_confirmed_at:    Optional[str]   = None
    weight_confirmed_by:    Optional[str]   = None
    weight_source_revision: Optional[str]   = None
    # Provenance of the last operator weight action: 'manual' (override saved) |
    # 'cleared' (override removed). The LIVE effective source (packing/carrier/
    # manual/missing) is computed by the transport resolver; this column answers
    # "why is this document showing this weight" after the fact.
    weight_override_source: Optional[str]   = None
    # ── Phase 3 — wFirma post-posting enrichment fields ──────────────
    wfirma_issue_date:      Optional[str] = None   # from wFirma invoices/get
    wfirma_payment_due:     Optional[str] = None   # paymentdate from wFirma
    wfirma_payment_method:  Optional[str] = None   # payment_method from wFirma
    # ── Sprint-24 clone provenance ────────────────────────────────────
    # clone_generation=0 for original drafts; 1,2,… for successive clones.
    # source_ref_id points to the draft this row was cloned from (None for originals).
    clone_generation:       int           = 0      # 0 = original, ≥1 = clone
    source_ref_id:          Optional[int] = None   # id of the source draft if cloned
    # ── ADR-027 D4 — VAT freeze (set at draft creation; drift-checked at post)
    vat_context:     Optional[str] = None   # "domestic"|"wdt"|"export"|"np"|…
    vat_code:        Optional[str] = None   # "23"|"WDT"|"EXP"|"NP"|… (code string)
    decision_source: Optional[str] = None   # "operator_vat_mode"|"derived"|"fallback_wfirma"
    # ── Sales-price authority (PR #519) ──────────────────────────────────
    sales_price_authority_total_eur: Optional[float] = None
    sales_price_imported_at:         Optional[str]   = None
    sales_price_invoice_ref:         Optional[str]   = None
    # ── Post-conversion invoice identity (set by conversion_persistence) ────
    wfirma_invoice_id:     Optional[str] = None   # wFirma invoice id after conversion
    wfirma_invoice_number: Optional[str] = None   # full invoice number e.g. WDT 1/2026
    converted_at:          Optional[str] = None   # UTC ISO timestamp of conversion
    # ── Contractor-at-birth projection (PR-2) — additive reference only ───
    client_contractor_id:            str             = ""


def _ensure_drafts_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS proforma_drafts (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id            TEXT NOT NULL,
            client_name         TEXT NOT NULL,
            status              TEXT NOT NULL,
            currency            TEXT NOT NULL DEFAULT '',
            exchange_rate       REAL,
            source_lines_json   TEXT NOT NULL DEFAULT '[]',
            wfirma_proforma_id  TEXT,
            notes               TEXT,
            created_at          TEXT NOT NULL,
            updated_at          TEXT NOT NULL,
            UNIQUE(batch_id, client_name)
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_pd_status ON proforma_drafts(status)"
    )

    # ── Phase 1 of editable Proforma Draft lifecycle ─────────────────────
    # Additive ALTERs only. Existing rows pick up safe defaults; the
    # backfill below remaps legacy ``status`` values into the new
    # ``draft_state`` column so reads project a coherent state.
    _ADDITIVE_DRAFT_COLUMNS = (
        ("draft_state",                "TEXT NOT NULL DEFAULT 'posted'"),
        ("draft_version",              "INTEGER NOT NULL DEFAULT 1"),
        ("supersedes_draft_id",        "INTEGER"),
        ("superseded_by_draft_id",     "INTEGER"),
        ("approved_at",                "TEXT"),
        ("approved_by",                "TEXT"),
        ("posted_at",                  "TEXT"),
        ("locked_at",                  "TEXT"),
        ("wfirma_proforma_fullnumber", "TEXT NOT NULL DEFAULT ''"),
        ("buyer_override_json",        "TEXT NOT NULL DEFAULT '{}'"),
        ("ship_to_override_json",      "TEXT NOT NULL DEFAULT '{}'"),
        ("payment_terms_json",         "TEXT NOT NULL DEFAULT '{}'"),
        ("remarks",                    "TEXT NOT NULL DEFAULT ''"),
        ("editable_lines_json",        "TEXT NOT NULL DEFAULT '[]'"),
        ("service_charges_json",       "TEXT NOT NULL DEFAULT '[]'"),
        # ── Phase 5 — posting lifecycle metadata ─────────────────────
        ("posting_started_at",         "TEXT"),
        ("posting_started_by",         "TEXT"),
        ("post_failed_at",             "TEXT"),
        ("posted_by",                  "TEXT"),
        # ── Phase 6 — packing-upload auto-sync metadata ───────────
        ("last_packing_sync_at",       "TEXT"),
        ("packing_sync_warning",       "TEXT"),
        # ── Phase 7 — commercial document fields ─────────────────────────
        ("fx_rate_date",   "TEXT"),
        ("fx_rate_source", "TEXT NOT NULL DEFAULT 'NBP'"),
        ("fx_accounting_date", "TEXT"),   # PR-4: requested accounting date
        ("fx_table_number",    "TEXT"),   # PR-4: NBP Table A number
        ("incoterm",       "TEXT"),
        ("insurance_eur",  "REAL"),
        # ── PR-5 transport-document weight override (kg) ─────────────────
        ("manual_net_weight",      "REAL"),
        ("manual_gross_weight",    "REAL"),
        ("weight_override_reason", "TEXT"),
        ("weight_confirmed_at",    "TEXT"),
        ("weight_confirmed_by",    "TEXT"),
        ("weight_source_revision", "TEXT"),
        ("weight_override_source", "TEXT"),   # packing | carrier | manual | cleared
        # ── Phase 3 — wFirma post-posting enrichment fields ──────────────
        ("wfirma_issue_date",     "TEXT"),
        ("wfirma_payment_due",    "TEXT"),
        ("wfirma_payment_method", "TEXT"),
        # ── Sprint-24 clone provenance ────────────────────────────────────
        ("clone_generation", "INTEGER NOT NULL DEFAULT 0"),
        ("source_ref_id",    "INTEGER"),
        # ── ADR-027 D4 — VAT freeze ───────────────────────────────────────
        ("vat_context",     "TEXT"),
        ("vat_code",        "TEXT"),
        ("decision_source", "TEXT"),
        # ── Sales price authority (PR #519) ──────────────────────────────────
        ("sales_price_authority_total_eur", "REAL"),
        ("sales_price_imported_at",         "TEXT"),
        ("sales_price_invoice_ref",         "TEXT"),
        # ── Contractor-at-birth projection (PR-2) ─────────────────────────────
        # Authoritative Customer-Master contractor identity carried as an
        # additive REFERENCE. The draft identity key remains client_name; this
        # column never becomes the unique key (avoids re-keying service charges
        # / authority joins). Default '' = unprojected (repaired by backfill).
        ("client_contractor_id", "TEXT NOT NULL DEFAULT ''"),
        # ── Post-conversion identity (conversion_persistence.py) ─────────────
        # Previously these existed ONLY after the first persist_invoice_to_draft
        # call ran its own ALTER loop (which stays in place for old DB files).
        # Declaring them here makes a fresh schema complete at startup so
        # readers (_opt) and the reconcile route never see a half-migrated DB.
        ("wfirma_invoice_id",     "TEXT"),
        ("wfirma_invoice_number", "TEXT"),
        ("payment_due",           "TEXT"),
        ("payment_method",        "TEXT"),
        ("sale_date",             "TEXT"),
        ("converted_at",          "TEXT"),
    )
    for _col, _ddl in _ADDITIVE_DRAFT_COLUMNS:
        try:
            conn.execute(f"ALTER TABLE proforma_drafts ADD COLUMN {_col} {_ddl}")
        except sqlite3.OperationalError as exc:
            if "duplicate column" not in str(exc).lower():
                raise

    # ── Sprint-24: widen unique constraint to allow clone rows ────────────
    # Original table has UNIQUE(batch_id, client_name) as a table-level
    # constraint. Clones share the same (batch_id, client_name) but differ
    # in clone_generation. SQLite requires table recreation to change
    # constraints. Migration is idempotent: detected via presence of the
    # uq_pd_batch_client_gen index.
    _idx_exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' "
        "AND name='uq_pd_batch_client_gen'"
    ).fetchone()
    if not _idx_exists:
        # Verify sprint-24 columns were already added before recreation
        _cols_now = {r[1] for r in conn.execute("PRAGMA table_info(proforma_drafts)")}
        if "clone_generation" in _cols_now and "source_ref_id" in _cols_now:
            # Rename old table, create new with UNIQUE(batch_id, client_name, clone_generation)
            # and copy data. We read the old table's column definitions to preserve
            # types, defaults, and NOT NULL markers.
            _ci = conn.execute("PRAGMA table_info(proforma_drafts)").fetchall()
            _col_defs = []
            for _c in _ci:
                _cname = _c[1]; _ctype = _c[2] or "TEXT"
                _notnull = " NOT NULL" if _c[3] else ""
                _dflt = f" DEFAULT {_c[4]}" if _c[4] is not None else ""
                _pk = " PRIMARY KEY AUTOINCREMENT" if _c[5] == 1 else ""
                _col_defs.append(f"{_cname} {_ctype}{_pk}{_notnull}{_dflt}")
            _col_ddl = ",\n  ".join(_col_defs)
            conn.execute("ALTER TABLE proforma_drafts RENAME TO _pd_old")
            conn.execute(f"""
                CREATE TABLE proforma_drafts (
                  {_col_ddl},
                  UNIQUE(batch_id, client_name, clone_generation)
                )
            """)
            _col_names = ", ".join(c[1] for c in _ci)
            conn.execute(
                f"INSERT INTO proforma_drafts ({_col_names}) "
                f"SELECT {_col_names} FROM _pd_old"
            )
            conn.execute("DROP TABLE _pd_old")
            conn.execute(
                "CREATE UNIQUE INDEX uq_pd_batch_client_gen "
                "ON proforma_drafts(batch_id, client_name, clone_generation)"
            )

    # Backfill draft_state from legacy status. Idempotent — only fires
    # on rows where the mapped value differs from the current value.
    # Mapping (read shim mirror):
    #   issued        → posted
    #   failed        → post_failed
    #   pending_local → posting
    # Unknown legacy values fall through (left at the default 'posted').
    # Phase 2 writers MUST use a legacy status that is not in this map
    # (the new ``status='draft'`` neutral value) so re-running init_db
    # does not clobber an explicitly-set draft_state. See
    # ``_PHASE2_LEGACY_STATUS`` below.
    for legacy, new in (
        ("issued",        "posted"),
        ("failed",        "post_failed"),
        ("pending_local", "posting"),
    ):
        # 'converted' is a terminal state set by conversion_persistence.py.
        # Guard it explicitly so subsequent _ensure_drafts_table() calls do
        # not overwrite draft_state='converted' back to 'posted' when the
        # legacy status column still reads 'issued'.
        conn.execute(
            "UPDATE proforma_drafts SET draft_state=? "
            "WHERE status=? AND draft_state<>? AND draft_state<>'converted'",
            (new, legacy, new),
        )

    # ── M6 — Cross-batch search indexes (additive, non-breaking) ────────────
    # These enable the search_drafts() function to filter efficiently
    # across all batches. Only CREATE IF NOT EXISTS — safe to re-run.
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_pd_client_name "
        "ON proforma_drafts(client_name)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_pd_fullnumber "
        "ON proforma_drafts(wfirma_proforma_fullnumber)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_pd_created_at "
        "ON proforma_drafts(created_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_pd_currency "
        "ON proforma_drafts(currency)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_pd_draft_state "
        "ON proforma_drafts(draft_state)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_pd_batch_id "
        "ON proforma_drafts(batch_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_pd_wfirma_proforma_id "
        "ON proforma_drafts(wfirma_proforma_id)"
    )

    # Per-draft event log — mirrors audit.timeline at draft granularity
    # so we don't pollute the per-batch audit with every edit. Keyed by
    # draft_id (stable across restarts).
    conn.execute("""
        CREATE TABLE IF NOT EXISTS proforma_draft_events (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            draft_id    INTEGER NOT NULL,
            event       TEXT NOT NULL,
            detail_json TEXT NOT NULL DEFAULT '{}',
            operator    TEXT NOT NULL DEFAULT '',
            occurred_at TEXT NOT NULL
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_pde_draft "
        "ON proforma_draft_events(draft_id, occurred_at)"
    )

    # ── PR-2: visible draft-birth blocked records ─────────────────────────
    # When a sales packing document resolves to NEITHER a usable client_name
    # NOR a Customer-Master-resolvable client_contractor_id, the draft cannot
    # be born. Instead of the historic silent drop, sync records a visible,
    # operator-readable block here. blocked_state lifecycle: 'open' while the
    # condition holds; flipped to 'resolved' once a draft is later created for
    # that sales_document (no stale red flags — Lesson M). Keyed by
    # (batch_id, sales_document_id) so re-sync is idempotent.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS proforma_draft_birth_blocks (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id             TEXT NOT NULL,
            sales_document_id    TEXT NOT NULL,
            client_contractor_id TEXT NOT NULL DEFAULT '',
            client_name          TEXT NOT NULL DEFAULT '',
            blocked_state        TEXT NOT NULL DEFAULT 'open',
            reason               TEXT NOT NULL DEFAULT '',
            code                 TEXT NOT NULL DEFAULT '',
            lines_count          INTEGER NOT NULL DEFAULT 0,
            value                REAL NOT NULL DEFAULT 0,
            currency             TEXT NOT NULL DEFAULT '',
            created_at           TEXT NOT NULL,
            updated_at           TEXT NOT NULL,
            UNIQUE(batch_id, sales_document_id)
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_pdbb_batch "
        "ON proforma_draft_birth_blocks(batch_id, blocked_state)"
    )


# ── PR-2: draft-birth blocked-record lifecycle ────────────────────────────────

# Stable machine codes for why a draft could not be born. Operators read these
# to know what to fix. ``contractor_conflict`` is advisory (a draft IS still
# created by name) — the others are true non-creation blocks.
DRAFT_BIRTH_BLOCK_CODES = (
    "contractor_missing",   # no client_name AND no client_contractor_id
    "client_unresolved",    # client_contractor_id present but no Customer Master match
    "contractor_conflict",  # one client_name group carries >1 distinct contractor_id
)


def record_draft_birth_block(
    db_path:              Path,
    batch_id:             str,
    sales_document_id:    str,
    *,
    code:                 str,
    reason:               str,
    client_contractor_id: str = "",
    client_name:          str = "",
    lines_count:          int = 0,
    value:                float = 0.0,
    currency:             str = "",
) -> None:
    """Idempotent upsert of an OPEN draft-birth block keyed by
    (batch_id, sales_document_id). Never raises — visibility must not break
    the non-blocking sync path."""
    if not (batch_id or "").strip() or not (sales_document_id or "").strip():
        return
    now = _now_utc_iso()
    try:
        with _connect(db_path) as conn:
            _ensure_drafts_table(conn)
            conn.execute(
                """
                INSERT INTO proforma_draft_birth_blocks
                    (batch_id, sales_document_id, client_contractor_id,
                     client_name, blocked_state, reason, code,
                     lines_count, value, currency, created_at, updated_at)
                VALUES (?,?,?,?, 'open', ?,?,?,?,?,?,?)
                ON CONFLICT(batch_id, sales_document_id) DO UPDATE SET
                    client_contractor_id = excluded.client_contractor_id,
                    client_name          = excluded.client_name,
                    blocked_state        = 'open',
                    reason               = excluded.reason,
                    code                 = excluded.code,
                    lines_count          = excluded.lines_count,
                    value                = excluded.value,
                    currency             = excluded.currency,
                    updated_at           = excluded.updated_at
                """,
                (batch_id, sales_document_id, client_contractor_id,
                 client_name, reason, code,
                 int(lines_count), float(value or 0), currency, now, now),
            )
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("record_draft_birth_block failed (non-fatal): %s", exc)


def resolve_draft_birth_block(
    db_path:           Path,
    batch_id:          str,
    sales_document_id: str,
) -> None:
    """Flip any OPEN block for (batch_id, sales_document_id) to 'resolved'.
    Called when a draft IS subsequently created for that document, so a stale
    block never lingers. Never raises."""
    if not (batch_id or "").strip() or not (sales_document_id or "").strip():
        return
    now = _now_utc_iso()
    try:
        with _connect(db_path) as conn:
            _ensure_drafts_table(conn)
            conn.execute(
                "UPDATE proforma_draft_birth_blocks "
                "SET blocked_state='resolved', updated_at=? "
                "WHERE batch_id=? AND sales_document_id=? AND blocked_state='open'",
                (now, batch_id, sales_document_id),
            )
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("resolve_draft_birth_block failed (non-fatal): %s", exc)


def list_draft_birth_blocks(
    db_path:          Path,
    batch_id:         str,
    *,
    include_resolved: bool = False,
) -> List[Dict[str, Any]]:
    """Return draft-birth block records for *batch_id*. Open-only by default."""
    if not (batch_id or "").strip():
        return []
    try:
        with _connect(db_path) as conn:
            _ensure_drafts_table(conn)
            conn.row_factory = sqlite3.Row
            sql = (
                "SELECT * FROM proforma_draft_birth_blocks WHERE batch_id=?"
            )
            params: tuple = (batch_id,)
            if not include_resolved:
                sql += " AND blocked_state='open'"
            sql += " ORDER BY updated_at DESC"
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("list_draft_birth_blocks failed (non-fatal): %s", exc)
        return []


def migrate_draft_to_canonical_name(
    db_path:          Path,
    batch_id:         str,
    old_client_name:  str,
    canonical_name:   str,
    *,
    charge_move:         Optional[Callable[[str, str, str], List[Dict[str, Any]]]] = None,
    charge_drop:         Optional[Callable[[str, str], List[Dict[str, Any]]]] = None,
    reservation_migrate: Optional[Callable[[str, str, str], Dict[str, Any]]] = None,
    operator:            str = "",
) -> Dict[str, Any]:
    """PR-3: migrate EDITABLE proforma drafts for (batch_id, old_client_name) to
    *canonical_name* (the operator's Customer-Master selection wins over a parsed
    name). EDITABLE drafts only — posted/approved/posting/cancelled/superseded
    identity is FROZEN and never renamed.

    Per draft row (across ALL clone_generations):
      * a canonical-named draft already exists at the SAME clone_generation →
        the old row is SUPERSEDED (canonical wins; superseded_by points at it),
      * otherwise the old row is RENAMED in place to canonical_name.

    Charges (per name, via injected callables — keeps this module dependency-free):
      * canonical draft pre-existed (collision) → ``charge_drop`` (canonical wins;
        dropped non-zero amounts returned for operator disclosure),
      * else → ``charge_move`` (the renamed draft keeps its charges).
    Reservation draft migrated via ``reservation_migrate`` (canonical-wins inside).

    Idempotent: when ``old_client_name == canonical_name`` or no old rows exist,
    returns a no-op. Returns a report dict (renamed / superseded / skipped_frozen
    ids + dropped_charges + reservation summary).
    """
    report: Dict[str, Any] = {
        "old_client_name": old_client_name,
        "canonical_name":  canonical_name,
        "renamed":         [],
        "superseded":      [],
        "skipped_frozen":  [],
        "dropped_charges": [],
        "reservation":     {"action": "noop"},
        "action":          "noop",
    }
    if not (batch_id or "").strip() or not (old_client_name or "").strip() \
            or not (canonical_name or "").strip():
        return report
    if old_client_name == canonical_name:
        return report

    now = _now_utc_iso()
    with _connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        _ensure_drafts_table(conn)

        old_rows = conn.execute(
            "SELECT id, draft_state, clone_generation FROM proforma_drafts "
            "WHERE batch_id=? AND client_name=?",
            (batch_id, old_client_name),
        ).fetchall()
        if not old_rows:
            return report

        # Whether an EDITABLE canonical draft exists — decides whether
        # "canonical wins" can safely DROP old charges (only onto a live
        # editable canonical), vs must PRESERVE them (frozen/posted canonical
        # can never receive them — dropping would be unrecoverable money loss).
        _editable_ph = ",".join("?" * len(EDITABLE_STATES))
        canonical_editable = conn.execute(
            f"SELECT 1 FROM proforma_drafts WHERE batch_id=? AND client_name=? "
            f"AND draft_state IN ({_editable_ph}) LIMIT 1",
            (batch_id, canonical_name, *EDITABLE_STATES),
        ).fetchone() is not None

        for r in old_rows:
            state = (r["draft_state"] or "").strip()
            if state not in EDITABLE_STATES:
                report["skipped_frozen"].append({"id": r["id"], "state": state})
                continue
            gen = r["clone_generation"] if "clone_generation" in r.keys() else 0
            canon_at_gen = conn.execute(
                "SELECT id FROM proforma_drafts "
                "WHERE batch_id=? AND client_name=? AND clone_generation=? LIMIT 1",
                (batch_id, canonical_name, gen),
            ).fetchone()
            if canon_at_gen is not None:
                conn.execute(
                    "UPDATE proforma_drafts SET draft_state='superseded', "
                    "superseded_by_draft_id=?, updated_at=? WHERE id=?",
                    (canon_at_gen["id"], now, r["id"]),
                )
                report["superseded"].append(r["id"])
            else:
                conn.execute(
                    "UPDATE proforma_drafts SET client_name=?, updated_at=? WHERE id=?",
                    (canonical_name, now, r["id"]),
                )
                report["renamed"].append(r["id"])
        conn.commit()

    # ── Charges migration — OUTCOME-aware + money-safe ────────────────────────
    # The charges must follow the LIVE editable canonical draft:
    #   * renamed (the old draft BECAME canonical)        → MOVE (keep its charges)
    #   * superseded into an EDITABLE canonical (collision)→ DROP old (operator's
    #     "canonical wins"; dropped non-zero amounts are DISCLOSED)
    #   * superseded into a FROZEN canonical              → MOVE (NEVER drop onto a
    #     posted/unrecoverable draft — preserve the money, disclosed)
    #   * nothing migrated (all frozen old)              → leave charges untouched
    charge_mode = "none"
    if report["renamed"]:
        charge_mode = "move"
    elif report["superseded"]:
        charge_mode = "drop" if canonical_editable else "move"
    report["charge_mode"] = charge_mode
    try:
        if charge_mode == "drop" and charge_drop is not None:
            report["dropped_charges"] = charge_drop(batch_id, old_client_name) or []
        elif charge_mode == "move" and charge_move is not None:
            report["dropped_charges"] = \
                charge_move(batch_id, old_client_name, canonical_name) or []
    except Exception as _chg_exc:  # pragma: no cover - defensive
        log.warning("draft charge migration failed (non-fatal) %s→%s: %s",
                    old_client_name, canonical_name, _chg_exc)
    try:
        if reservation_migrate is not None:
            report["reservation"] = \
                reservation_migrate(batch_id, old_client_name, canonical_name) or {"action": "noop"}
    except Exception as _res_exc:  # pragma: no cover - defensive
        log.warning("reservation migration failed (non-fatal) %s→%s: %s",
                    old_client_name, canonical_name, _res_exc)

    report["action"] = (
        "renamed" if report["renamed"] and not report["superseded"]
        else "superseded" if report["superseded"] and not report["renamed"]
        else "mixed" if (report["renamed"] or report["superseded"])
        else "skipped"
    )
    return report


# ── Phase 1 read shim: legacy status → new draft_state mapping ────────────

# Forward map (legacy → new). Used for backfill and as a defensive read
# fallback when a row has a non-default legacy `status` but `draft_state`
# is still the column default.
_LEGACY_STATUS_TO_DRAFT_STATE: Dict[str, str] = {
    "issued":        "posted",
    "failed":        "post_failed",
    "pending_local": "posting",
    # Phase 2.5 — formalise the Phase-2 neutral legacy value. Identity
    # mapping: a row with status='draft' projects to draft_state='draft'.
    # The writer (auto_create_draft_from_sales_packing) sets both
    # columns explicitly, so this entry only matters for defence-in-depth
    # on rows where draft_state column might somehow be missing.
    "draft":         "draft",
}


def _legacy_status_to_draft_state(legacy_status: str) -> str:
    """Map a legacy ``proforma_drafts.status`` value to the canonical
    ``draft_state``. Returns ``""`` for unknown values; callers fall
    back to the row's stored ``draft_state``."""
    return _LEGACY_STATUS_TO_DRAFT_STATE.get(
        (legacy_status or "").strip(), "")


# ── Phase 2.5 writer-side guards ────────────────────────────────────────────
#
# These normalisers MUST be called by every new writer that inserts or
# updates ``proforma_drafts``. They strip whitespace, reject unknown
# values, and surface ValueError with a stable shape so callers don't
# need to reimplement validation. We do NOT install a SQL CHECK
# constraint at this phase — adding one to an existing SQLite table
# requires a full table rebuild, which is unsafe for live DBs holding
# issued Proformas. Writer-side validation is the intentionally weaker
# guard; a CHECK constraint is a Phase-7 (legacy retirement) concern.

def _normalise_draft_status(status: str) -> str:
    """Validate a value bound for ``proforma_drafts.status`` (the legacy
    column).

    Returns the trimmed canonical value. Raises ``ValueError`` for any
    value not in :data:`KNOWN_LEGACY_STATUSES`. The empty string is
    rejected — every row must carry a deterministic legacy status so
    the read shim can project a coherent ``draft_state``.
    """
    s = (status or "").strip()
    if s not in KNOWN_LEGACY_STATUSES:
        raise ValueError(
            f"unknown legacy draft status {status!r}; "
            f"expected one of {KNOWN_LEGACY_STATUSES}"
        )
    return s


def _normalise_draft_state(state: str) -> str:
    """Validate a value bound for ``proforma_drafts.draft_state`` (the
    Phase-1+ lifecycle column).

    Returns the trimmed canonical value. Raises ``ValueError`` for any
    value not in :data:`DRAFT_LIFECYCLE_STATES`.
    """
    s = (state or "").strip()
    if s not in DRAFT_LIFECYCLE_STATES:
        raise ValueError(
            f"unknown draft_state {state!r}; "
            f"expected one of {DRAFT_LIFECYCLE_STATES}"
        )
    return s


def _row_to_draft(row: sqlite3.Row) -> ProformaDraft:
    keys = row.keys()

    # Read-side draft_state shim. Backfill at migration time should
    # have already populated draft_state from legacy status, but
    # defence-in-depth: if a row arrives with a non-default legacy
    # status AND draft_state is the column default ('posted') AND the
    # legacy mapping disagrees, prefer the legacy mapping. This
    # protects against any pre-migration row that snuck past the
    # backfill (e.g. a fresh insert via a legacy code path that wrote
    # status but not draft_state).
    raw_state = row["draft_state"] if "draft_state" in keys else "posted"
    legacy_status = (row["status"] or "").strip()
    mapped_legacy = _legacy_status_to_draft_state(legacy_status)
    # The default column value on a fresh ALTER is 'posted'. If the
    # legacy status maps to something else, override.
    if mapped_legacy and raw_state == "posted" and mapped_legacy != "posted":
        draft_state = mapped_legacy
    else:
        draft_state = raw_state or "posted"

    def _opt(key: str, default=None):
        return row[key] if key in keys else default

    return ProformaDraft(
        id                 = row["id"],
        batch_id           = row["batch_id"],
        client_name        = row["client_name"],
        status             = legacy_status,
        currency           = row["currency"] or "",
        exchange_rate      = row["exchange_rate"],
        source_lines_json  = row["source_lines_json"] or "[]",
        wfirma_proforma_id = row["wfirma_proforma_id"],
        notes              = row["notes"],
        created_at         = row["created_at"],
        updated_at         = row["updated_at"],
        # Phase 1 lifecycle fields. Use defaults when columns are
        # absent (defence-in-depth — the migration adds them, but a
        # row read mid-migration on a parallel connection could
        # theoretically miss them).
        draft_state                = draft_state,
        draft_version              = int(_opt("draft_version", 1) or 1),
        supersedes_draft_id        = _opt("supersedes_draft_id"),
        superseded_by_draft_id     = _opt("superseded_by_draft_id"),
        approved_at                = _opt("approved_at"),
        approved_by                = _opt("approved_by"),
        posted_at                  = _opt("posted_at"),
        locked_at                  = _opt("locked_at"),
        wfirma_proforma_fullnumber = (_opt("wfirma_proforma_fullnumber") or ""),
        buyer_override_json        = (_opt("buyer_override_json") or "{}"),
        ship_to_override_json      = (_opt("ship_to_override_json") or "{}"),
        payment_terms_json         = (_opt("payment_terms_json") or "{}"),
        remarks                    = (_opt("remarks") or ""),
        editable_lines_json        = (_opt("editable_lines_json") or "[]"),
        service_charges_json       = (_opt("service_charges_json") or "[]"),
        posting_started_at         = _opt("posting_started_at"),
        posting_started_by         = _opt("posting_started_by"),
        post_failed_at             = _opt("post_failed_at"),
        posted_by                  = _opt("posted_by"),
        last_packing_sync_at       = _opt("last_packing_sync_at"),
        packing_sync_warning       = _opt("packing_sync_warning"),
        # ── Phase 7 — commercial document fields ─────────────────────────
        fx_rate_date               = _opt("fx_rate_date"),
        fx_rate_source             = (_opt("fx_rate_source") or "NBP"),
        fx_accounting_date         = _opt("fx_accounting_date"),
        fx_table_number            = _opt("fx_table_number"),
        incoterm                   = _opt("incoterm"),
        insurance_eur              = _opt("insurance_eur"),
        # ── PR-5 transport-document weight override ──────────────────────
        manual_net_weight          = _opt("manual_net_weight"),
        manual_gross_weight        = _opt("manual_gross_weight"),
        weight_override_reason     = _opt("weight_override_reason"),
        weight_confirmed_at        = _opt("weight_confirmed_at"),
        weight_confirmed_by        = _opt("weight_confirmed_by"),
        weight_source_revision     = _opt("weight_source_revision"),
        weight_override_source     = _opt("weight_override_source"),
        # ── Phase 3 — wFirma post-posting enrichment fields ──────────────
        wfirma_issue_date          = _opt("wfirma_issue_date"),
        wfirma_payment_due         = _opt("wfirma_payment_due"),
        wfirma_payment_method      = _opt("wfirma_payment_method"),
        # Sprint-24 clone provenance
        clone_generation           = int(_opt("clone_generation", 0) or 0),
        source_ref_id              = _opt("source_ref_id"),
        # ADR-027 D4 — VAT freeze
        vat_context                = _opt("vat_context"),
        vat_code                   = _opt("vat_code"),
        decision_source            = _opt("decision_source"),
        # ── Sales price authority ────────────────────────────────────────
        sales_price_authority_total_eur = _opt("sales_price_authority_total_eur"),
        sales_price_imported_at         = _opt("sales_price_imported_at"),
        sales_price_invoice_ref         = _opt("sales_price_invoice_ref"),
        # ── Contractor-at-birth projection (PR-2) ─────────────────────────
        client_contractor_id            = (_opt("client_contractor_id") or ""),
        # ── Post-conversion invoice identity ──────────────────────────────
        wfirma_invoice_id               = _opt("wfirma_invoice_id"),
        wfirma_invoice_number           = _opt("wfirma_invoice_number"),
        converted_at                    = _opt("converted_at"),
    )


def freeze_draft_vat_context(
    db_path:         Path,
    draft_id:        int,
    vat_context:     str,
    vat_code:        str,
    decision_source: str,
) -> None:
    """Write resolved VAT context into proforma_drafts (D4 freeze, ADR-027).

    Idempotent — safe to call multiple times; last write wins.
    Called at draft creation and, if not yet set, at first post attempt.
    """
    now = _now_utc_iso()
    with _connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        # Do NOT call _ensure_drafts_table here — the draft row exists,
        # the columns exist (added by startup migration), and calling it
        # would re-run the legacy-status backfill which overwrites draft_state.
        conn.execute(
            "UPDATE proforma_drafts "
            "SET vat_context=?, vat_code=?, decision_source=?, updated_at=? "
            "WHERE id=?",
            (vat_context, vat_code, decision_source, now, draft_id),
        )


def get_draft(
    db_path:     Path,
    batch_id:    str,
    client_name: str,
) -> Optional[ProformaDraft]:
    if not Path(db_path).exists():
        return None
    with _connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        _ensure_drafts_table(conn)
        cur = conn.execute(
            "SELECT * FROM proforma_drafts WHERE batch_id=? AND client_name=? LIMIT 1",
            (str(batch_id), str(client_name)),
        )
        row = cur.fetchone()
        return _row_to_draft(row) if row else None


def upsert_pending_draft(
    db_path:               Path,
    *,
    batch_id:              str,
    client_name:           str,
    currency:              str,
    exchange_rate:         Optional[float],
    source_lines_json:     str,
    service_charges_json:  str = "[]",
) -> tuple:
    """
    Return (ProformaDraft, was_created).

    Idempotent on (batch_id, client_name): if a draft already exists for
    that key (in any status), it is returned unchanged with was_created=False.

    Concurrency-safe: uses INSERT … ON CONFLICT DO NOTHING and detects
    whether THIS connection performed the insert by inspecting changes().
    Two concurrent callers cannot both observe was_created=True; the loser
    re-fetches the winning row and returns was_created=False. Caller logic
    is symmetric — no IntegrityError ever escapes the helper.

    Phase 6D: ``service_charges_json`` is snapshotted at create time so
    that the finance dual-write hook (and any downstream renderer) always
    reads the charges that were live when the operator confirmed the
    proforma — not a later state.  Defaults to ``"[]"`` (backward-compat).
    """
    # Validate / normalise the snapshot: must be a JSON-serialisable list.
    try:
        parsed = json.loads(service_charges_json or "[]")
        if not isinstance(parsed, list):
            parsed = []
    except Exception:
        parsed = []
    sc_json = json.dumps(parsed, ensure_ascii=False, sort_keys=True)

    init_db(db_path)
    with _connect(db_path, isolation_level="DEFERRED") as conn:
        conn.row_factory = sqlite3.Row
        _ensure_drafts_table(conn)

        now = _now_utc_iso()
        # Atomic insert-or-skip. SQLite returns rowcount=1 on insert,
        # rowcount=0 when the UNIQUE row already exists.
        conn.execute(
            """
            INSERT INTO proforma_drafts
                (batch_id, client_name, status, currency, exchange_rate,
                 source_lines_json, service_charges_json,
                 wfirma_proforma_id, notes,
                 created_at, updated_at, clone_generation)
            VALUES (?, ?, 'pending_local', ?, ?, ?, ?, NULL, NULL, ?, ?, 0)
            ON CONFLICT(batch_id, client_name, clone_generation) DO NOTHING
            """,
            (str(batch_id), str(client_name), str(currency or ""),
             exchange_rate, source_lines_json, sc_json, now, now),
        )
        # changes() reports the number of rows modified by the LAST statement
        # on this connection — survives the race because each connection has
        # its own counter.
        was_created = bool(conn.execute("SELECT changes()").fetchone()[0])
        conn.commit()

        row = conn.execute(
            "SELECT * FROM proforma_drafts WHERE batch_id=? AND client_name=? LIMIT 1",
            (str(batch_id), str(client_name)),
        ).fetchone()
        if row is None:
            # Should not happen — INSERT ON CONFLICT DO NOTHING guarantees a
            # row exists post-call when the table accepts the operation.
            raise RuntimeError(
                f"upsert_pending_draft: no row for ({batch_id!r}, {client_name!r}) "
                "after upsert — investigate concurrent delete or DB corruption"
            )
        return (_row_to_draft(row), was_created)


def mark_draft_failed(db_path: Path, batch_id: str, client_name: str,
                      *, notes: str) -> None:
    if not (notes or "").strip():
        raise ValueError("notes is required when marking failed")
    with _connect(db_path) as conn:
        _ensure_drafts_table(conn)
        cur = conn.execute(
            "UPDATE proforma_drafts SET status='failed', notes=?, updated_at=? "
            "WHERE batch_id=? AND client_name=?",
            (notes, _now_utc_iso(), str(batch_id), str(client_name)),
        )
        conn.commit()
        if cur.rowcount == 0:
            raise KeyError(f"no draft for ({batch_id!r}, {client_name!r})")


def mark_draft_cancelled_for_reissue(
    db_path:           Path,
    batch_id:          str,
    client_name:       str,
    *,
    deleted_wfirma_id: str,
    reason:            str,
) -> None:
    """
    Reset an issued draft to failed/retryable after a confirmed wFirma
    delete. Must only be called AFTER delete_invoice returned OK.

    Sets status='failed', clears wfirma_proforma_id (it no longer exists
    in wFirma), and writes the deleted id + reason to notes so the operator
    has a full audit trail. The create route treats failed as retryable —
    a subsequent POST /create will issue a fresh proforma.

    Raises KeyError if no issued draft for (batch_id, client_name) is found.
    """
    notes = (
        f"cancelled_for_reissue: deleted_wfirma_id={deleted_wfirma_id} "
        f"reason={reason}"
    )
    with _connect(db_path) as conn:
        _ensure_drafts_table(conn)
        cur = conn.execute(
            "UPDATE proforma_drafts "
            "SET status='failed', wfirma_proforma_id=NULL, notes=?, "
            "    updated_at=? "
            "WHERE batch_id=? AND client_name=? AND status='issued'",
            (notes, _now_utc_iso(), str(batch_id), str(client_name)),
        )
        conn.commit()
        if cur.rowcount == 0:
            raise KeyError(
                f"no issued draft for ({batch_id!r}, {client_name!r}) — "
                "draft may already be cancelled or was never issued"
            )


def adopt_issued_draft(
    db_path:            Path,
    batch_id:           str,
    client_name:        str,
    *,
    wfirma_proforma_id: str,
    reason:             str,
    source_lines_json:  Optional[str] = None,
) -> tuple:
    """
    Register an existing wFirma proforma that predates local draft tracking.

    Four cases:
      1. No row exists              → INSERT status='issued'
      2. Row exists, status='issued', same wfirma_proforma_id → idempotent (no-op)
      3. Row exists, status='issued', different wfirma_proforma_id
                                    → raise ValueError (caller blocks)
      4. Row exists, status='failed'|'pending_local'
                                    → UPDATE to issued with new notes

    Returns (ProformaDraft, was_created: bool).
    No wFirma writes ever happen here.
    """
    if not (wfirma_proforma_id or "").strip():
        raise ValueError("wfirma_proforma_id is required")
    if not (reason or "").strip():
        raise ValueError("reason is required")

    notes = f"adopted: wfirma_proforma_id={wfirma_proforma_id} reason={reason}"
    now   = _now_utc_iso()

    init_db(db_path)
    with _connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        _ensure_drafts_table(conn)

        existing = conn.execute(
            "SELECT * FROM proforma_drafts WHERE batch_id=? AND client_name=? LIMIT 1",
            (str(batch_id), str(client_name)),
        ).fetchone()

        if existing is None:
            conn.execute(
                """
                INSERT INTO proforma_drafts
                    (batch_id, client_name, status, currency, exchange_rate,
                     source_lines_json, wfirma_proforma_id, notes,
                     created_at, updated_at)
                VALUES (?, ?, 'issued', '', NULL, ?, ?, ?, ?, ?)
                """,
                (str(batch_id), str(client_name),
                 source_lines_json or "[]",
                 str(wfirma_proforma_id), notes, now, now),
            )
            conn.commit()
            was_created = True
        else:
            existing_wfirma_id = (existing["wfirma_proforma_id"] or "").strip()
            existing_status    = (existing["status"] or "").strip()

            if existing_status == "issued" and existing_wfirma_id == str(wfirma_proforma_id).strip():
                # Case 2 — idempotent
                row = conn.execute(
                    "SELECT * FROM proforma_drafts WHERE batch_id=? AND client_name=? LIMIT 1",
                    (str(batch_id), str(client_name)),
                ).fetchone()
                return (_row_to_draft(row), False)

            if existing_status == "issued" and existing_wfirma_id != str(wfirma_proforma_id).strip():
                # Case 3 — collision with different issued proforma
                raise ValueError(
                    f"adopt_issued_draft conflict: ({batch_id!r}, {client_name!r}) "
                    f"already has issued wfirma_proforma_id={existing_wfirma_id!r}; "
                    f"cannot adopt different id={wfirma_proforma_id!r} — "
                    "cancel the existing issued draft first"
                )

            # Case 4 — failed or pending_local → update to issued
            conn.execute(
                "UPDATE proforma_drafts "
                "SET status='issued', wfirma_proforma_id=?, notes=?, updated_at=? "
                "WHERE batch_id=? AND client_name=?",
                (str(wfirma_proforma_id), notes, now,
                 str(batch_id), str(client_name)),
            )
            conn.commit()
            was_created = False

        row = conn.execute(
            "SELECT * FROM proforma_drafts WHERE batch_id=? AND client_name=? LIMIT 1",
            (str(batch_id), str(client_name)),
        ).fetchone()
        return (_row_to_draft(row), was_created)


def mark_draft_issued(db_path: Path, batch_id: str, client_name: str,
                      *, wfirma_proforma_id: str,
                      wfirma_proforma_fullnumber: str = "") -> None:
    """Phase 9.1 — accepts optional ``wfirma_proforma_fullnumber``.

    When provided, persists the canonical operator-readable Proforma
    number alongside the wFirma id. Empty (default) preserves whatever
    is already stored, so legacy callers that don't pass the arg keep
    working unchanged.
    """
    if not (wfirma_proforma_id or "").strip():
        raise ValueError("wfirma_proforma_id is required to mark issued")
    fullnumber = (wfirma_proforma_fullnumber or "").strip()
    with _connect(db_path) as conn:
        _ensure_drafts_table(conn)
        if fullnumber:
            cur = conn.execute(
                "UPDATE proforma_drafts SET status='issued', "
                "wfirma_proforma_id=?, wfirma_proforma_fullnumber=?, "
                "updated_at=? WHERE batch_id=? AND client_name=?",
                (str(wfirma_proforma_id), fullnumber, _now_utc_iso(),
                 str(batch_id), str(client_name)),
            )
        else:
            cur = conn.execute(
                "UPDATE proforma_drafts SET status='issued', "
                "wfirma_proforma_id=?, updated_at=? "
                "WHERE batch_id=? AND client_name=?",
                (str(wfirma_proforma_id), _now_utc_iso(),
                 str(batch_id), str(client_name)),
            )
        conn.commit()
        if cur.rowcount == 0:
            raise KeyError(f"no draft for ({batch_id!r}, {client_name!r})")


def write_postposting_enrichment(
    db_path: Path,
    draft_id: int,
    *,
    wfirma_issue_date:     Optional[str],
    wfirma_payment_due:    Optional[str],
    wfirma_payment_method: Optional[str],
) -> None:
    """Phase 3 — store wFirma post-posting enrichment fields on a draft.

    Called best-effort after a successful wFirma post so that
    issue_date / payment_due / payment_method are available for
    renderer display without a second live call.

    Only the three enrichment columns are touched; all other fields
    (including the snapshot-frozen commercial fields) are left intact.
    Raises KeyError when no draft with the given id exists.
    Raises ValueError when draft_id is invalid.
    """
    if not isinstance(draft_id, int) or draft_id <= 0:
        raise ValueError(f"draft_id must be a positive int, got {draft_id!r}")
    with _connect(db_path) as conn:
        _ensure_drafts_table(conn)
        cur = conn.execute(
            "UPDATE proforma_drafts "
            "SET wfirma_issue_date=?, wfirma_payment_due=?, "
            "    wfirma_payment_method=?, updated_at=? "
            "WHERE id=?",
            (
                wfirma_issue_date,
                wfirma_payment_due,
                wfirma_payment_method,
                _now_utc_iso(),
                draft_id,
            ),
        )
        conn.commit()
        if cur.rowcount == 0:
            raise KeyError(f"no draft with id={draft_id}")


# ── Phase 2 — local editable Proforma Draft auto-create + read helpers ─────

# Legacy `status` value used when auto-creating a Phase-2 draft.
#
# We deliberately do NOT reuse one of the legacy DRAFT_STATUSES
# ("pending_local", "issued", "failed") because the schema-time
# backfill in ``_ensure_drafts_table`` re-runs on every init_db()
# call and would clobber an explicitly-set draft_state back to the
# legacy mapping. Using a neutral value outside the backfill map
# keeps the Phase 1 dual-write contract intact AND lets Phase 2
# writers store a stable lifecycle state.
#
# The read shim leaves unknown legacy values unmapped, so the raw
# draft_state column wins on read.
_PHASE2_LEGACY_STATUS = "draft"


def _record_draft_event(
    db_path:     Path,
    *,
    draft_id:    int,
    event:       str,
    detail_json: str = "{}",
    operator:    str = "",
) -> int:
    """Append an event row to ``proforma_draft_events``.

    Returns the new event row id. Idempotency is the caller's responsibility
    — events are append-only by design (an event log, not a state column).
    """
    if not isinstance(draft_id, int) or draft_id <= 0:
        raise ValueError("draft_id must be a positive int")
    if not (event or "").strip():
        raise ValueError("event is required")
    # Defensive: ensure stored detail is valid JSON. We don't parse the
    # caller's payload; we just refuse obvious corruption.
    detail = (detail_json or "").strip() or "{}"
    if not (detail.startswith("{") or detail.startswith("[")):
        raise ValueError("detail_json must be a JSON object or array")

    init_db(db_path)
    with _connect(db_path) as conn:
        _ensure_drafts_table(conn)
        cur = conn.execute(
            """
            INSERT INTO proforma_draft_events
                (draft_id, event, detail_json, operator, occurred_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (int(draft_id), str(event), detail, str(operator or ""),
             _now_utc_iso()),
        )
        conn.commit()
        return int(cur.lastrowid or 0)


def list_draft_events(
    db_path:  Path,
    draft_id: int,
) -> List[Dict[str, Any]]:
    """Return events for a draft in chronological order.

    Empty list if the draft does not exist OR has no events. Callers that
    need to distinguish missing-vs-empty should call ``get_draft_by_id``
    first.
    """
    if not Path(db_path).exists():
        return []
    with _connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        _ensure_drafts_table(conn)
        rows = conn.execute(
            "SELECT id, draft_id, event, detail_json, operator, occurred_at "
            "FROM proforma_draft_events WHERE draft_id=? "
            "ORDER BY occurred_at, id",
            (int(draft_id),),
        ).fetchall()
    return [dict(r) for r in rows]


def get_draft_by_id(db_path: Path, draft_id: int) -> Optional[ProformaDraft]:
    """Fetch a draft by its primary key. Returns None if not found."""
    if not Path(db_path).exists():
        return None
    with _connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        _ensure_drafts_table(conn)
        row = conn.execute(
            "SELECT * FROM proforma_drafts WHERE id=? LIMIT 1",
            (int(draft_id),),
        ).fetchone()
    return _row_to_draft(row) if row else None


def clone_draft(db_path: Path, source_id: int) -> ProformaDraft:
    """Create a new draft as a deep copy of the source, status=draft, unposted.

    The clone gets:
    - Same batch_id, client_name, currency, all line/charge/override JSON
    - draft_state = 'draft', draft_version = 1
    - wfirma_proforma_id = None (never posted)
    - clone_generation = max existing clone_generation for this (batch, client) + 1
    - source_ref_id = source_id

    The source draft is NOT modified in any way.
    Raises KeyError if source_id not found.
    """
    import json as _json
    now = _now_utc_iso()
    init_db(db_path)
    with _connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        _ensure_drafts_table(conn)

        src_row = conn.execute(
            "SELECT * FROM proforma_drafts WHERE id=? LIMIT 1",
            (int(source_id),),
        ).fetchone()
        if src_row is None:
            raise KeyError(f"source draft {source_id} not found")

        src = _row_to_draft(src_row)

        # Determine next clone_generation for this (batch_id, client_name) pair
        max_gen_row = conn.execute(
            "SELECT MAX(clone_generation) FROM proforma_drafts "
            "WHERE batch_id=? AND client_name=?",
            (src.batch_id, src.client_name),
        ).fetchone()
        next_gen = (max_gen_row[0] or 0) + 1

        conn.execute(
            """
            INSERT INTO proforma_drafts (
                batch_id, client_name, status, currency, exchange_rate,
                source_lines_json, editable_lines_json, service_charges_json,
                buyer_override_json, ship_to_override_json, payment_terms_json,
                remarks, incoterm, fx_rate_source,
                draft_state, draft_version,
                wfirma_proforma_id, wfirma_proforma_fullnumber,
                notes, created_at, updated_at,
                clone_generation, source_ref_id
            ) VALUES (
                ?, ?, 'draft', ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                'draft', 1,
                NULL, '',
                ?, ?, ?,
                ?, ?
            )
            """,
            (
                src.batch_id, src.client_name,
                src.currency, src.exchange_rate,
                src.source_lines_json, src.editable_lines_json, src.service_charges_json,
                src.buyer_override_json, src.ship_to_override_json, src.payment_terms_json,
                src.remarks, src.incoterm, src.fx_rate_source,
                f"Cloned from draft #{source_id}",
                now, now,
                next_gen, source_id,
            ),
        )
        new_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()

        new_row = conn.execute(
            "SELECT * FROM proforma_drafts WHERE id=? LIMIT 1",
            (int(new_id),),
        ).fetchone()
    return _row_to_draft(new_row)


def list_drafts_for_batch(db_path: Path, batch_id: str) -> List[ProformaDraft]:
    """Return every draft row for a batch, oldest-first."""
    if not Path(db_path).exists():
        return []
    with _connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        _ensure_drafts_table(conn)
        rows = conn.execute(
            "SELECT * FROM proforma_drafts WHERE batch_id=? "
            "ORDER BY created_at, id",
            (str(batch_id),),
        ).fetchall()
    return [_row_to_draft(r) for r in rows]


def search_drafts(
    db_path: Path,
    *,
    filters: Optional[Dict[str, Any]] = None,
    page: int = 1,
    page_size: int = 25,
) -> Dict[str, Any]:
    """Cross-batch proforma draft search with filtering and pagination.

    M6 Prior Proforma Search — the first authoritative cross-batch
    read-only index. Authority source: proforma_drafts table ONLY.

    Args:
        db_path: Path to proforma_links.db
        filters: Dict with optional keys:
            - batch_id: exact match
            - client_name: partial match (LIKE %value%)
            - wfirma_proforma_id: exact match
            - wfirma_proforma_fullnumber: exact or prefix match (LIKE value%)
            - draft_state: exact match
            - currency: exact match
            - date_from: created_at >= value (ISO 8601 string)
            - date_to: created_at <= value (ISO 8601 string)
        page: 1-based page number (default 1)
        page_size: results per page (default 25, max 100)

    Returns:
        {
            "results": [ProformaDraft, ...],
            "total": int,
            "page": int,
            "page_size": int,
        }
    """
    if filters is None:
        filters = {}

    # Clamp pagination
    page = max(1, int(page))
    page_size = max(1, min(100, int(page_size)))

    if not Path(db_path).exists():
        return {"results": [], "total": 0, "page": page, "page_size": page_size}

    # Build WHERE clause from filters
    conditions: List[str] = []
    params: List[Any] = []

    if filters.get("batch_id"):
        conditions.append("batch_id = ?")
        params.append(str(filters["batch_id"]))

    if filters.get("client_name"):
        conditions.append("client_name LIKE ?")
        params.append(f"%{filters['client_name']}%")

    if filters.get("wfirma_proforma_id"):
        conditions.append("wfirma_proforma_id = ?")
        params.append(str(filters["wfirma_proforma_id"]))

    if filters.get("wfirma_proforma_fullnumber"):
        conditions.append("wfirma_proforma_fullnumber LIKE ?")
        params.append(f"{filters['wfirma_proforma_fullnumber']}%")

    if filters.get("draft_state"):
        conditions.append("draft_state = ?")
        params.append(str(filters["draft_state"]))

    if filters.get("currency"):
        conditions.append("currency = ?")
        params.append(str(filters["currency"]))

    if filters.get("date_from"):
        conditions.append("created_at >= ?")
        params.append(str(filters["date_from"]))

    if filters.get("date_to"):
        conditions.append("created_at <= ?")
        params.append(str(filters["date_to"]))

    where_clause = ""
    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    with _connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        _ensure_drafts_table(conn)

        # Count total matching rows
        count_sql = f"SELECT COUNT(*) FROM proforma_drafts {where_clause}"
        total = conn.execute(count_sql, params).fetchone()[0]

        # Fetch paginated results, newest first
        offset = (page - 1) * page_size
        query_sql = (
            f"SELECT * FROM proforma_drafts {where_clause} "
            f"ORDER BY created_at DESC, id DESC "
            f"LIMIT ? OFFSET ?"
        )
        rows = conn.execute(
            query_sql, params + [page_size, offset]
        ).fetchall()

    results = [_row_to_draft(r) for r in rows]
    return {
        "results": results,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def list_attention_drafts(
    db_path: Path,
    *,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Cross-batch scan for proforma drafts that need operator attention.

    Returns a list of lightweight dicts (NOT full ProformaDraft objects)
    suitable for the inbox aggregator.  Read-only.  Never mutates.

    Attention states (non-terminal, non-completed):
        draft       — new draft, needs operator review
        editing     — operator is working on it
        approved    — locked, ready to post to wFirma
        post_failed — wFirma rejected, needs operator retry
        posting     — submission in progress (may be stuck)

    Excluded states (terminal / completed):
        posted, cancelled, superseded

    Sorted by updated_at DESC so the most recently touched drafts
    appear first — same ordering convention as the inbox aggregator.
    """
    limit = max(1, min(200, int(limit)))
    if not Path(db_path).exists():
        return []

    attention_states = ("draft", "editing", "approved", "post_failed", "posting")
    placeholders = ", ".join("?" for _ in attention_states)

    with _connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        _ensure_drafts_table(conn)
        rows = conn.execute(
            f"SELECT id, batch_id, client_name, draft_state, currency, "
            f"       wfirma_proforma_fullnumber, updated_at, created_at, "
            f"       post_failed_at "
            f"FROM proforma_drafts "
            f"WHERE draft_state IN ({placeholders}) "
            f"ORDER BY updated_at DESC "
            f"LIMIT ?",
            (*attention_states, limit),
        ).fetchall()

    results: List[Dict[str, Any]] = []
    for row in rows:
        state = row["draft_state"]
        results.append({
            "id":               row["id"],
            "batch_id":         row["batch_id"],
            "client_name":      row["client_name"],
            "draft_state":      state,
            "currency":         row["currency"] or "",
            "fullnumber":       row["wfirma_proforma_fullnumber"] or "",
            "updated_at":       row["updated_at"] or "",
            "created_at":       row["created_at"] or "",
            "post_failed_at":   row["post_failed_at"] or "",
        })
    return results




def _birth_unresolved_lines(
    lines:          List[Dict[str, Any]],
    mapping_lookup: Optional[Callable[[str], Optional[Dict[str, Any]]]] = None,
) -> List[Dict[str, Any]]:
    """Non-authoritative birth advisory.

    Flags, per line:
      * ``zero_unit_price``         — unit_price missing or <= 0;
      * ``missing_product_mapping`` — ONLY when ``mapping_lookup`` is supplied
        AND the product has no ``wfirma_product_id``. This mirrors the
        readiness authority's §3 check, read-only — it NEVER writes wFirma.
        With no lookup supplied the mapping is simply not assessed (no flag),
        so the default behaviour is unchanged.

    This is a VISIBILITY surface recorded in the draft event log only — it is
    NOT readiness truth, it is NOT stored on the draft row, and it does NOT
    block creation. The single readiness authority
    (:func:`_derive_draft_readiness`) re-derives blockers on read/post.
    """
    out: List[Dict[str, Any]] = []
    for ln in lines:
        reasons: List[str] = []
        try:
            up = float(ln.get("unit_price", 0) or 0)
        except (TypeError, ValueError):
            up = 0.0
        if up <= 0:
            reasons.append("zero_unit_price")
        if mapping_lookup is not None:
            pc = str(ln.get("product_code") or "").strip()
            mapped = False
            if pc:
                try:
                    row = mapping_lookup(pc)
                    mapped = bool((row or {}).get("wfirma_product_id"))
                except Exception:
                    mapped = False
            if not mapped:
                reasons.append("missing_product_mapping")
        if reasons:
            out.append({
                "product_code": str(ln.get("product_code") or ""),
                "design_no":    str(ln.get("design_no") or ""),
                "reasons":      reasons,
            })
    return out


def _sales_variant_fields(ln: Dict[str, Any]) -> Dict[str, Any]:
    """Variant-identity passthrough from a sales_packing_lines row.

    These columns exist on sales_packing_lines (document_db) but were
    historically dropped at the draft birth/reset boundary — same
    silent-drop class as the client_po/invoice_no fix of 2026-07-02.
    Display/identity only: never used for pricing, readiness, or totals.
    NOT ``item_type`` — enrichment owns that key and overwrites it.
    """
    def _wt(key: str) -> float:
        try:
            return float(ln.get(key, 0) or 0)
        except (TypeError, ValueError):
            return 0.0
    return {
        "client_po":      str(ln.get("client_po") or ""),
        "karat":          str(ln.get("karat") or ""),
        "metal":          str(ln.get("metal") or ""),
        "metal_color":    str(ln.get("metal_color") or ""),
        "quality_string": str(ln.get("quality_string") or ""),
        "stone_type":     str(ln.get("stone_type") or ""),
        "size":           str(ln.get("size") or ""),
        "diamond_weight": _wt("diamond_weight"),
        "color_weight":   _wt("color_weight"),
    }


def auto_create_draft_from_sales_packing(
    db_path:       Path,
    *,
    batch_id:      str,
    client_name:   str,
    currency:      str,
    lines:         List[Dict[str, Any]],
    operator:      str = "",
    client_contractor_id: str = "",
    name_pl_lookup: Optional[Callable[[str], Optional[Dict[str, Any]]]] = None,
    desc_generate:  Optional[Callable[..., Optional[str]]] = None,
    product_mapping_lookup: Optional[Callable[[str], Optional[Dict[str, Any]]]] = None,
) -> tuple:
    """Phase 2 — create a v=1 editable draft for (batch_id, client_name).

    Idempotent. Returns ``(ProformaDraft, was_created: bool)``. If a draft
    already exists for this key in any state OTHER than ``cancelled`` or
    ``superseded``, the existing row is returned unchanged with
    ``was_created=False`` and no event is emitted.

    ``lines`` is a list of dicts mirroring sales_packing_lines columns:
      product_code, design_no, quantity (or qty), unit_price, currency,
      price_source, client_ref, remarks (optional)

    Lines are normalised into the ``editable_lines_json`` shape:
      {product_code, design_no, qty, unit_price, currency, price_source,
       client_ref, name_pl}

    ``name_pl`` is carried through from the caller (operator-confirmed
    values are preserved) and blank values are filled from the
    product_descriptions authority when ``name_pl_lookup`` is supplied — it
    is never fabricated. A blank name_pl or a zero/missing unit_price is
    recorded in the ``created_from_sales_packing`` event ``birth_unresolved``
    advisory (visibility only; not readiness truth, never blocks creation).

    NB: this never mutates pricing, currency, price_source or totals — it
    only persists what the caller passed plus the name_pl annotation.
    Recalculation and readiness remain the engine's job.
    """
    if not (batch_id or "").strip():
        raise ValueError("batch_id is required")
    if not (client_name or "").strip():
        raise ValueError("client_name is required")

    # Normalise lines defensively. Skip rows with no product_code —
    # product_code is required for sales/proforma identity; design_no alone
    # is not invoiceable.
    editable: List[Dict[str, Any]] = []
    # source_lines_json is the IMMUTABLE raw-source record. It must contain
    # ONLY the fields the caller supplied (the sales_packing columns) and must
    # NEVER carry the editable/annotation shape. We build it in lock-step with
    # the editable rows but deliberately exclude the name_pl annotation and the
    # transient _gen_attrs, so the birth INSERT cannot pollute source with
    # derived data (#593 Cluster A). editable_lines_json is the working copy
    # that carries name_pl and is the only one enrichment/readiness may mutate.
    source: List[Dict[str, Any]] = []
    for ln in (lines or []):
        product_code = str(ln.get("product_code") or "").strip()
        design_no    = str(ln.get("design_no") or "").strip()
        if not product_code:
            continue
        qty = ln.get("qty", ln.get("quantity", 0)) or 0
        try:
            qty_f = float(qty)
        except (TypeError, ValueError):
            qty_f = 0.0
        try:
            up_f = float(ln.get("unit_price", 0) or 0)
        except (TypeError, ValueError):
            up_f = 0.0
        # Raw immutable source projection — sales_packing columns only.
        raw_row = {
            "product_code": product_code,
            "design_no":    design_no,
            "qty":          qty_f,
            "unit_price":   up_f,
            "currency":     str(ln.get("currency") or currency or "").upper(),
            "price_source": str(ln.get("price_source") or ""),
            "client_ref":   str(ln.get("client_ref") or ""),
            # Variant identity (also sales_packing columns) — display only.
            **_sales_variant_fields(ln),
        }
        source.append(dict(raw_row))
        # Editable copy starts from the same raw values, then gains the
        # annotation fields that source must never hold.
        row = dict(raw_row)
        # Carry any operator-confirmed/source name_pl through the birth
        # boundary on the EDITABLE copy only. Blank by default;
        row["name_pl"] = str(ln.get("name_pl") or "").strip()
        editable.append(row)

    init_db(db_path)
    now = _now_utc_iso()
    with _connect(db_path, isolation_level="DEFERRED") as conn:
        conn.row_factory = sqlite3.Row
        _ensure_drafts_table(conn)

        existing = conn.execute(
            "SELECT * FROM proforma_drafts WHERE batch_id=? AND client_name=? LIMIT 1",
            (str(batch_id), str(client_name)),
        ).fetchone()

        cid = str(client_contractor_id or "").strip()
        if existing is not None:
            existing_state = (existing["draft_state"] or "").strip()
            # Only treat cancelled/superseded as "gone" for idempotency
            # — every other state means "draft already exists, do not
            # touch it". Phase 2 never replaces lines on a live draft.
            if existing_state not in ("cancelled", "superseded"):
                # PR-2 merge-not-replace: backfill the contractor reference on
                # a live draft only when currently empty. Never changes
                # client_name (the identity key) and never touches lines/price.
                try:
                    existing_cid = (existing["client_contractor_id"] or "").strip()
                except (KeyError, IndexError):
                    existing_cid = ""
                if cid and not existing_cid:
                    conn.execute(
                        "UPDATE proforma_drafts SET client_contractor_id=? "
                        "WHERE id=?",
                        (cid, existing["id"]),
                    )
                    conn.commit()
                    existing = conn.execute(
                        "SELECT * FROM proforma_drafts WHERE id=? LIMIT 1",
                        (existing["id"],),
                    ).fetchone()
                return (_row_to_draft(existing), False)

        # Either no row, or the existing row was cancelled/superseded. The
        # UNIQUE(batch_id, client_name) constraint prevents inserting a
        # second row, so cancelled/superseded → we'd need a Phase-7-style
        # archive/replace flow. For Phase 2 we treat that as "do nothing
        # and return existing" to avoid a unique-violation crash.
        if existing is not None:
            return (_row_to_draft(existing), False)

        # Phase 2.5 writer-side guard: validate the legacy status + new
        # state pair against the formal compatibility surface BEFORE
        # we hit the DB. These two raise ValueError on unknown values
        # so a coding mistake in a future writer fails loudly here
        # rather than silently writing an unmappable row.
        legacy_status = _normalise_draft_status(_PHASE2_LEGACY_STATUS)
        initial_state = _normalise_draft_state("draft")

        # Pop transient _gen_attrs — never persisted to editable_lines_json.
        # description_pl comes from the canonical description engine (CPA authority),
        # not from birth-time name_pl resolution.
        for _ln in editable:
            _ln.pop("_gen_attrs", None)
        birth_unresolved = _birth_unresolved_lines(editable, product_mapping_lookup)

        # source_lines_json gets the raw snapshot; editable_lines_json gets the
        # name_pl-annotated working copy. These are intentionally DISTINCT — a
        # single shared blob is the #593 Cluster A pollution bug.
        source_json   = json.dumps(source,   ensure_ascii=False, sort_keys=True)
        editable_json = json.dumps(editable, ensure_ascii=False, sort_keys=True)
        cur = conn.execute(
            """
            INSERT INTO proforma_drafts
                (batch_id, client_name, status, currency, exchange_rate,
                 source_lines_json, wfirma_proforma_id, notes,
                 created_at, updated_at,
                 draft_state, draft_version, editable_lines_json,
                 service_charges_json, buyer_override_json,
                 ship_to_override_json, payment_terms_json, remarks,
                 wfirma_proforma_fullnumber, client_contractor_id)
            VALUES (?, ?, ?, ?, NULL, ?, NULL, NULL, ?, ?,
                    ?, 1, ?,
                    '[]', '{}', '{}', '{}', '', '', ?)
            """,
            (str(batch_id), str(client_name), legacy_status,
             str(currency or "").upper(),
             source_json, now, now,
             initial_state, editable_json, cid),
        )
        conn.commit()
        new_id = int(cur.lastrowid or 0)

        row = conn.execute(
            "SELECT * FROM proforma_drafts WHERE id=? LIMIT 1",
            (new_id,),
        ).fetchone()
        if row is None:
            raise RuntimeError(
                f"auto_create_draft_from_sales_packing: insert lost for "
                f"({batch_id!r}, {client_name!r})"
            )

    # Event recording uses its own connection — outside the main txn so a
    # consumer reading the DB sees the draft+event together once committed.
    _record_draft_event(
        db_path,
        draft_id    = new_id,
        event       = "created_from_sales_packing",
        detail_json = json.dumps({
            "batch_id":    str(batch_id),
            "client_name": str(client_name),
            "currency":    str(currency or "").upper(),
            "line_count":  len(editable),
            # Non-authoritative birth advisory: lines born with a blank
            # commercial description or zero/missing unit_price. Visibility
            # only — readiness remains backend-derived on read/post.
            "birth_unresolved": birth_unresolved,
        }, ensure_ascii=False, sort_keys=True),
        operator    = operator or "",
    )
    return (_row_to_draft(row), True)


# ── Phase 3 — editable draft mutation API ───────────────────────────────────

# Lifecycle states in which mutation is permitted. Posted/posting/cancelled/
# superseded/approved drafts MUST NOT be edited.
EDITABLE_STATES = ("draft", "editing", "post_failed")

# Currencies the project deals in. Mirrors the intake-route allowlist.
ALLOWED_CURRENCIES = ("EUR", "USD", "PLN", "GBP", "CHF", "JPY")

# Allowed top-level fields on PATCH /draft/{id}. Mutation is line-by-line
# for editable_lines, so it is intentionally NOT in this set.
EDITABLE_DRAFT_FIELDS = (
    "remarks",
    "buyer_override",
    "ship_to_override",
    "payment_terms",
    "currency",          # bulk currency change at draft level
    "exchange_rate",
    "incoterm",          # Phase 7: per-shipment incoterm
    "insurance_eur",     # Phase 7: declared shipment insurance EUR
)

# Allowed per-line patch fields.
EDITABLE_LINE_FIELDS = (
    "qty",
    "unit_price",
    "currency",
    "product_code",
    "design_no",
    "client_ref",
    "price_source",
    "remarks",
    # PR #199: operator override layer.  item_type and name_pl normally
    # come from product_descriptions (via enrich_lines_from_product_
    # descriptions) but the operator must be able to set them per-line
    # before posting — drafts are the override surface.  Enrich remains
    # available as a helper but is no longer the only path.
    "item_type",
    "name_pl",
)

ALLOWED_SERVICE_CHARGE_TYPES = ("freight", "insurance")

# PR-6 — the resolution vocabulary is OWNED by the commercial_charge_authority
# (the reader). The writer imports it so add/update persist only valid states.
from .commercial_charge_authority import (  # noqa: E402
    RESOLUTION_STATES,
    RESOLUTION_CALCULATED,
)


# ── C-3g: service-charge product metadata registry ───────────────────────────
# PROFORMA-authority store for service-charge line emission metadata
# (display label, informational vat_rate, unit). Identity (wfirma_product_id)
# lives ONLY in wfirma_product_mirror — never here.

def upsert_service_product_meta(
    db_path: Path,
    charge_type: str,
    *,
    product_name: str = "",
    vat_rate: str = "23",
    unit: str = "szt.",
) -> None:
    """Insert or replace the emission metadata for a service charge type."""
    ct = (charge_type or "").strip().lower()
    if ct not in ALLOWED_SERVICE_CHARGE_TYPES:
        raise ValueError(
            f"charge_type {charge_type!r} not allowed; "
            f"expected one of {ALLOWED_SERVICE_CHARGE_TYPES}"
        )
    init_db(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO service_product_registry "
            "(charge_type, product_name, vat_rate, unit, updated_at) "
            "VALUES (?,?,?,?,?) "
            "ON CONFLICT(charge_type) DO UPDATE SET "
            "product_name=excluded.product_name, vat_rate=excluded.vat_rate, "
            "unit=excluded.unit, updated_at=excluded.updated_at",
            (ct, (product_name or "").strip(), (vat_rate or "23").strip(),
             (unit or "szt.").strip(), _now_utc_iso()),
        )
        conn.commit()


def get_service_product_meta(db_path: Path, charge_type: str) -> Optional[Dict[str, Any]]:
    """Return {product_name, vat_rate, unit} for a charge type, or None."""
    ct = (charge_type or "").strip().lower()
    init_db(db_path)
    with _connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT charge_type, product_name, vat_rate, unit, updated_at "
            "FROM service_product_registry WHERE charge_type=?", (ct,)
        ).fetchone()
    return dict(row) if row else None


def get_all_service_product_meta(db_path: Path) -> Dict[str, Dict[str, Any]]:
    """Return {charge_type: {product_name, vat_rate, unit, updated_at}}."""
    init_db(db_path)
    with _connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT charge_type, product_name, vat_rate, unit, updated_at "
            "FROM service_product_registry"
        ).fetchall()
    return {r["charge_type"]: dict(r) for r in rows}


# Keys that must never appear in formula_basis — they would bleed
# customs / import cost data into a service charge formula.
_FORBIDDEN_FORMULA_BASIS_PREFIXES = (
    "cif", "customs", "import_cost", "pz_", "sad_", "zc429_",
)


class DraftNotFound(Exception):
    """Raised when a draft id has no matching row."""


class DraftNotEditable(Exception):
    """Raised when an edit is attempted on a non-editable draft state."""


class DraftConflict(Exception):
    """Raised when expected_updated_at does not match the row's
    current ``updated_at`` (optimistic-lock violation)."""


class OverwriteRequired(ValueError):
    """Raised when bulk_price_recovery would overwrite existing non-zero
    prices without ``confirm_overwrite=True``.

    ``codes`` lists every product_code that would be overwritten.
    """

    def __init__(self, codes: List[str]) -> None:
        self.codes = list(codes)
        super().__init__(
            f"confirm_overwrite required: {len(self.codes)} line(s) already "
            f"have unit_price > 0: {self.codes}"
        )


def _next_state_after_edit(current: str) -> str:
    """First successful edit on a ``draft`` row promotes it to ``editing``.

    ``post_failed`` rows STAY in ``post_failed`` after edits — the operator
    must explicitly re-trigger posting (Phase 5) once they're satisfied;
    this avoids accidentally hiding a failed-post from the dashboard's
    "needs attention" filter. ``editing`` rows stay in ``editing``.
    """
    if current == "post_failed":
        return "post_failed"
    return "editing"


def _ensure_line_ids(lines: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Guarantee every editable_lines entry has a stable integer ``line_id``.

    Phase 2 wrote lines without ids; Phase 3 needs ids so PATCH-by-id is
    deterministic. We assign 1-based ids in array order, preserving any
    pre-existing ids. Read-only — caller persists the result if needed.
    """
    out: List[Dict[str, Any]] = []
    used = {int(l["line_id"]) for l in lines if isinstance(l.get("line_id"), int) and l["line_id"] > 0}
    next_id = (max(used) if used else 0) + 1
    for ln in lines:
        existing = ln.get("line_id")
        if isinstance(existing, int) and existing > 0:
            out.append({**ln})
        else:
            out.append({**ln, "line_id": next_id})
            next_id += 1
    return out


def _validate_currency(ccy: str) -> str:
    c = (ccy or "").strip().upper()
    if c not in ALLOWED_CURRENCIES:
        raise ValueError(
            f"currency {ccy!r} not allowed; expected one of {ALLOWED_CURRENCIES}"
        )
    return c


def _check_editable(d: ProformaDraft) -> None:
    if d.draft_state not in EDITABLE_STATES:
        raise DraftNotEditable(
            f"draft id={d.id} is in state {d.draft_state!r}; "
            f"only {EDITABLE_STATES} are editable"
        )


def _check_lock(d: ProformaDraft, expected_updated_at: str) -> None:
    if not (expected_updated_at or "").strip():
        raise DraftConflict("expected_updated_at is required")
    if (d.updated_at or "") != str(expected_updated_at).strip():
        raise DraftConflict(
            f"draft id={d.id} updated_at={d.updated_at!r} does not match "
            f"expected_updated_at={expected_updated_at!r} — refresh and retry"
        )


_UNCHANGED = "__unchanged__"


def _commit_draft_update(
    db_path:               Path,
    draft_id:              int,
    *,
    new_state:             str,
    new_remarks:           Optional[str]                = None,
    new_currency:          Optional[str]                = None,
    new_exchange_rate:     Any                          = _UNCHANGED,
    new_buyer_override:    Optional[Dict[str, Any]]     = None,
    new_ship_to_override:  Optional[Dict[str, Any]]     = None,
    new_payment_terms:     Optional[Dict[str, Any]]     = None,
    new_editable_lines:    Optional[List[Dict[str, Any]]] = None,
    new_service_charges:   Optional[List[Dict[str, Any]]] = None,
    new_approved_at:       Any                          = _UNCHANGED,
    new_approved_by:       Any                          = _UNCHANGED,
    new_locked_at:         Any                          = _UNCHANGED,
    new_status:            Optional[str]                = None,
    new_notes:             Any                          = _UNCHANGED,
    new_wfirma_proforma_id:         Any                 = _UNCHANGED,
    new_wfirma_proforma_fullnumber: Any                 = _UNCHANGED,
    new_posted_at:                  Any                 = _UNCHANGED,
    new_posted_by:                  Any                 = _UNCHANGED,
    new_posting_started_at:         Any                 = _UNCHANGED,
    new_posting_started_by:         Any                 = _UNCHANGED,
    new_post_failed_at:             Any                 = _UNCHANGED,
    # ── Phase 7 — commercial document fields ─────────────────────────
    new_incoterm:                   Any                 = _UNCHANGED,
    new_insurance_eur:              Any                 = _UNCHANGED,
    new_fx_rate_date:               Any                 = _UNCHANGED,
    new_fx_rate_source:             Any                 = _UNCHANGED,
    new_fx_accounting_date:         Any                 = _UNCHANGED,
    new_fx_table_number:            Any                 = _UNCHANGED,
    # ── PR-5 transport-document weight override ──────────────────────
    new_manual_net_weight:          Any                 = _UNCHANGED,
    new_manual_gross_weight:        Any                 = _UNCHANGED,
    new_weight_override_reason:     Any                 = _UNCHANGED,
    new_weight_confirmed_at:        Any                 = _UNCHANGED,
    new_weight_confirmed_by:        Any                 = _UNCHANGED,
    new_weight_source_revision:     Any                 = _UNCHANGED,
    new_weight_override_source:     Any                 = _UNCHANGED,
    # ── Sales price authority ────────────────────────────────────────
    new_sales_price_authority_total_eur: Any            = _UNCHANGED,
    new_sales_price_imported_at:         Any            = _UNCHANGED,
    new_sales_price_invoice_ref:         Any            = _UNCHANGED,
) -> ProformaDraft:
    """Commit a validated patch atomically, returning the refreshed row.

    Only fields explicitly passed are written. ``new_state`` is required
    so callers always make the lifecycle transition decision.
    """
    state = _normalise_draft_state(new_state)
    sets: List[str] = ["draft_state=?", "updated_at=?"]
    args: List[Any] = [state, _now_utc_iso()]

    if new_remarks is not None:
        sets.append("remarks=?")
        args.append(str(new_remarks))
    if new_currency is not None:
        sets.append("currency=?")
        args.append(str(new_currency).upper())
    if new_exchange_rate != _UNCHANGED:
        sets.append("exchange_rate=?")
        args.append(new_exchange_rate)
    if new_buyer_override is not None:
        sets.append("buyer_override_json=?")
        args.append(json.dumps(new_buyer_override, ensure_ascii=False, sort_keys=True))
    if new_ship_to_override is not None:
        sets.append("ship_to_override_json=?")
        args.append(json.dumps(new_ship_to_override, ensure_ascii=False, sort_keys=True))
    if new_payment_terms is not None:
        sets.append("payment_terms_json=?")
        args.append(json.dumps(new_payment_terms, ensure_ascii=False, sort_keys=True))
    if new_editable_lines is not None:
        sets.append("editable_lines_json=?")
        args.append(json.dumps(new_editable_lines, ensure_ascii=False, sort_keys=True))
    if new_service_charges is not None:
        sets.append("service_charges_json=?")
        args.append(json.dumps(new_service_charges, ensure_ascii=False, sort_keys=True))
    if new_approved_at != _UNCHANGED:
        sets.append("approved_at=?")
        args.append(new_approved_at)
    if new_approved_by != _UNCHANGED:
        sets.append("approved_by=?")
        args.append(new_approved_by)
    if new_locked_at != _UNCHANGED:
        sets.append("locked_at=?")
        args.append(new_locked_at)
    if new_status is not None:
        # Phase 4: keep legacy status column in lockstep with lifecycle
        # transitions for cancel (status='failed' is closest to cancelled)
        # and approve (legacy 'pending_local'). Always validated.
        sets.append("status=?")
        args.append(_normalise_draft_status(new_status))
    if new_notes != _UNCHANGED:
        sets.append("notes=?")
        args.append(new_notes)
    if new_wfirma_proforma_id != _UNCHANGED:
        sets.append("wfirma_proforma_id=?")
        args.append(new_wfirma_proforma_id)
    if new_wfirma_proforma_fullnumber != _UNCHANGED:
        sets.append("wfirma_proforma_fullnumber=?")
        args.append(new_wfirma_proforma_fullnumber)
    if new_posted_at != _UNCHANGED:
        sets.append("posted_at=?")
        args.append(new_posted_at)
    if new_posted_by != _UNCHANGED:
        sets.append("posted_by=?")
        args.append(new_posted_by)
    if new_posting_started_at != _UNCHANGED:
        sets.append("posting_started_at=?")
        args.append(new_posting_started_at)
    if new_posting_started_by != _UNCHANGED:
        sets.append("posting_started_by=?")
        args.append(new_posting_started_by)
    if new_post_failed_at != _UNCHANGED:
        sets.append("post_failed_at=?")
        args.append(new_post_failed_at)
    # ── Phase 7 — commercial document fields ─────────────────────────
    if new_incoterm != _UNCHANGED:
        sets.append("incoterm=?")
        args.append(new_incoterm)
    if new_insurance_eur != _UNCHANGED:
        sets.append("insurance_eur=?")
        args.append(new_insurance_eur)
    if new_fx_rate_date != _UNCHANGED:
        sets.append("fx_rate_date=?")
        args.append(new_fx_rate_date)
    if new_fx_rate_source != _UNCHANGED:
        sets.append("fx_rate_source=?")
        args.append(new_fx_rate_source)
    if new_fx_accounting_date != _UNCHANGED:
        sets.append("fx_accounting_date=?")
        args.append(new_fx_accounting_date)
    if new_fx_table_number != _UNCHANGED:
        sets.append("fx_table_number=?")
        args.append(new_fx_table_number)
    # ── PR-5 transport-document weight override ──────────────────────
    if new_manual_net_weight != _UNCHANGED:
        sets.append("manual_net_weight=?")
        args.append(new_manual_net_weight)
    if new_manual_gross_weight != _UNCHANGED:
        sets.append("manual_gross_weight=?")
        args.append(new_manual_gross_weight)
    if new_weight_override_reason != _UNCHANGED:
        sets.append("weight_override_reason=?")
        args.append(new_weight_override_reason)
    if new_weight_confirmed_at != _UNCHANGED:
        sets.append("weight_confirmed_at=?")
        args.append(new_weight_confirmed_at)
    if new_weight_confirmed_by != _UNCHANGED:
        sets.append("weight_confirmed_by=?")
        args.append(new_weight_confirmed_by)
    if new_weight_source_revision != _UNCHANGED:
        sets.append("weight_source_revision=?")
        args.append(new_weight_source_revision)
    if new_weight_override_source != _UNCHANGED:
        sets.append("weight_override_source=?")
        args.append(new_weight_override_source)
    # ── Sales price authority ────────────────────────────────────────
    if new_sales_price_authority_total_eur != _UNCHANGED:
        sets.append("sales_price_authority_total_eur=?")
        args.append(new_sales_price_authority_total_eur)
    if new_sales_price_imported_at != _UNCHANGED:
        sets.append("sales_price_imported_at=?")
        args.append(new_sales_price_imported_at)
    if new_sales_price_invoice_ref != _UNCHANGED:
        sets.append("sales_price_invoice_ref=?")
        args.append(new_sales_price_invoice_ref)

    args.append(int(draft_id))
    with _connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        _ensure_drafts_table(conn)
        cur = conn.execute(
            f"UPDATE proforma_drafts SET {', '.join(sets)} WHERE id=?",
            tuple(args),
        )
        if cur.rowcount == 0:
            raise DraftNotFound(f"draft id={draft_id} not found")
        conn.commit()
        row = conn.execute(
            "SELECT * FROM proforma_drafts WHERE id=? LIMIT 1",
            (int(draft_id),),
        ).fetchone()
    if row is None:
        raise DraftNotFound(f"draft id={draft_id} disappeared after update")
    return _row_to_draft(row)


def _load_for_edit(
    db_path:             Path,
    draft_id:            int,
    expected_updated_at: str,
) -> ProformaDraft:
    """Common preamble for every edit helper: fetch, check editable,
    check optimistic lock. Raises DraftNotFound / DraftNotEditable /
    DraftConflict — never None."""
    d = get_draft_by_id(db_path, draft_id)
    if d is None:
        raise DraftNotFound(f"draft id={draft_id} not found")
    _check_editable(d)
    _check_lock(d, expected_updated_at)
    return d


def update_draft_fields(
    db_path:              Path,
    draft_id:             int,
    patch:                Dict[str, Any],
    operator:             str,
    expected_updated_at:  str,
) -> ProformaDraft:
    """PATCH the editable top-level fields of a draft.

    Accepted keys (all optional): remarks, buyer_override,
    ship_to_override, payment_terms, currency, exchange_rate,
    incoterm, insurance_eur.

    Any key outside :data:`EDITABLE_DRAFT_FIELDS` raises ValueError.
    Returns the refreshed draft.
    """
    if not (operator or "").strip():
        raise ValueError("operator is required")
    if not isinstance(patch, dict):
        raise ValueError("patch must be a JSON object")

    # Validate keys.
    unknown = [k for k in patch.keys() if k not in EDITABLE_DRAFT_FIELDS]
    if unknown:
        raise ValueError(
            f"unknown patch field(s): {unknown}; "
            f"allowed: {EDITABLE_DRAFT_FIELDS}"
        )

    d = _load_for_edit(db_path, draft_id, expected_updated_at)

    # Validate per-field shape.
    new_remarks         = None
    new_currency        = None
    new_exchange_rate   = "__unchanged__"
    new_buyer_override  = None
    new_ship_to         = None
    new_payment         = None
    new_incoterm        = "__unchanged__"
    new_insurance_eur   = "__unchanged__"
    if "remarks" in patch:
        new_remarks = str(patch["remarks"] or "")
    if "currency" in patch:
        new_currency = _validate_currency(str(patch["currency"]))
    if "exchange_rate" in patch:
        v = patch["exchange_rate"]
        if v is None:
            new_exchange_rate = None
        else:
            try:
                new_exchange_rate = float(v)
            except (TypeError, ValueError):
                raise ValueError(f"exchange_rate must be numeric, got {v!r}")
            if new_exchange_rate < 0:
                raise ValueError("exchange_rate must be >= 0")
    if "buyer_override" in patch:
        if not isinstance(patch["buyer_override"], dict):
            raise ValueError("buyer_override must be a JSON object")
        new_buyer_override = patch["buyer_override"]
    if "ship_to_override" in patch:
        if not isinstance(patch["ship_to_override"], dict):
            raise ValueError("ship_to_override must be a JSON object")
        new_ship_to = patch["ship_to_override"]
    if "payment_terms" in patch:
        if not isinstance(patch["payment_terms"], dict):
            raise ValueError("payment_terms must be a JSON object")
        new_payment = patch["payment_terms"]
    if "incoterm" in patch:
        v = patch["incoterm"]
        new_incoterm = str(v).strip().upper() if v is not None else None
    if "insurance_eur" in patch:
        v = patch["insurance_eur"]
        if v is None:
            new_insurance_eur = None
        else:
            try:
                new_insurance_eur = float(v)
            except (TypeError, ValueError):
                raise ValueError(f"insurance_eur must be numeric, got {v!r}")
            if new_insurance_eur < 0:
                raise ValueError("insurance_eur must be >= 0")

    # Derive fx_rate_date when exchange_rate is being set for the first time
    # (or updated). Only set if fx_rate_date is not already on the draft.
    new_fx_rate_date = "__unchanged__"
    if new_exchange_rate != "__unchanged__" and new_exchange_rate is not None:
        if not d.fx_rate_date:
            new_fx_rate_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # PR-4 — manual exchange-rate override. A hand-typed rate is authored by the
    # operator, not fetched from NBP: mark the source 'manual' and CLEAR the stale
    # NBP table metadata (a table number captured for a previous fetched rate no
    # longer describes this manual value). The before/after is audited below.
    new_fx_rate_source  = "__unchanged__"
    new_fx_table_number = "__unchanged__"
    _fx_before = None
    if "exchange_rate" in patch and new_exchange_rate != "__unchanged__":
        _fx_before = {
            "exchange_rate":  d.exchange_rate,
            "fx_rate_source": d.fx_rate_source,
            "fx_table_number": getattr(d, "fx_table_number", None),
        }
        new_fx_rate_source  = "manual"
        new_fx_table_number = None

    # Currency change must not contradict service-charge currencies that
    # were locked in earlier.
    if new_currency is not None:
        try:
            charges = json.loads(d.service_charges_json or "[]")
        except Exception:
            charges = []
        bad = [c for c in charges
                if (c.get("currency") or "").upper() != new_currency
                and c.get("currency")]
        if bad:
            raise ValueError(
                f"cannot change draft currency to {new_currency} — "
                f"existing service charges in {bad[0].get('currency')!r} "
                "must be removed first"
            )

    refreshed = _commit_draft_update(
        db_path, d.id,
        new_state            = _next_state_after_edit(d.draft_state),
        new_remarks          = new_remarks,
        new_currency         = new_currency,
        new_exchange_rate    = new_exchange_rate,
        new_buyer_override   = new_buyer_override,
        new_ship_to_override = new_ship_to,
        new_payment_terms    = new_payment,
        new_incoterm         = new_incoterm,
        new_insurance_eur    = new_insurance_eur,
        new_fx_rate_date     = new_fx_rate_date,
        new_fx_rate_source   = new_fx_rate_source,
        new_fx_table_number  = new_fx_table_number,
    )
    _fx_after = None
    if _fx_before is not None:
        _fx_after = {
            "exchange_rate":   refreshed.exchange_rate,
            "fx_rate_source":  refreshed.fx_rate_source,
            "fx_table_number": getattr(refreshed, "fx_table_number", None),
        }
    _record_draft_event(
        db_path, draft_id=d.id, event="draft_edited",
        detail_json=json.dumps({
            "fields_changed": sorted(list(patch.keys())),
            "from_state":     d.draft_state,
            "to_state":       refreshed.draft_state,
            **({"fx_before": _fx_before, "fx_after": _fx_after}
               if _fx_before is not None else {}),
        }, ensure_ascii=False, sort_keys=True),
        operator=operator,
    )
    return refreshed


def set_draft_nbp_rate(
    db_path:              Path,
    draft_id:            int,
    *,
    exchange_rate:       float,
    accounting_date:     str,
    table_date:          Optional[str],
    table_number:        Optional[str],
    source:              str,
    operator:            str,
    expected_updated_at: str,
) -> ProformaDraft:
    """Persist a fetched NBP (or PLN identity) rate atomically on the draft.

    Written through the shared optimistic-lock + draft-edit path
    (``_load_for_edit`` → ``_commit_draft_update``), so a stale
    ``expected_updated_at`` raises :class:`DraftConflict` and a non-editable draft
    raises :class:`DraftNotEditable`. The rate VALUE comes from the sole PZ NBP
    authority via ``nbp_rate_service`` — this writer never computes a rate.

    Persists: exchange_rate, fx_accounting_date (the requested date), fx_rate_date
    (the returned NBP table date — may differ), fx_table_number, fx_rate_source
    ('NBP' | 'identity'), updated_at. Records a ``nbp_rate_fetched`` audit event
    with before/after.
    """
    if not (operator or "").strip():
        raise ValueError("operator is required")
    try:
        rate = float(exchange_rate)
    except (TypeError, ValueError):
        raise ValueError(f"exchange_rate must be numeric, got {exchange_rate!r}")
    if rate <= 0:
        raise ValueError("exchange_rate must be > 0")

    d = _load_for_edit(db_path, draft_id, expected_updated_at)
    before = {
        "exchange_rate":    d.exchange_rate,
        "fx_rate_source":   d.fx_rate_source,
        "fx_rate_date":     d.fx_rate_date,
        "fx_accounting_date": getattr(d, "fx_accounting_date", None),
        "fx_table_number":  getattr(d, "fx_table_number", None),
    }
    refreshed = _commit_draft_update(
        db_path, d.id,
        new_state           = _next_state_after_edit(d.draft_state),
        new_exchange_rate   = rate,
        new_fx_rate_date    = (table_date or None),
        new_fx_rate_source  = source,
        new_fx_accounting_date = accounting_date,
        new_fx_table_number = (table_number or None),
    )
    _record_draft_event(
        db_path, draft_id=d.id, event="nbp_rate_fetched",
        detail_json=json.dumps({
            "before":          before,
            "after": {
                "exchange_rate":    refreshed.exchange_rate,
                "fx_rate_source":   refreshed.fx_rate_source,
                "fx_rate_date":     refreshed.fx_rate_date,
                "fx_accounting_date": getattr(refreshed, "fx_accounting_date", None),
                "fx_table_number":  getattr(refreshed, "fx_table_number", None),
            },
            "from_state":      d.draft_state,
            "to_state":        refreshed.draft_state,
        }, ensure_ascii=False, sort_keys=True, default=str),
        operator=operator,
    )
    return refreshed


def set_draft_weight_override(
    db_path:              Path,
    draft_id:            int,
    *,
    manual_net_weight:   Optional[float],
    manual_gross_weight: Optional[float],
    reason:              str,
    source_revision:     Optional[str],
    operator:            str,
    expected_updated_at: str,
) -> ProformaDraft:
    """Persist an operator manual net/gross weight override on the draft (KG).

    This is the sole transport-document weight-override writer. The EXTRACTED
    packing weight (packing_lines, grams) remains the historical authority and is
    NOT touched here — the override becomes the EFFECTIVE value only through this
    explicit operator action. At least one of net/gross must be provided; each,
    when provided, must be a non-negative number. ``source_revision`` snapshots
    the extracted-weight fingerprint at confirm time so a later re-import can flag
    drift without silently overwriting the override.

    Written through the shared OCC + draft-edit path (``_load_for_edit`` →
    ``_commit_draft_update``): a stale ``expected_updated_at`` raises
    ``DraftConflict``; a non-editable draft raises ``DraftNotEditable``. Records a
    ``weight_override_set`` audit event with before/after.
    """
    if not (operator or "").strip():
        raise ValueError("operator is required")

    def _num(v: Any, name: str) -> Optional[float]:
        if v is None or (isinstance(v, str) and v.strip() == ""):
            return None
        try:
            f = float(v)
        except (TypeError, ValueError):
            raise ValueError(f"{name} must be numeric, got {v!r}")
        if f < 0:
            raise ValueError(f"{name} must be >= 0")
        return f

    net = _num(manual_net_weight, "manual_net_weight")
    gross = _num(manual_gross_weight, "manual_gross_weight")
    if net is None and gross is None:
        raise ValueError("at least one of manual_net_weight / manual_gross_weight is required")

    d = _load_for_edit(db_path, draft_id, expected_updated_at)
    before = {
        "manual_net_weight":   d.manual_net_weight,
        "manual_gross_weight": d.manual_gross_weight,
        "weight_override_reason": d.weight_override_reason,
        "weight_source_revision": d.weight_source_revision,
    }
    now = _now_utc_iso()
    refreshed = _commit_draft_update(
        db_path, d.id,
        new_state              = _next_state_after_edit(d.draft_state),
        new_manual_net_weight  = net,
        new_manual_gross_weight = gross,
        new_weight_override_reason = (str(reason or "").strip() or None),
        new_weight_confirmed_at    = now,
        new_weight_confirmed_by    = operator,
        new_weight_source_revision = (source_revision or None),
        new_weight_override_source = "manual",
    )
    _record_draft_event(
        db_path, draft_id=d.id, event="weight_override_set",
        detail_json=json.dumps({
            "before": before,
            "after": {
                "manual_net_weight":   refreshed.manual_net_weight,
                "manual_gross_weight": refreshed.manual_gross_weight,
                "weight_override_reason": refreshed.weight_override_reason,
                "weight_source_revision": refreshed.weight_source_revision,
                "weight_confirmed_by":    refreshed.weight_confirmed_by,
            },
            "from_state": d.draft_state,
            "to_state":   refreshed.draft_state,
        }, ensure_ascii=False, sort_keys=True, default=str),
        operator=operator,
    )
    return refreshed


def clear_draft_weight_override(
    db_path:              Path,
    draft_id:            int,
    *,
    operator:            str,
    expected_updated_at: str,
) -> ProformaDraft:
    """Clear the manual weight override, restoring the EXTRACTED packing weight as
    the effective value (it was never overwritten — the override simply took
    precedence while present). Same OCC + audit path as the setter; records a
    ``weight_override_cleared`` audit event.
    """
    if not (operator or "").strip():
        raise ValueError("operator is required")
    d = _load_for_edit(db_path, draft_id, expected_updated_at)
    before = {
        "manual_net_weight":   d.manual_net_weight,
        "manual_gross_weight": d.manual_gross_weight,
        "weight_override_reason": d.weight_override_reason,
    }
    refreshed = _commit_draft_update(
        db_path, d.id,
        new_state              = _next_state_after_edit(d.draft_state),
        new_manual_net_weight  = None,
        new_manual_gross_weight = None,
        new_weight_override_reason = None,
        new_weight_confirmed_at    = None,
        new_weight_confirmed_by    = None,
        new_weight_source_revision = None,
        new_weight_override_source = "cleared",
    )
    _record_draft_event(
        db_path, draft_id=d.id, event="weight_override_cleared",
        detail_json=json.dumps({
            "before": before,
            "from_state": d.draft_state,
            "to_state":   refreshed.draft_state,
        }, ensure_ascii=False, sort_keys=True, default=str),
        operator=operator,
    )
    return refreshed


def update_draft_line(
    db_path:              Path,
    draft_id:             int,
    line_id:              int,
    patch:                Dict[str, Any],
    operator:             str,
    expected_updated_at:  str,
) -> ProformaDraft:
    """PATCH a single editable line by ``line_id``.

    Accepted keys (all optional): qty, unit_price, currency,
    product_code, design_no, client_ref, price_source, remarks.

    Validation:
      - ``qty`` must be > 0 if present
      - ``unit_price`` must be >= 0 if present
      - ``currency`` must be in :data:`ALLOWED_CURRENCIES` if present
      - ``product_code`` must be non-blank if present
    """
    if not (operator or "").strip():
        raise ValueError("operator is required")
    if not isinstance(patch, dict):
        raise ValueError("patch must be a JSON object")
    unknown = [k for k in patch.keys() if k not in EDITABLE_LINE_FIELDS]
    if unknown:
        raise ValueError(
            f"unknown line patch field(s): {unknown}; "
            f"allowed: {EDITABLE_LINE_FIELDS}"
        )

    d = _load_for_edit(db_path, draft_id, expected_updated_at)

    try:
        lines_raw = json.loads(d.editable_lines_json or "[]")
    except Exception:
        lines_raw = []
    if not isinstance(lines_raw, list):
        lines_raw = []
    lines = _ensure_line_ids(lines_raw)

    target_idx = next(
        (i for i, ln in enumerate(lines)
         if int(ln.get("line_id") or 0) == int(line_id)),
        None,
    )
    if target_idx is None:
        raise ValueError(f"line_id={line_id} not found on draft id={draft_id}")

    # Validate patch.
    if "qty" in patch:
        try:
            q = float(patch["qty"])
        except (TypeError, ValueError):
            raise ValueError(f"qty must be numeric, got {patch['qty']!r}")
        if q <= 0:
            raise ValueError("qty must be > 0")
    if "unit_price" in patch:
        try:
            up = float(patch["unit_price"])
        except (TypeError, ValueError):
            raise ValueError(
                f"unit_price must be numeric, got {patch['unit_price']!r}")
        if up < 0:
            raise ValueError("unit_price must be >= 0")
    if "currency" in patch:
        _validate_currency(str(patch["currency"]))
    if "product_code" in patch:
        if not str(patch["product_code"] or "").strip():
            raise ValueError("product_code cannot be blank")

    # Apply patch in-place to preserve sales-packing source fields not
    # mentioned in the patch.
    target = dict(lines[target_idx])
    before = {k: target.get(k) for k in EDITABLE_LINE_FIELDS}
    for k, v in patch.items():
        if k == "currency":
            target[k] = _validate_currency(str(v))
        elif k in ("qty", "unit_price"):
            target[k] = float(v)
        else:
            target[k] = v if v is not None else ""
    lines[target_idx] = target

    refreshed = _commit_draft_update(
        db_path, d.id,
        new_state          = _next_state_after_edit(d.draft_state),
        new_editable_lines = lines,
    )
    _record_draft_event(
        db_path, draft_id=d.id, event="draft_line_edited",
        detail_json=json.dumps({
            "line_id":   int(line_id),
            "before":    before,
            "patch":     patch,
            "from_state": d.draft_state,
            "to_state":   refreshed.draft_state,
        }, ensure_ascii=False, sort_keys=True),
        operator=operator,
    )
    return refreshed


def bulk_price_recovery(
    db_path:             Path,
    draft_id:            int,
    prices:              List[Dict[str, Any]],
    operator:            str,
    expected_updated_at: str,
    *,
    confirm_overwrite:   bool = False,
) -> ProformaDraft:
    """Apply a bulk unit-price update to editable lines, matched by ``product_code``.

    ``prices`` is a list of ``{"product_code": str, "unit_price": float}``
    dicts.  Only ``unit_price`` and ``price_source`` are written on matched
    lines; all other fields (qty, currency, design_no, client_ref, item_type,
    name_pl, description_*) are preserved exactly.  ``source_lines_json`` is
    **never** read or written.

    Parameters
    ----------
    prices:
        Each entry must have a non-blank ``product_code`` and a numeric
        ``unit_price > 0``.  Duplicate product codes in the list are rejected.
    confirm_overwrite:
        Set to ``True`` to allow overwriting lines that already have a
        positive ``unit_price``.  If any such lines exist and this flag is
        ``False``, raises :class:`OverwriteRequired`.

    Returns
    -------
    The refreshed :class:`ProformaDraft` after the atomic write.

    Raises
    ------
    ValueError           — invalid input (bad prices, duplicates, empty list)
    OverwriteRequired    — non-zero prices would be overwritten without consent
    DraftNotFound        — draft_id unknown
    DraftNotEditable     — draft is not in an editable state
    DraftConflict        — stale expected_updated_at
    """
    # ── 1. Input validation (all before any DB access) ───────────────────────
    if not (operator or "").strip():
        raise ValueError("operator is required")
    if not isinstance(prices, list) or len(prices) == 0:
        raise ValueError("prices must be a non-empty list")

    price_map: Dict[str, float] = {}
    for entry in prices:
        code = str(entry.get("product_code") or "").strip()
        if not code:
            raise ValueError("each price entry must have a non-blank product_code")
        try:
            up = float(entry["unit_price"])
        except (TypeError, ValueError, KeyError):
            raise ValueError(
                f"unit_price for {code!r} must be numeric, "
                f"got {entry.get('unit_price')!r}"
            )
        if up <= 0:
            raise ValueError(
                f"unit_price for {code!r} must be > 0, got {up!r}"
            )
        if code in price_map:
            raise ValueError(f"duplicate product_code in prices list: {code!r}")
        price_map[code] = up

    # ── 2. Load draft + OCC + editable check ─────────────────────────────────
    d = _load_for_edit(db_path, draft_id, expected_updated_at)

    # ── 3. Parse current editable lines ──────────────────────────────────────
    try:
        lines_raw = json.loads(d.editable_lines_json or "[]")
    except Exception:
        lines_raw = []
    if not isinstance(lines_raw, list):
        lines_raw = []
    lines = _ensure_line_ids(lines_raw)

    # ── 4. Overwrite detection ────────────────────────────────────────────────
    would_overwrite = [
        str(ln.get("product_code") or "")
        for ln in lines
        if str(ln.get("product_code") or "") in price_map
        and float(ln.get("unit_price", 0) or 0) > 0
    ]
    if would_overwrite and not confirm_overwrite:
        raise OverwriteRequired(would_overwrite)

    # ── 5. Apply updates ──────────────────────────────────────────────────────
    known_codes = {str(ln.get("product_code") or "") for ln in lines}
    updated_count    = 0
    overwritten_count = 0
    for i, ln in enumerate(lines):
        code = str(ln.get("product_code") or "")
        if code in price_map:
            was_nonzero = float(ln.get("unit_price", 0) or 0) > 0
            lines[i] = {**ln, "unit_price": price_map[code], "price_source": "bulk_recovery"}
            updated_count += 1
            if was_nonzero:
                overwritten_count += 1

    unmatched_codes = [c for c in price_map if c not in known_codes]
    still_zero_count = sum(
        1 for ln in lines if float(ln.get("unit_price", 0) or 0) <= 0
    )

    # ── 6. Atomic commit ──────────────────────────────────────────────────────
    refreshed = _commit_draft_update(
        db_path, d.id,
        new_state          = _next_state_after_edit(d.draft_state),
        new_editable_lines = lines,
    )

    # ── 7. Event record ───────────────────────────────────────────────────────
    _record_draft_event(
        db_path, draft_id=d.id, event="draft_bulk_price_recovery",
        detail_json=json.dumps({
            "updated_count":     updated_count,
            "unmatched_codes":   unmatched_codes,
            "still_zero_count":  still_zero_count,
            "overwritten_count": overwritten_count,
            "from_state":        d.draft_state,
            "to_state":          refreshed.draft_state,
        }, ensure_ascii=False, sort_keys=True),
        operator=operator,
    )
    return refreshed


def add_draft_service_charge(
    db_path:              Path,
    draft_id:             int,
    charge:               Dict[str, Any],
    operator:             str,
    expected_updated_at:  str,
) -> ProformaDraft:
    """Append a service charge.

    Required keys: charge_type, amount, currency.
    Optional: label.

    Currency must match every editable line's currency unless the draft
    has zero product lines. ``charge_id`` is server-assigned (1-based,
    monotonically increasing per draft).
    """
    if not (operator or "").strip():
        raise ValueError("operator is required")
    if not isinstance(charge, dict):
        raise ValueError("charge must be a JSON object")

    ctype = (charge.get("charge_type") or "").strip().lower()
    if ctype not in ALLOWED_SERVICE_CHARGE_TYPES:
        raise ValueError(
            f"charge_type {charge.get('charge_type')!r} not allowed; "
            f"expected one of {ALLOWED_SERVICE_CHARGE_TYPES}"
        )
    try:
        amount = float(charge.get("amount", 0) or 0)
    except (TypeError, ValueError):
        raise ValueError(f"amount must be numeric, got {charge.get('amount')!r}")
    if amount < 0:
        raise ValueError("amount must be >= 0")
    ccy = _validate_currency(str(charge.get("currency") or ""))

    # Validate wfirma_service_id if present
    wsid = charge.get("wfirma_service_id")
    if wsid is not None and not str(wsid).strip():
        raise ValueError("wfirma_service_id must be a non-empty string if provided")

    # PR-6 — explicit charge resolution (never inferred from amount). A zero
    # amount is valid when paired with customer_courier / waived / not_applicable
    # / manual_amount. Absent → stored as None (the reader treats an ambiguous
    # legacy zero as 'unresolved').
    resolution = charge.get("resolution")
    if resolution is not None:
        resolution = str(resolution).strip().lower()
        if resolution not in RESOLUTION_STATES:
            raise ValueError(
                f"resolution {charge.get('resolution')!r} not allowed; "
                f"expected one of {sorted(RESOLUTION_STATES)}"
            )

    # Validate formula_basis if present
    formula_basis = charge.get("formula_basis")
    if formula_basis is not None:
        if not isinstance(formula_basis, dict):
            raise ValueError("formula_basis must be a JSON object")
        for k in formula_basis:
            if any(
                str(k).startswith(pfx) or str(k) == pfx
                for pfx in _FORBIDDEN_FORMULA_BASIS_PREFIXES
            ):
                raise ValueError(
                    f"formula_basis key {k!r} is not allowed; "
                    "only sales_total, rate_pct, minimum_eur, minimum_usd are permitted"
                )

    d = _load_for_edit(db_path, draft_id, expected_updated_at)

    # Currency-match check vs existing lines.
    try:
        lines = _ensure_line_ids(json.loads(d.editable_lines_json or "[]") or [])
    except Exception:
        lines = []
    line_ccys = {(ln.get("currency") or "").upper() for ln in lines if ln.get("currency")}
    if line_ccys and ccy not in line_ccys:
        raise ValueError(
            f"service charge currency {ccy} does not match draft line "
            f"currencies {sorted(line_ccys)}"
        )

    try:
        charges = json.loads(d.service_charges_json or "[]") or []
    except Exception:
        charges = []

    # One-per-type constraint: block a duplicate charge_type
    existing_types = {c.get("charge_type") for c in charges}
    if ctype in existing_types:
        raise ValueError(
            f"A service charge of type {ctype!r} already exists on this draft. "
            "Remove it first before adding another."
        )

    used_ids = {int(c.get("charge_id") or 0) for c in charges
                if isinstance(c.get("charge_id"), int)}
    new_id = (max(used_ids) if used_ids else 0) + 1
    new_charge: Dict[str, Any] = {
        "charge_id":         new_id,
        "charge_type":       ctype,
        "amount":            amount,
        "currency":          ccy,
        "label":             str(charge.get("label") or "").strip(),
        "wfirma_service_id": str(wsid).strip() if wsid is not None else None,
        "formula_basis":     formula_basis,
        "resolution":        resolution,
    }
    charges.append(new_charge)

    refreshed = _commit_draft_update(
        db_path, d.id,
        new_state           = _next_state_after_edit(d.draft_state),
        new_service_charges = charges,
    )
    _record_draft_event(
        db_path, draft_id=d.id, event="draft_service_charge_added",
        detail_json=json.dumps({
            "charge":     new_charge,
            "from_state": d.draft_state,
            "to_state":   refreshed.draft_state,
        }, ensure_ascii=False, sort_keys=True),
        operator=operator,
    )
    return refreshed


def remove_draft_service_charge(
    db_path:              Path,
    draft_id:             int,
    charge_id:            int,
    operator:             str,
    expected_updated_at:  str,
) -> ProformaDraft:
    """Remove a service charge by ``charge_id``."""
    if not (operator or "").strip():
        raise ValueError("operator is required")

    d = _load_for_edit(db_path, draft_id, expected_updated_at)
    try:
        charges = json.loads(d.service_charges_json or "[]") or []
    except Exception:
        charges = []
    target = next(
        (c for c in charges if int(c.get("charge_id") or 0) == int(charge_id)),
        None,
    )
    if target is None:
        raise ValueError(
            f"charge_id={charge_id} not found on draft id={draft_id}")
    remaining = [c for c in charges
                  if int(c.get("charge_id") or 0) != int(charge_id)]

    refreshed = _commit_draft_update(
        db_path, d.id,
        new_state           = _next_state_after_edit(d.draft_state),
        new_service_charges = remaining,
    )
    _record_draft_event(
        db_path, draft_id=d.id, event="draft_service_charge_removed",
        detail_json=json.dumps({
            "removed":    target,
            "from_state": d.draft_state,
            "to_state":   refreshed.draft_state,
        }, ensure_ascii=False, sort_keys=True),
        operator=operator,
    )
    return refreshed


def update_draft_service_charge(
    db_path:              Path,
    draft_id:             int,
    charge_id:            int,
    updates:              Dict[str, Any],
    operator:             str,
    expected_updated_at:  str,
) -> ProformaDraft:
    """Edit an existing service charge in place by ``charge_id``.

    Completes CRUD on the canonical service-charge writer (add / update /
    remove) so the operator can correct a freight/insurance amount, service
    product mapping, label, or insurance rate WITHOUT a destructive
    delete-then-re-add. ``charge_type`` is immutable (remove + add to change a
    type). Only the keys present in ``updates`` are changed.

    Editable keys: ``amount`` (>= 0), ``currency`` (must match draft lines),
    ``label``, ``wfirma_service_id`` (non-empty when set, or null to clear),
    ``rate_pct`` (insurance formula_basis.rate_pct; None/'' clears it).

    Reuses the same validation, one-per-type invariant (untouched), currency
    guard, and audit path as :func:`add_draft_service_charge`.
    """
    if not (operator or "").strip():
        raise ValueError("operator is required")
    if not isinstance(updates, dict):
        raise ValueError("updates must be a JSON object")

    d = _load_for_edit(db_path, draft_id, expected_updated_at)
    try:
        charges = json.loads(d.service_charges_json or "[]") or []
    except Exception:
        charges = []
    idx = next(
        (i for i, c in enumerate(charges)
         if int(c.get("charge_id") or 0) == int(charge_id)),
        None,
    )
    if idx is None:
        raise ValueError(
            f"charge_id={charge_id} not found on draft id={draft_id}")

    before = dict(charges[idx])
    charge = dict(charges[idx])

    if "amount" in updates:
        try:
            amount = float(updates.get("amount") or 0)
        except (TypeError, ValueError):
            raise ValueError(f"amount must be numeric, got {updates.get('amount')!r}")
        if amount < 0:
            raise ValueError("amount must be >= 0")
        charge["amount"] = amount

    if "currency" in updates:
        ccy = _validate_currency(str(updates.get("currency") or ""))
        try:
            lines = _ensure_line_ids(json.loads(d.editable_lines_json or "[]") or [])
        except Exception:
            lines = []
        line_ccys = {(ln.get("currency") or "").upper()
                     for ln in lines if ln.get("currency")}
        if line_ccys and ccy not in line_ccys:
            raise ValueError(
                f"service charge currency {ccy} does not match draft line "
                f"currencies {sorted(line_ccys)}"
            )
        charge["currency"] = ccy

    if "label" in updates:
        charge["label"] = str(updates.get("label") or "").strip()

    if "wfirma_service_id" in updates:
        wsid = updates.get("wfirma_service_id")
        if wsid is None or str(wsid).strip() == "":
            charge["wfirma_service_id"] = None
        else:
            charge["wfirma_service_id"] = str(wsid).strip()

    if "rate_pct" in updates:
        rate = updates.get("rate_pct")
        fb = dict(charge.get("formula_basis") or {})
        if rate is None or str(rate).strip() == "":
            fb.pop("rate_pct", None)
        else:
            try:
                fb["rate_pct"] = float(rate)
            except (TypeError, ValueError):
                raise ValueError(f"rate_pct must be numeric, got {rate!r}")
        charge["formula_basis"] = fb or None

    if "resolution" in updates:
        # PR-6 — persist the operator's explicit resolution decision. Setting a
        # zero-state (customer_courier / waived / not_applicable) alongside
        # amount=0 is a valid commercial decision, not an error.
        res = updates.get("resolution")
        if res is None or str(res).strip() == "":
            charge["resolution"] = None
        else:
            res = str(res).strip().lower()
            if res not in RESOLUTION_STATES:
                raise ValueError(
                    f"resolution {updates.get('resolution')!r} not allowed; "
                    f"expected one of {sorted(RESOLUTION_STATES)}"
                )
            charge["resolution"] = res

    charges[idx] = charge

    refreshed = _commit_draft_update(
        db_path, d.id,
        new_state           = _next_state_after_edit(d.draft_state),
        new_service_charges = charges,
    )
    _record_draft_event(
        db_path, draft_id=d.id, event="draft_service_charge_updated",
        detail_json=json.dumps({
            "charge_id":  int(charge_id),
            "before":     before,
            "after":      charge,
            "from_state": d.draft_state,
            "to_state":   refreshed.draft_state,
        }, ensure_ascii=False, sort_keys=True),
        operator=operator,
    )
    return refreshed


def apply_customer_address_to_draft(
    db_path:              Path,
    draft_id:             int,
    cm_name:              str,
    cm_contractor_id:     str,
    buyer_override:       Dict[str, Any],
    ship_to_override:     Optional[Dict[str, Any]],
    operator:             str,
    expected_updated_at:  str,
) -> ProformaDraft:
    """Apply a Customer Master address projection as buyer_override + ship_to_override.

    Records a specific ``buyer_override_from_customer_master`` audit event
    (not the generic ``draft_edited``) so the trace is unambiguous.

    ``ship_to_override`` is None when the Customer Master has no alternate
    ship-to address (ship_to_use_alternate=False) — in that case only
    buyer_override is written, and any existing ship_to_override is left
    untouched (caller clears it explicitly if wanted).
    """
    if not (operator or "").strip():
        raise ValueError("operator is required")
    if not isinstance(buyer_override, dict):
        raise ValueError("buyer_override must be a dict")

    d = _load_for_edit(db_path, draft_id, expected_updated_at)

    # Capture previous overrides for audit trail
    try:
        prev_buyer = json.loads(d.buyer_override_json or "{}") or {}
    except Exception:
        prev_buyer = {}
    try:
        prev_ship = json.loads(d.ship_to_override_json or "{}") or {}
    except Exception:
        prev_ship = {}

    refreshed = _commit_draft_update(
        db_path, d.id,
        new_state            = _next_state_after_edit(d.draft_state),
        new_buyer_override   = buyer_override,
        new_ship_to_override = ship_to_override,   # None = leave existing ship_to unchanged
    )
    _record_draft_event(
        db_path, draft_id=d.id,
        event="buyer_override_from_customer_master",
        detail_json=json.dumps({
            "source_contractor_id": cm_contractor_id,
            "source_name":          cm_name,
            "prev_buyer_override":  prev_buyer,
            "new_buyer_override":   buyer_override,
            "ship_to_applied":      ship_to_override is not None,
            "prev_ship_to":         prev_ship if ship_to_override is not None else None,
            "new_ship_to":          ship_to_override,
            "from_state":           d.draft_state,
            "to_state":             refreshed.draft_state,
        }, ensure_ascii=False, sort_keys=True),
        operator=operator,
    )
    return refreshed


# ── Customer Master commercial-defaults apply (Slice 1) ────────────────────────

#: Field keys accepted by :func:`apply_customer_commercial_to_draft`.
#: Exposed so the route layer can validate incoming ``fields`` lists
#: without importing internal implementation details.
_CM_COMMERCIAL_FIELDS: frozenset = frozenset([
    "payment_method",
    "payment_terms_days",
    "invoice_language_id",
    "vat_mode",
    "freight_amount",
    "freight_service_id",
    "insurance_rate",
    "insurance_service_id",
    # PR-6: freeze the computed insurance premium at write time. The route
    # computes it via the ONE shared premium helper and passes the frozen amount
    # + full formula_basis (sales_total/rate_pct/minimum) so the read authority
    # never depends on live Customer Master data. insurance_rate stays supported
    # for back-compat but no longer leaves amount=0.
    "insurance_amount",
    "insurance_formula_basis",
])


def apply_customer_commercial_to_draft(
    db_path:              Path,
    draft_id:             int,
    cm_name:              str,
    cm_contractor_id:     str,
    updates:              Dict[str, Any],
    operator:             str,
    expected_updated_at:  str,
    audit_event:          str = "commercial_defaults_from_customer_master",
) -> "ProformaDraft":
    """Apply a subset of Customer Master commercial defaults to a draft.

    ``updates`` maps field key → resolved CM value.  Only keys present in
    ``updates`` (and in :data:`_CM_COMMERCIAL_FIELDS`) are written; any
    non-empty draft value is overwritten ONLY when its key appears in
    ``updates``.

    Field → storage mapping:

    * ``payment_method``    → ``payment_terms_json.method``
    * ``payment_terms_days``→ ``payment_terms_json.days``
    * ``invoice_language_id``→``payment_terms_json.invoice_language_id``
    * ``vat_mode``          → ``vat_code`` column +
                              ``decision_source = 'operator_vat_mode'``
    * ``freight_amount``    → service charge type "freight" ``.amount``
                              (upsert: update existing or create new)
    * ``freight_service_id``→ service charge type "freight"
                              ``.wfirma_service_id`` (upsert)
    * ``insurance_rate``    → service charge type "insurance"
                              ``.formula_basis.rate_pct`` (upsert).
                              **Amount is NOT computed here** — that belongs
                              to the service-charge slice.
    * ``insurance_service_id``→ service charge type "insurance"
                              ``.wfirma_service_id`` (upsert)

    Writes atomically in one SQL UPDATE. Records audit event
    ``commercial_defaults_from_customer_master``.

    Raises
    ------
    ValueError
        Bad arguments or unknown field key.
    DraftNotFound
        Draft not found.
    DraftNotEditable
        Draft is in a non-editable state.
    DraftConflict
        Optimistic-lock mismatch (expected_updated_at does not match).
    """
    if not (operator or "").strip():
        raise ValueError("operator is required")
    if not isinstance(updates, dict):
        raise ValueError("updates must be a dict")

    unknown = [k for k in updates if k not in _CM_COMMERCIAL_FIELDS]
    if unknown:
        raise ValueError(
            f"unknown commercial field(s): {unknown!r}; "
            f"allowed: {sorted(_CM_COMMERCIAL_FIELDS)}"
        )

    d = _load_for_edit(db_path, draft_id, expected_updated_at)

    # ── Parse existing JSON blobs ─────────────────────────────────────────
    try:
        existing_pt: Dict[str, Any] = json.loads(d.payment_terms_json or "{}") or {}
    except Exception:
        existing_pt = {}
    try:
        existing_charges: List[Dict[str, Any]] = (
            json.loads(d.service_charges_json or "[]") or []
        )
    except Exception:
        existing_charges = []
    if not isinstance(existing_charges, list):
        existing_charges = []

    # ── Before snapshot for audit ─────────────────────────────────────────
    before: Dict[str, Any] = {
        "payment_terms": {
            k: existing_pt.get(k)
            for k in ("method", "days", "invoice_language_id")
        },
        "vat_code": d.vat_code,
        "freight": next(
            (c for c in existing_charges if c.get("charge_type") == "freight"), None
        ),
        "insurance": next(
            (c for c in existing_charges if c.get("charge_type") == "insurance"), None
        ),
    }

    # ── Compute new payment_terms ─────────────────────────────────────────
    new_pt = dict(existing_pt)
    if "payment_method" in updates and updates["payment_method"] is not None:
        new_pt["method"] = str(updates["payment_method"])
    if "payment_terms_days" in updates and updates["payment_terms_days"] is not None:
        try:
            new_pt["days"] = int(updates["payment_terms_days"])
        except (TypeError, ValueError):
            new_pt["days"] = updates["payment_terms_days"]
    if "invoice_language_id" in updates and updates["invoice_language_id"] is not None:
        new_pt["invoice_language_id"] = str(updates["invoice_language_id"])

    # ── Compute new vat_code / decision_source ────────────────────────────
    new_vat_code = d.vat_code          # default: unchanged
    new_decision_source = d.decision_source
    if "vat_mode" in updates and updates["vat_mode"] is not None:
        new_vat_code = str(updates["vat_mode"])
        new_decision_source = "operator_vat_mode"

    # ── Compute new service_charges (upsert freight / insurance) ─────────
    fr_keys = frozenset(("freight_amount", "freight_service_id")) & updates.keys()
    ins_keys = frozenset((
        "insurance_rate", "insurance_service_id",
        "insurance_amount", "insurance_formula_basis",
    )) & updates.keys()

    def _apply_insurance_freeze(chg: Dict[str, Any]) -> None:
        """PR-6: freeze the premium from the ONE Calculate action. When the caller
        supplies a computed insurance_amount + insurance_formula_basis, store BOTH
        (the premium and its frozen evidence) and stamp resolution='calculated'
        (an explicit operator action, never inferred). Falls back to the legacy
        rate-only stamp otherwise."""
        _froze = False
        if "insurance_amount" in updates and updates["insurance_amount"] is not None:
            try:
                chg["amount"] = float(updates["insurance_amount"])
                _froze = True
            except (TypeError, ValueError):
                pass
        if "insurance_formula_basis" in updates and isinstance(updates["insurance_formula_basis"], dict):
            chg["formula_basis"] = dict(updates["insurance_formula_basis"])
            _froze = True
        elif "insurance_rate" in updates and updates["insurance_rate"] is not None:
            fb = dict(chg.get("formula_basis") or {})
            try:
                fb["rate_pct"] = float(updates["insurance_rate"])
            except (TypeError, ValueError):
                pass
            chg["formula_basis"] = fb or None
        if _froze:
            chg["resolution"] = RESOLUTION_CALCULATED

    new_charges: List[Dict[str, Any]] = [dict(c) for c in existing_charges]

    def _next_charge_id() -> int:
        used = {int(c.get("charge_id") or 0) for c in new_charges
                if isinstance(c.get("charge_id"), int)}
        return (max(used) if used else 0) + 1

    if fr_keys:
        fr_idx = next(
            (i for i, c in enumerate(new_charges)
             if isinstance(c, dict) and c.get("charge_type") == "freight"),
            None,
        )
        if fr_idx is not None:
            fr = dict(new_charges[fr_idx])
            if "freight_amount" in updates and updates["freight_amount"] is not None:
                try:
                    fr["amount"] = float(updates["freight_amount"])
                except (TypeError, ValueError):
                    pass
            if "freight_service_id" in updates and updates["freight_service_id"] is not None:
                fr["wfirma_service_id"] = str(updates["freight_service_id"])
            new_charges[fr_idx] = fr
        else:
            fr_new: Dict[str, Any] = {
                "charge_id":         _next_charge_id(),
                "charge_type":       "freight",
                "amount":            0.0,
                "currency":          (d.currency or "EUR").upper(),
                "label":             "",
                "wfirma_service_id": None,
                "formula_basis":     None,
            }
            if "freight_amount" in updates and updates["freight_amount"] is not None:
                try:
                    fr_new["amount"] = float(updates["freight_amount"])
                except (TypeError, ValueError):
                    pass
            if "freight_service_id" in updates and updates["freight_service_id"] is not None:
                fr_new["wfirma_service_id"] = str(updates["freight_service_id"])
            new_charges.append(fr_new)

    if ins_keys:
        ins_idx = next(
            (i for i, c in enumerate(new_charges)
             if isinstance(c, dict) and c.get("charge_type") == "insurance"),
            None,
        )
        if ins_idx is not None:
            ins = dict(new_charges[ins_idx])
            if "insurance_service_id" in updates and updates["insurance_service_id"] is not None:
                ins["wfirma_service_id"] = str(updates["insurance_service_id"])
            _apply_insurance_freeze(ins)
            new_charges[ins_idx] = ins
        else:
            ins_new: Dict[str, Any] = {
                "charge_id":         _next_charge_id(),
                "charge_type":       "insurance",
                "amount":            0.0,
                "currency":          (d.currency or "EUR").upper(),
                "label":             "",
                "wfirma_service_id": None,
                "formula_basis":     None,
            }
            if "insurance_service_id" in updates and updates["insurance_service_id"] is not None:
                ins_new["wfirma_service_id"] = str(updates["insurance_service_id"])
            _apply_insurance_freeze(ins_new)
            new_charges.append(ins_new)

    # ── After snapshot for audit ──────────────────────────────────────────
    after: Dict[str, Any] = {
        "payment_terms": {
            k: new_pt.get(k)
            for k in ("method", "days", "invoice_language_id")
        },
        "vat_code": new_vat_code,
        "freight": next(
            (c for c in new_charges if c.get("charge_type") == "freight"), None
        ),
        "insurance": next(
            (c for c in new_charges if c.get("charge_type") == "insurance"), None
        ),
    }

    # ── Atomic SQL write ─────────────────────────────────────────────────
    new_state = _next_state_after_edit(d.draft_state)
    now_ts = _now_utc_iso()

    sets: List[str] = [
        "draft_state=?", "updated_at=?",
        "payment_terms_json=?", "service_charges_json=?",
        "vat_code=?", "decision_source=?",
    ]
    args: List[Any] = [
        new_state, now_ts,
        json.dumps(new_pt, ensure_ascii=False, sort_keys=True),
        json.dumps(new_charges, ensure_ascii=False, sort_keys=True),
        new_vat_code,
        new_decision_source,
    ]
    args.append(int(draft_id))

    with _connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        _ensure_drafts_table(conn)
        cur = conn.execute(
            f"UPDATE proforma_drafts SET {', '.join(sets)} WHERE id=?",
            tuple(args),
        )
        if cur.rowcount == 0:
            raise DraftNotFound(f"draft id={draft_id} not found")
        conn.commit()
        row = conn.execute(
            "SELECT * FROM proforma_drafts WHERE id=? LIMIT 1",
            (int(draft_id),),
        ).fetchone()
    if row is None:
        raise DraftNotFound(f"draft id={draft_id} disappeared after update")
    refreshed = _row_to_draft(row)

    _record_draft_event(
        db_path, draft_id=d.id,
        event=audit_event,
        detail_json=json.dumps(
            {
                "source_contractor_id": cm_contractor_id,
                "source_name":          cm_name,
                "selected_fields":      sorted(updates.keys()),
                "before":               before,
                "after":                after,
                "from_state":           d.draft_state,
                "to_state":             refreshed.draft_state,
            },
            ensure_ascii=False,
            sort_keys=True,
            default=str,          # Decimal / datetime fallback
        ),
        operator=operator,
    )
    return refreshed


# ── Customer-replacement migration warnings — ONE safe, stable contract ────────
#
# When the post-identity charge / reservation migration fails (see
# change_draft_customer), the operator must be told — but the warning surfaced
# to the browser MUST NOT carry raw exception text. A raw ``str(exc)`` can leak
# internal filesystem paths, SQLite details, wFirma payloads or other
# operational information. So there is exactly ONE warning authority: a stable
# per-type contract, browser-safe by construction. Full exception detail stays
# in the server log (``log.warning(..., exc_info=True)``); the audit event and
# the HTTP response both carry only this shape.
#
# Shape (stable): {type, authority, severity, message, requires_operator_review}
_MIGRATION_WARNING_CONTRACT: Dict[str, Dict[str, Any]] = {
    "charge_move_failed": {
        "type":                     "charge_move_failed",
        "authority":                "PROFORMA",
        "severity":                 "warning",
        "message": (
            "Customer changed, but service charges could not be migrated. "
            "Review service charges for this draft."
        ),
        "requires_operator_review": True,
    },
    "reservation_migrate_failed": {
        "type":                     "reservation_migrate_failed",
        "authority":                "SALES",
        "severity":                 "warning",
        "message": (
            "Customer changed, but the wFirma reservation draft could not be "
            "renamed. Review the reservation for this draft."
        ),
        "requires_operator_review": True,
    },
}


def migration_warning(warning_type: str) -> Dict[str, Any]:
    """Return a fresh copy of the stable, browser-safe migration-warning contract
    for *warning_type* (``charge_move_failed`` | ``reservation_migrate_failed``).

    NEVER carries raw exception text — full exception detail is server-log-only.
    Raises KeyError for an unknown type (programmer error, not operator input)."""
    return dict(_MIGRATION_WARNING_CONTRACT[warning_type])


def change_draft_customer(
    db_path:              Path,
    draft_id:             int,
    *,
    new_contractor_id:    str,
    new_client_name:      str,
    buyer_override:       Dict[str, Any],
    operator:             str,
    expected_updated_at:  str,
    charge_move:          Optional[Callable[[str, str, str], List[Dict[str, Any]]]] = None,
    reservation_migrate:  Optional[Callable[[str, str, str], Dict[str, Any]]] = None,
    migration_warnings:   Optional[List[Dict[str, Any]]] = None,
) -> ProformaDraft:
    """PR 1a: replace the draft's CUSTOMER identity (client_name +
    client_contractor_id) with an operator-selected Customer Master contractor,
    and project the new bill-to address as buyer_override.

    Authority / safety rules:
      * EDITABLE drafts only (draft / editing / post_failed) — posted / approved /
        posting / cancelled / superseded identity is FROZEN. Enforced by
        ``_load_for_edit`` (raises DraftNotEditable → 409).
      * Optimistic-locked via ``expected_updated_at`` (DraftConflict → 409).
      * ID-FIRST: the caller supplies the explicit contractor id; this function
        NEVER resolves a customer by name.
      * NEVER touches editable_lines / source_lines / prices / qty / batch_id /
        packing linkage — only client_name, client_contractor_id, buyer_override.
      * Service charges (keyed by batch_id + client_name) travel with the draft
        via the injected ``charge_move`` callable (money-safe, disclosed); the
        wFirma reservation draft follows via ``reservation_migrate``.
      * Duplicate/target collision: if another draft in the batch already carries
        the new customer's name at the same clone_generation, raises DraftConflict
        (→ 409) — NEVER auto-merges; the operator must resolve.

    The charge / reservation migration runs OUTSIDE the identity transaction
    (best-effort, PR-3 money-safe pattern). If either step raises AFTER the
    identity UPDATE has committed, the identity change still stands and the
    failure is NOT silently swallowed: a STABLE, BROWSER-SAFE warning (see
    :func:`migration_warning` — ``{type, authority, severity, message,
    requires_operator_review}``) is appended to the optional
    ``migration_warnings`` sink (a caller-supplied list) so the route can
    surface the orphaned-charge / stray-reservation disclosure in its HTTP
    response — the operator sees it without reading the audit log. The same
    safe warnings are written into the ``draft_customer_changed`` audit event.
    The raw exception is logged server-side ONLY (``exc_info=True``); it is
    never placed in the warning, which would leak internal path / DB / wFirma
    payload detail to the browser.

    Idempotent no-op when the contractor id + name already match the draft.
    """
    if not (operator or "").strip():
        raise ValueError("operator is required")
    new_cid  = str(new_contractor_id or "").strip()
    new_name = (new_client_name or "").strip()
    if not new_cid:
        raise ValueError("new_contractor_id is required (ID-first; never resolved by name)")
    if not new_name:
        raise ValueError("new_client_name is required")
    if not isinstance(buyer_override, dict):
        raise ValueError("buyer_override must be a dict")

    d = _load_for_edit(db_path, draft_id, expected_updated_at)
    old_name = d.client_name or ""
    old_cid  = d.client_contractor_id or ""

    # Idempotent no-op — same contractor identity already on the draft.
    if str(old_cid) == new_cid and old_name == new_name:
        return d

    gen = getattr(d, "clone_generation", 0) or 0
    now = _now_utc_iso()
    with _connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        _ensure_drafts_table(conn)
        # Collision guard — NEVER auto-merge onto another draft already assigned to
        # the target customer in this batch (duplicate identity → operator choice).
        clash = conn.execute(
            "SELECT id FROM proforma_drafts WHERE batch_id=? AND client_name=? "
            "AND clone_generation=? AND id!=? LIMIT 1",
            (d.batch_id, new_name, gen, int(draft_id)),
        ).fetchone()
        if clash is not None:
            raise DraftConflict(
                f"batch {d.batch_id!r} already has a draft for customer {new_name!r} "
                f"(id={clash['id']}) at clone_generation={gen} — not auto-merged; "
                "resolve the duplicate manually before reassigning the customer."
            )
        # Identity + bill-to projection ONLY. Line items, source_lines, prices,
        # qty, batch_id and packing linkage are deliberately untouched.
        conn.execute(
            "UPDATE proforma_drafts SET client_name=?, client_contractor_id=?, "
            "buyer_override_json=?, draft_state=?, updated_at=? WHERE id=?",
            (
                new_name, new_cid,
                json.dumps(buyer_override, ensure_ascii=False, sort_keys=True),
                _next_state_after_edit(d.draft_state), now, int(draft_id),
            ),
        )
        conn.commit()

    # Charge + reservation migration — OUTSIDE the identity txn, best-effort and
    # DISCLOSED, mirroring migrate_draft_to_canonical_name's money-safe pattern.
    # The identity write has ALREADY committed above; a failure here therefore
    # cannot roll it back. On failure we append a STABLE, BROWSER-SAFE warning
    # (``migration_warning``) so the route can surface orphaned-charge /
    # stray-reservation risk in its response. The raw exception is logged
    # server-side ONLY (exc_info=True) — never placed in the warning, which
    # would leak internal paths / DB / wFirma payload detail to the browser.
    charges_dropped: List[Dict[str, Any]] = []
    warnings = migration_warnings if migration_warnings is not None else []
    if old_name != new_name:
        try:
            if charge_move is not None:
                charges_dropped = charge_move(d.batch_id, old_name, new_name) or []
        except Exception:
            log.warning("change_draft_customer charge migration failed (non-fatal) "
                        "%s→%s", old_name, new_name, exc_info=True)
            warnings.append(migration_warning("charge_move_failed"))
        try:
            if reservation_migrate is not None:
                reservation_migrate(d.batch_id, old_name, new_name)
        except Exception:
            log.warning("change_draft_customer reservation migration failed (non-fatal) "
                        "%s→%s", old_name, new_name, exc_info=True)
            warnings.append(migration_warning("reservation_migrate_failed"))

    _record_draft_event(
        db_path, draft_id=int(draft_id),
        event="draft_customer_changed",
        detail_json=json.dumps({
            "old_client_name":    old_name,
            "new_client_name":    new_name,
            "old_contractor_id":  str(old_cid),
            "new_contractor_id":  new_cid,
            "charges_dropped":    charges_dropped,   # non-empty only on defensive collision
            "migration_warnings": warnings,          # orphaned-charge / stray-reservation disclosure
            "buyer_override":     buyer_override,
        }, ensure_ascii=False, sort_keys=True),
        operator=operator,
    )
    refreshed = get_draft_by_id(db_path, int(draft_id))
    if refreshed is None:  # pragma: no cover - defensive
        raise DraftNotFound(f"draft id={draft_id} not found after change_customer")
    return refreshed


# ── Phase 4 — lifecycle controls + line add/remove ─────────────────────────

# Confirm tokens — the operator must include these literally in the
# request body to make irreversible state transitions explicit. They
# are not secrets; they exist purely to prevent accidental clicks.
APPROVE_CONFIRM_TOKEN = "YES_APPROVE_LOCAL_PROFORMA_DRAFT"
REOPEN_CONFIRM_TOKEN  = "YES_REOPEN_LOCAL_PROFORMA_DRAFT"

# State transition allowlists (subset of DRAFT_LIFECYCLE_STATES).
APPROVABLE_STATES = ("draft", "editing", "post_failed")
REOPENABLE_STATES = ("approved",)
CANCELLABLE_STATES = ("draft", "editing", "approved", "post_failed")
RESETTABLE_STATES = EDITABLE_STATES   # draft / editing / post_failed


def approve_draft(
    db_path:             Path,
    draft_id:            int,
    operator:            str,
    expected_updated_at: str,
    *,
    confirm_token:       str,
) -> ProformaDraft:
    """Lock the draft as ``approved``. Idempotent only at the wire layer:
    re-calling on an already-approved draft raises ``DraftNotEditable``
    (use ``reopen_draft`` first if intentional).

    Allowed from: draft, editing, post_failed. The previous state is
    captured in the event detail so audit can show the path.
    """
    if not (operator or "").strip():
        raise ValueError("operator is required")
    if (confirm_token or "").strip() != APPROVE_CONFIRM_TOKEN:
        raise ValueError(
            f"approve requires confirm_token={APPROVE_CONFIRM_TOKEN!r}"
        )
    d = get_draft_by_id(db_path, draft_id)
    if d is None:
        raise DraftNotFound(f"draft id={draft_id} not found")
    if d.draft_state not in APPROVABLE_STATES:
        raise DraftNotEditable(
            f"draft id={draft_id} is in state {d.draft_state!r}; "
            f"approve requires one of {APPROVABLE_STATES}"
        )
    _check_lock(d, expected_updated_at)
    now = _now_utc_iso()
    refreshed = _commit_draft_update(
        db_path, d.id,
        new_state        = "approved",
        new_approved_at  = now,
        new_approved_by  = str(operator),
        new_locked_at    = now,
    )
    _record_draft_event(
        db_path, draft_id=d.id, event="draft_approved",
        detail_json=json.dumps({
            "from_state": d.draft_state,
            "to_state":   "approved",
            "approved_by": str(operator),
            "approved_at": now,
        }, ensure_ascii=False, sort_keys=True),
        operator=operator,
    )
    return refreshed


def reopen_draft(
    db_path:             Path,
    draft_id:            int,
    operator:            str,
    expected_updated_at: str,
    *,
    confirm_token:       str,
) -> ProformaDraft:
    """Move an approved draft back to ``editing``. Allowed only from
    ``approved``. Clears ``locked_at``; preserves ``approved_at`` and
    ``approved_by`` for audit history (an operator can see it WAS
    approved before it was reopened).
    """
    if not (operator or "").strip():
        raise ValueError("operator is required")
    if (confirm_token or "").strip() != REOPEN_CONFIRM_TOKEN:
        raise ValueError(
            f"reopen requires confirm_token={REOPEN_CONFIRM_TOKEN!r}"
        )
    d = get_draft_by_id(db_path, draft_id)
    if d is None:
        raise DraftNotFound(f"draft id={draft_id} not found")
    if d.draft_state not in REOPENABLE_STATES:
        raise DraftNotEditable(
            f"draft id={draft_id} is in state {d.draft_state!r}; "
            f"reopen requires one of {REOPENABLE_STATES}"
        )
    _check_lock(d, expected_updated_at)
    refreshed = _commit_draft_update(
        db_path, d.id,
        new_state     = "editing",
        new_locked_at = None,
    )
    _record_draft_event(
        db_path, draft_id=d.id, event="draft_reopened",
        detail_json=json.dumps({
            "from_state":      d.draft_state,
            "to_state":        "editing",
            "previous_approved_at": d.approved_at,
            "previous_approved_by": d.approved_by,
        }, ensure_ascii=False, sort_keys=True),
        operator=operator,
    )
    return refreshed


def cancel_draft(
    db_path:             Path,
    draft_id:            int,
    operator:            str,
    expected_updated_at: str,
    *,
    reason:              str,
) -> ProformaDraft:
    """Mark a draft ``cancelled``. Reason is required and recorded in the
    event detail. Allowed from any pre-post state — but explicitly NOT
    from posted/cancelled/superseded/posting (those are immutable here).

    NB: this is a LOCAL cancel only. It does NOT delete a posted Proforma
    in wFirma — that's the existing ``cancel-issued-for-reissue`` route.
    """
    if not (operator or "").strip():
        raise ValueError("operator is required")
    if not (reason or "").strip():
        raise ValueError("reason is required")
    d = get_draft_by_id(db_path, draft_id)
    if d is None:
        raise DraftNotFound(f"draft id={draft_id} not found")
    if d.draft_state not in CANCELLABLE_STATES:
        raise DraftNotEditable(
            f"draft id={draft_id} is in state {d.draft_state!r}; "
            f"cancel requires one of {CANCELLABLE_STATES} — "
            f"posted Proformas must be cancelled via the wFirma reissue route"
        )
    _check_lock(d, expected_updated_at)
    now = _now_utc_iso()
    refreshed = _commit_draft_update(
        db_path, d.id,
        new_state     = "cancelled",
        new_locked_at = now,
    )
    _record_draft_event(
        db_path, draft_id=d.id, event="draft_cancelled",
        detail_json=json.dumps({
            "from_state": d.draft_state,
            "to_state":   "cancelled",
            "reason":     str(reason).strip(),
        }, ensure_ascii=False, sort_keys=True),
        operator=operator,
    )
    return refreshed


def purge_cancelled_draft(
    db_path:  Path,
    draft_id: int,
    operator: str,
) -> None:
    """Hard-delete a local-only cancelled draft and its event log.

    Guards (all must pass):
    - draft_state must be 'cancelled'
    - wfirma_proforma_id must be absent / None
    - wfirma_proforma_fullnumber must be absent / empty

    Removes the proforma_drafts row and its proforma_draft_events rows.
    Service charges and lines are stored as JSON columns on the draft row
    and are removed with it.
    """
    if not (operator or "").strip():
        raise ValueError("operator is required")
    d = get_draft_by_id(db_path, draft_id)
    if d is None:
        raise DraftNotFound(f"draft id={draft_id} not found")
    if d.draft_state != "cancelled":
        raise DraftNotEditable(
            f"draft id={draft_id} state={d.draft_state!r} — "
            f"purge requires state='cancelled'"
        )
    if d.wfirma_proforma_id:
        raise DraftNotEditable(
            f"draft id={draft_id} has wFirma proforma id {d.wfirma_proforma_id!r} — "
            f"cannot purge a draft linked to wFirma"
        )
    if d.wfirma_proforma_fullnumber:
        raise DraftNotEditable(
            f"draft id={draft_id} has proforma number "
            f"{d.wfirma_proforma_fullnumber!r} — "
            f"cannot purge a draft with an assigned number"
        )
    with _connect(db_path) as conn:
        conn.execute(
            "DELETE FROM proforma_draft_events WHERE draft_id = ?", (draft_id,)
        )
        conn.execute(
            "DELETE FROM proforma_drafts WHERE id = ?", (draft_id,)
        )
        conn.commit()


def reset_draft_from_sales_packing(
    db_path:             Path,
    draft_id:            int,
    operator:            str,
    expected_updated_at: str,
    *,
    sales_lines:         List[Dict[str, Any]],
    reset_all:           bool = False,
    name_pl_lookup:      Optional[Callable[[str], Optional[Dict[str, Any]]]] = None,
    desc_generate:       Optional[Callable[..., Optional[str]]] = None,
    product_mapping_lookup: Optional[Callable[[str], Optional[Dict[str, Any]]]] = None,
) -> ProformaDraft:
    """Rebuild ``editable_lines_json`` from caller-supplied sales-packing
    lines. The DB layer does not read documents.db; the route resolves
    the latest ``sales_packing_lines`` and passes them in.

    By default, buyer/ship-to/payment-terms/remarks/service-charges are
    PRESERVED. With ``reset_all=True`` they are cleared.

    Allowed from editable states. Lifecycle transition follows
    :func:`_next_state_after_edit` (post_failed stays put; draft → editing).
    """
    if not (operator or "").strip():
        raise ValueError("operator is required")
    if not isinstance(sales_lines, list):
        raise ValueError("sales_lines must be a list")

    d = _load_for_edit(db_path, draft_id, expected_updated_at)

    # Preserve operator-confirmed name_pl across the rebuild: a reset must
    # not strip a curated commercial description back to blank. Map the
    # PRIOR draft's non-blank name_pl by product_code so matching rebuilt
    # lines re-inherit it before product_descriptions enrichment fills any
    # remaining blanks.
    prior_names: Dict[str, str] = {}
    for _pl in (json.loads(d.editable_lines_json or "[]") or []):
        _pc  = str(_pl.get("product_code") or "").strip()
        _npl = str(_pl.get("name_pl") or "").strip()
        if _pc and _npl:
            prior_names.setdefault(_pc, _npl)

    # Reshape sales_packing_lines columns into editable_lines shape.
    # Skip rows with no product_code — product_code is required for
    # sales/proforma identity; design_no alone is not invoiceable.
    rebuilt: List[Dict[str, Any]] = []
    for r in sales_lines:
        product_code = str(r.get("product_code") or "").strip()
        design_no    = str(r.get("design_no") or "").strip()
        if not product_code:
            continue
        try:
            qty_f = float(r.get("qty", r.get("quantity", 0)) or 0)
        except (TypeError, ValueError):
            qty_f = 0.0
        try:
            up_f = float(r.get("unit_price", 0) or 0)
        except (TypeError, ValueError):
            up_f = 0.0
        rebuilt_row = {
            "product_code": product_code,
            "design_no":    design_no,
            "qty":          qty_f,
            "unit_price":   up_f,
            "currency":     str(r.get("currency") or d.currency or "").upper(),
            "price_source": str(r.get("price_source") or ""),
            "client_ref":   str(r.get("client_ref") or ""),
            # Variant identity (sales_packing columns) — display only.
            **_sales_variant_fields(r),
            # Carry incoming name_pl if present, else re-inherit the prior
            # operator-confirmed name_pl. Enrichment (below) fills any blank
            # that survives without overwriting a non-blank value.
            "name_pl":      (str(r.get("name_pl") or "").strip()
                             or prior_names.get(product_code, "")),
        }
        rebuilt.append(rebuilt_row)
    rebuilt = _ensure_line_ids(rebuilt)
    reset_unresolved = _birth_unresolved_lines(rebuilt, product_mapping_lookup)

    kwargs: Dict[str, Any] = {
        "new_state":          _next_state_after_edit(d.draft_state),
        "new_editable_lines": rebuilt,
    }
    if reset_all:
        kwargs.update({
            "new_buyer_override":   {},
            "new_ship_to_override": {},
            "new_payment_terms":    {},
            "new_remarks":          "",
            "new_service_charges":  [],
        })

    refreshed = _commit_draft_update(db_path, d.id, **kwargs)
    _record_draft_event(
        db_path, draft_id=d.id, event="draft_reset_from_sales_packing",
        detail_json=json.dumps({
            "from_state":      d.draft_state,
            "to_state":        refreshed.draft_state,
            "reset_all":       bool(reset_all),
            "lines_before":    len(json.loads(d.editable_lines_json or "[]") or []),
            "lines_after":     len(rebuilt),
            # Same non-authoritative advisory as birth — visibility only.
            "birth_unresolved": reset_unresolved,
        }, ensure_ascii=False, sort_keys=True),
        operator=operator,
    )
    return refreshed


# ── PR 2C — product-description enrichment ──────────────────────────────────

def enrich_lines_from_product_descriptions(
    lines:     List[Dict[str, Any]],
    lookup_fn: Callable[[str], Optional[Dict[str, Any]]],
) -> Tuple[List[Dict[str, Any]], int, int]:
    """Annotate each editable line with canonical product-description fields.

    Pure function — no DB I/O.  The caller supplies *lookup_fn* so this
    module stays free from document_db imports.

    For each line the following annotation keys are added (or overwritten):
        item_type, name_pl, description_pl, description_en,
        description_bilingual, pd_confidence

    If no product_descriptions row exists for the line's product_code all
    six keys are set to ``None``.

    ``description_bilingual`` resolution priority:
        1. row["description_bilingual"]
        2. row["description_block"]
        3. "<description_pl> / <description_en>" when both are non-empty
        4. None

    All existing fields (qty, unit_price, currency, price_source, client_ref,
    product_code, design_no, line_id …) are preserved unchanged.

    Returns:
        (enriched_lines, enriched_count, missing_count)
    """
    enriched: List[Dict[str, Any]] = []
    n_hit = 0
    n_miss = 0
    for ln in lines:
        pc  = str(ln.get("product_code") or "").strip()
        row = lookup_fn(pc) if pc else None
        if row:
            # Resolve description_bilingual with fallback chain.
            bil = (str(row.get("description_bilingual") or "").strip()
                   or str(row.get("description_block") or "").strip()
                   or None)
            if bil is None:
                dp = str(row.get("description_pl") or "").strip()
                de = str(row.get("description_en") or "").strip()
                if dp and de:
                    bil = f"{dp} / {de}"
            enriched.append({
                **ln,
                "item_type":             str(row.get("item_type") or "").strip() or None,
                "name_pl":               str(row.get("name_pl") or "").strip() or None,
                "description_pl":        str(row.get("description_pl") or "").strip() or None,
                "description_en":        str(row.get("description_en") or "").strip() or None,
                "description_bilingual": bil,
                "pd_confidence":         str(row.get("confidence") or "").strip() or None,
            })
            n_hit += 1
        else:
            enriched.append({
                **ln,
                "item_type":             None,
                "name_pl":               None,
                "description_pl":        None,
                "description_en":        None,
                "description_bilingual": None,
                "pd_confidence":         None,
            })
            n_miss += 1
    return enriched, n_hit, n_miss


def enrich_draft_lines(
    db_path:             Path,
    draft_id:            int,
    operator:            str,
    expected_updated_at: str,
    lookup_fn:           Callable[[str], Optional[Dict[str, Any]]],
) -> ProformaDraft:
    """Enrich ``editable_lines_json`` with product-description annotations.

    ``source_lines_json`` is NEVER touched.  ``draft_state`` is preserved
    unchanged (enrichment is a pure annotation, not a lifecycle transition).
    Allowed only from :data:`EDITABLE_STATES`.

    Records event ``lines_enriched_from_product_descriptions`` with detail::

        {"enriched_count": N, "missing_count": M, "line_count": total}

    Returns the refreshed :class:`ProformaDraft`.
    """
    if not (operator or "").strip():
        raise ValueError("operator is required")

    d = _load_for_edit(db_path, draft_id, expected_updated_at)
    lines = _ensure_line_ids(json.loads(d.editable_lines_json or "[]") or [])
    enriched, n_hit, n_miss = enrich_lines_from_product_descriptions(lines, lookup_fn)

    refreshed = _commit_draft_update(
        db_path,
        d.id,
        new_state          = d.draft_state,   # state unchanged
        new_editable_lines = enriched,
    )
    _record_draft_event(
        db_path,
        draft_id    = d.id,
        event       = "lines_enriched_from_product_descriptions",
        detail_json = json.dumps({
            "enriched_count": n_hit,
            "missing_count":  n_miss,
            "line_count":     len(enriched),
        }, ensure_ascii=False, sort_keys=True),
        operator    = operator or "",
    )
    return refreshed


def add_draft_line(
    db_path:             Path,
    draft_id:            int,
    line:                Dict[str, Any],
    operator:            str,
    expected_updated_at: str,
) -> ProformaDraft:
    """Append a new editable line.

    Required keys: product_code, qty, unit_price, currency.
    Optional: design_no, client_ref, price_source, remarks.

    Currency must be a member of :data:`ALLOWED_CURRENCIES`. We do NOT
    enforce per-line currency uniformity here; the operator may
    intentionally mix (Phase 5 posting will reject mixed-currency lines
    against a single Proforma).
    """
    if not (operator or "").strip():
        raise ValueError("operator is required")
    if not isinstance(line, dict):
        raise ValueError("line must be a JSON object")

    product_code = str(line.get("product_code") or "").strip()
    if not product_code:
        raise ValueError("product_code is required and cannot be blank")
    try:
        qty = float(line.get("qty", line.get("quantity", 0)) or 0)
    except (TypeError, ValueError):
        raise ValueError(f"qty must be numeric, got {line.get('qty')!r}")
    if qty <= 0:
        raise ValueError("qty must be > 0")
    try:
        up = float(line.get("unit_price", 0) or 0)
    except (TypeError, ValueError):
        raise ValueError(
            f"unit_price must be numeric, got {line.get('unit_price')!r}")
    if up < 0:
        raise ValueError("unit_price must be >= 0")
    ccy = _validate_currency(str(line.get("currency") or ""))

    d = _load_for_edit(db_path, draft_id, expected_updated_at)

    try:
        lines = _ensure_line_ids(json.loads(d.editable_lines_json or "[]") or [])
    except Exception:
        lines = []
    used_ids = {int(l.get("line_id") or 0) for l in lines
                if isinstance(l.get("line_id"), int)}
    new_id = (max(used_ids) if used_ids else 0) + 1
    new_line = {
        "line_id":      new_id,
        "product_code": product_code,
        "design_no":    str(line.get("design_no") or "").strip(),
        "qty":          qty,
        "unit_price":   up,
        "currency":     ccy,
        "price_source": str(line.get("price_source") or "manual"),
        "client_ref":   str(line.get("client_ref") or ""),
    }
    if "remarks" in line:
        new_line["remarks"] = str(line["remarks"] or "")
    lines.append(new_line)

    refreshed = _commit_draft_update(
        db_path, d.id,
        new_state          = _next_state_after_edit(d.draft_state),
        new_editable_lines = lines,
    )
    _record_draft_event(
        db_path, draft_id=d.id, event="draft_line_added",
        detail_json=json.dumps({
            "line":       new_line,
            "from_state": d.draft_state,
            "to_state":   refreshed.draft_state,
        }, ensure_ascii=False, sort_keys=True),
        operator=operator,
    )
    return refreshed


def remove_draft_line(
    db_path:             Path,
    draft_id:            int,
    line_id:             int,
    operator:            str,
    expected_updated_at: str,
    *,
    force:               bool = False,
) -> ProformaDraft:
    """Remove a line by ``line_id``.

    Refuses to remove the last product line unless ``force=True``. A
    Proforma with zero product lines cannot be posted, so this guard
    prevents an operator from accidentally emptying the draft.
    """
    if not (operator or "").strip():
        raise ValueError("operator is required")

    d = _load_for_edit(db_path, draft_id, expected_updated_at)
    try:
        lines = _ensure_line_ids(json.loads(d.editable_lines_json or "[]") or [])
    except Exception:
        lines = []

    target = next(
        (ln for ln in lines if int(ln.get("line_id") or 0) == int(line_id)),
        None,
    )
    if target is None:
        raise ValueError(f"line_id={line_id} not found on draft id={draft_id}")

    remaining = [ln for ln in lines
                  if int(ln.get("line_id") or 0) != int(line_id)]
    if len(remaining) == 0 and not force:
        raise ValueError(
            "removing the last product line would leave the draft empty; "
            "pass force=true to confirm"
        )

    refreshed = _commit_draft_update(
        db_path, d.id,
        new_state          = _next_state_after_edit(d.draft_state),
        new_editable_lines = remaining,
    )
    _record_draft_event(
        db_path, draft_id=d.id, event="draft_line_removed",
        detail_json=json.dumps({
            "removed":    target,
            "force":      bool(force),
            "from_state": d.draft_state,
            "to_state":   refreshed.draft_state,
        }, ensure_ascii=False, sort_keys=True),
        operator=operator,
    )
    return refreshed


# ── Phase 5 — operator-driven posting to wFirma ────────────────────────────

# Confirm token mandatory in the POST body. Distinct from approve/reopen so
# accidental clicks elsewhere never trigger a wFirma write.
POST_CONFIRM_TOKEN = "YES_POST_LOCAL_PROFORMA_DRAFT_TO_WFIRMA"

# Only an explicitly-approved draft may post. post_failed drafts do NOT
# go directly back to posting — operator must re-open + edit + approve
# again. This prevents an in-place retry from masking root-cause issues
# captured in the failed-post notes.
POSTABLE_STATES = ("approved",)


def start_post(
    db_path:             Path,
    draft_id:            int,
    operator:            str,
    expected_updated_at: str,
    *,
    confirm_token:       str,
) -> ProformaDraft:
    """Transition ``approved → posting``. The commit point: any failure
    after this returns the draft to ``post_failed``, never silently to
    ``approved``.

    Sets ``posting_started_at``, ``posting_started_by``, legacy
    ``status='pending_local'``. Emits ``draft_post_started`` event.

    Raises:
      DraftNotFound       — draft id unknown
      DraftNotEditable    — wrong state, or wfirma_proforma_id already set
      DraftConflict       — stale expected_updated_at
      ValueError          — operator empty, confirm_token wrong
    """
    if not (operator or "").strip():
        raise ValueError("operator is required")
    if (confirm_token or "").strip() != POST_CONFIRM_TOKEN:
        raise ValueError(
            f"post requires confirm_token={POST_CONFIRM_TOKEN!r}"
        )
    d = get_draft_by_id(db_path, draft_id)
    if d is None:
        raise DraftNotFound(f"draft id={draft_id} not found")
    if d.draft_state not in POSTABLE_STATES:
        raise DraftNotEditable(
            f"draft id={draft_id} is in state {d.draft_state!r}; "
            f"post requires one of {POSTABLE_STATES} — re-open and re-approve "
            "to retry a post_failed draft"
        )
    if (d.wfirma_proforma_id or "").strip():
        raise DraftNotEditable(
            f"draft id={draft_id} already has wfirma_proforma_id="
            f"{d.wfirma_proforma_id!r}; cannot post twice"
        )
    _check_lock(d, expected_updated_at)
    now = _now_utc_iso()
    refreshed = _commit_draft_update(
        db_path, d.id,
        new_state              = "posting",
        new_status             = "pending_local",
        new_posting_started_at = now,
        new_posting_started_by = str(operator),
    )
    _record_draft_event(
        db_path, draft_id=d.id, event="draft_post_started",
        detail_json=json.dumps({
            "from_state": d.draft_state,
            "to_state":   "posting",
            "started_by": str(operator),
            "started_at": now,
        }, ensure_ascii=False, sort_keys=True),
        operator=operator,
    )
    return refreshed


def mark_post_succeeded(
    db_path:                    Path,
    draft_id:                   int,
    *,
    wfirma_proforma_id:         str,
    wfirma_proforma_fullnumber: str = "",
    operator:                   str,
) -> ProformaDraft:
    """Transition ``posting → posted``. Caller must have already received
    a successful ``ProformaResult`` from wFirma — this helper does NO
    external I/O.

    Raises:
      DraftNotFound     — draft id unknown
      DraftNotEditable  — not currently in ``posting``
      ValueError        — wfirma_proforma_id empty, operator empty
    """
    if not (operator or "").strip():
        raise ValueError("operator is required")
    if not (wfirma_proforma_id or "").strip():
        raise ValueError("wfirma_proforma_id is required to mark posted")
    d = get_draft_by_id(db_path, draft_id)
    if d is None:
        raise DraftNotFound(f"draft id={draft_id} not found")
    if d.draft_state != "posting":
        raise DraftNotEditable(
            f"draft id={draft_id} is in state {d.draft_state!r}; "
            "mark_post_succeeded requires 'posting'"
        )
    now = _now_utc_iso()
    refreshed = _commit_draft_update(
        db_path, d.id,
        new_state                       = "posted",
        new_status                      = "issued",
        new_wfirma_proforma_id          = str(wfirma_proforma_id),
        new_wfirma_proforma_fullnumber  = str(wfirma_proforma_fullnumber or ""),
        new_posted_at                   = now,
        new_posted_by                   = str(operator),
    )
    _record_draft_event(
        db_path, draft_id=d.id, event="draft_posted",
        detail_json=json.dumps({
            "from_state":                 "posting",
            "to_state":                   "posted",
            "wfirma_proforma_id":         str(wfirma_proforma_id),
            "wfirma_proforma_fullnumber": str(wfirma_proforma_fullnumber or ""),
            "posted_by":                  str(operator),
            "posted_at":                  now,
        }, ensure_ascii=False, sort_keys=True),
        operator=operator,
    )
    return refreshed


def mark_post_failed(
    db_path:   Path,
    draft_id:  int,
    *,
    error:     str,
    operator:  str,
) -> ProformaDraft:
    """Transition ``posting → post_failed``. Truncates ``error`` to 500
    chars and stores it on ``notes``. Emits ``draft_post_failed`` event.
    """
    if not (operator or "").strip():
        raise ValueError("operator is required")
    d = get_draft_by_id(db_path, draft_id)
    if d is None:
        raise DraftNotFound(f"draft id={draft_id} not found")
    if d.draft_state != "posting":
        raise DraftNotEditable(
            f"draft id={draft_id} is in state {d.draft_state!r}; "
            "mark_post_failed requires 'posting'"
        )
    truncated = (str(error or "")[:500]).strip() or "wfirma create returned ok=false"
    now = _now_utc_iso()
    refreshed = _commit_draft_update(
        db_path, d.id,
        new_state          = "post_failed",
        new_status         = "failed",
        new_notes          = truncated,
        new_post_failed_at = now,
    )
    _record_draft_event(
        db_path, draft_id=d.id, event="draft_post_failed",
        detail_json=json.dumps({
            "from_state":     "posting",
            "to_state":       "post_failed",
            "error":          truncated,
            "post_failed_at": now,
        }, ensure_ascii=False, sort_keys=True),
        operator=operator,
    )
    return refreshed


def record_post_orphan(
    db_path:            Path,
    draft_id:           int,
    *,
    wfirma_proforma_id: str,
    error:              str,
    operator:           str = "",
) -> bool:
    """Best-effort: record a ``draft_post_orphan`` event when wFirma
    succeeded but the local UPDATE that should have written the
    ``posted`` state failed. Returns True if the event was recorded,
    False otherwise. Never raises — the caller is already in an error
    path and we don't want to mask the original failure.

    The operator can recover by calling the existing
    ``POST /api/v1/proforma/adopt-issued/{batch}/{client}`` route with
    the returned ``wfirma_proforma_id``.
    """
    try:
        # The events table is a separate row in the same DB. If the
        # main UPDATE failed because of a transient lock the events
        # write may still succeed.
        _record_draft_event(
            db_path, draft_id=int(draft_id), event="draft_post_orphan",
            detail_json=json.dumps({
                "wfirma_proforma_id": str(wfirma_proforma_id or ""),
                "error":              (str(error or "")[:500]).strip(),
                "recovery_hint":      "use POST /adopt-issued/{batch}/{client} "
                                      "to re-link the orphan to this draft",
            }, ensure_ascii=False, sort_keys=True),
            operator=operator or "",
        )
        return True
    except Exception:
        return False


_PATCHABLE_STATES = ("draft", "editing", "post_failed", "approved")


def apply_sales_price_patch(
    db_path:                   "Path",
    draft_id:                  int,
    operator:                  str,
    expected_updated_at:       str,
    *,
    patched_lines:             "List[Dict[str, Any]]",
    sales_authority_total_eur: float,
    sales_invoice_ref:         str,
) -> "ProformaDraft":
    """Import sales-price authority into a draft.

    Auto-reopens 'approved' drafts to 'editing' before patching.
    Allowed from: draft, editing, post_failed, approved.
    """
    d = get_draft_by_id(db_path, draft_id)
    if d is None:
        raise DraftNotFound(f"draft id={draft_id} not found")
    if d.draft_state not in _PATCHABLE_STATES:
        raise DraftNotEditable(
            f"draft id={draft_id} is in state {d.draft_state!r}; "
            f"must be one of {_PATCHABLE_STATES}"
        )

    reopened = False
    if d.draft_state == "approved":
        _check_lock(d, expected_updated_at)
        d = _commit_draft_update(
            db_path, draft_id,
            new_state="editing",
            new_approved_at=None,
            new_approved_by=None,
        )
        _record_draft_event(
            db_path, draft_id=draft_id,
            event="draft_reopened_for_price_import",
            detail_json=json.dumps({"reason": "sales_price_import"}, ensure_ascii=False),
            operator=operator,
        )
        reopened = True

    if not reopened:
        _check_lock(d, expected_updated_at)

    now = _now_utc_iso()
    refreshed = _commit_draft_update(
        db_path, draft_id,
        new_state=d.draft_state if not reopened else "editing",
        new_editable_lines=patched_lines,
        new_sales_price_authority_total_eur=sales_authority_total_eur,
        new_sales_price_imported_at=now,
        new_sales_price_invoice_ref=sales_invoice_ref,
    )
    _record_draft_event(
        db_path, draft_id=draft_id,
        event="sales_price_patch_applied",
        detail_json=json.dumps({
            "sales_invoice_ref":         sales_invoice_ref,
            "sales_authority_total_eur": sales_authority_total_eur,
            "lines_patched":             len(patched_lines),
        }, ensure_ascii=False),
        operator=operator,
    )
    return refreshed


__all__ = [
    "ProformaInvoiceLink",
    "ProformaAlreadyConverted",
    "VALID_STATUSES",
    "validate",
    "init_db",
    "create_pending_link",
    "mark_issued",
    "mark_failed",
    "get_link_by_proforma",
    "get_link_by_invoice",
    "get_pz_doc_id",
    "set_pz_doc_id",
    "list_links",
    # ── Proforma drafts (pre-create staging) ──
    "ProformaDraft",
    "DRAFT_STATUSES",
    "KNOWN_LEGACY_STATUSES",
    "DRAFT_LIFECYCLE_STATES",
    "_normalise_draft_status",
    "_normalise_draft_state",
    "upsert_pending_draft",
    "get_draft",
    "mark_draft_failed",
    "mark_draft_issued",
    "mark_draft_cancelled_for_reissue",
    "adopt_issued_draft",
    # ── Phase 2 — editable lifecycle ──
    "auto_create_draft_from_sales_packing",
    # ── Phase 3 — editable mutation API ──
    "EDITABLE_STATES",
    "ALLOWED_CURRENCIES",
    "EDITABLE_DRAFT_FIELDS",
    "EDITABLE_LINE_FIELDS",
    "ALLOWED_SERVICE_CHARGE_TYPES",
    "upsert_service_product_meta",
    "get_service_product_meta",
    "get_all_service_product_meta",
    "_FORBIDDEN_FORMULA_BASIS_PREFIXES",
    "DraftNotFound",
    "DraftNotEditable",
    "DraftConflict",
    "OverwriteRequired",
    "update_draft_fields",
    "update_draft_line",
    "bulk_price_recovery",
    "add_draft_service_charge",
    "remove_draft_service_charge",
    # ── Phase 4 — lifecycle controls + line add/remove ──
    "APPROVE_CONFIRM_TOKEN",
    "REOPEN_CONFIRM_TOKEN",
    "APPROVABLE_STATES",
    "REOPENABLE_STATES",
    "CANCELLABLE_STATES",
    "RESETTABLE_STATES",
    "approve_draft",
    "reopen_draft",
    "cancel_draft",
    "reset_draft_from_sales_packing",
    "add_draft_line",
    "remove_draft_line",
    # ── Phase 5 — operator-driven posting to wFirma ──
    "POST_CONFIRM_TOKEN",
    "POSTABLE_STATES",
    "start_post",
    "mark_post_succeeded",
    "mark_post_failed",
    "record_post_orphan",
    "list_drafts_for_batch",
    "get_draft_by_id",
    "search_drafts",
    "list_draft_events",
    "_record_draft_event",
    "apply_sales_price_patch",
    "apply_customer_address_to_draft",
]
