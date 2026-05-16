"""
backfill_finance_postings.py — Phase 6F.2.a — Backfill legacy
proforma_service_charges rows into the new finance_postings schema.

> **DEFAULT MODE: DRY-RUN.** Live mode requires `--write` AND
> `--snapshot-dir`. There is no implicit live path; the operator must
> explicitly opt in.

What it does
============
For every row in the legacy ``proforma_service_charges`` table:
  1. Validate row eligibility (non-empty currency, ISO 4217, charge_type
     in allow-list).
  2. Compute a deterministic idempotency key
     ``sha1("legacy_psc:" + batch_id + ":" + client_name + ":" + charge_type)``.
  3. Group charges by ``(batch_id, client_name)`` — one synthetic
     ``postings`` row per group (Strategy A from the inspection report).
  4. In dry-run mode: enumerate everything and write a JSON report. No
     writes to the target DB.
  5. In live mode: take a snapshot, then INSERT INTO charges + postings
     using the idempotency key to skip already-backfilled rows.

What it does NOT do
===================
- Does NOT modify the legacy table.
- Does NOT call wFirma, proforma, settlement, FX, PZ, DHL.
- Does NOT touch any other DB file.
- Does NOT auto-merge or auto-deploy.
- Does NOT run in a background thread.

CLI
===
Dry-run (default; safe; no writes):
    python backfill_finance_postings.py \\
        --source-db <path/to/proforma_links.db> \\
        --target-db <path/to/finance_postings.sqlite> \\
        --report-path <path/to/dryrun-<date>.json> \\
        --dry-run

Live (requires explicit flags):
    python backfill_finance_postings.py \\
        --source-db <path/to/proforma_links.db> \\
        --target-db <path/to/finance_postings.sqlite> \\
        --report-path <path/to/live-<date>.json> \\
        --write \\
        --snapshot-dir <path/to/snapshots/> \\
        --chunk-size 100

Exit codes
==========
0  — completed; report written; live writes (if any) committed
1  — validation failures or blocked rows encountered (still wrote report)
2  — fatal error (missing source DB, snapshot failure, etc.)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ── Constants ─────────────────────────────────────────────────────────────

#: Charge types in the legacy table that the new schema accepts.
LEGACY_TO_NEW_CHARGE_TYPES = {
    "freight":   "freight",
    "insurance": "insurance",
}

#: ISO 4217 pattern; mirrors finance_postings_db's _ISO_4217_RE.
import re
_ISO_4217_RE = re.compile(r"^[A-Z]{3}$")

#: Prefix used for the idempotency marker stored in charges.notes.
IDEMPOTENCY_PREFIX = "[backfill:sha1="
#: Prefix used to mark synthetic postings in wfirma_invoice_id.
POSTING_SYNTHETIC_PREFIX = "BACKFILL-"

#: Source-table name (legacy).
LEGACY_TABLE = "proforma_service_charges"


# ── Data classes ───────────────────────────────────────────────────────────

@dataclass
class LegacyCharge:
    id:          int
    batch_id:    str
    client_name: str
    charge_type: str
    amount:      float
    currency:    str
    note:        str
    created_at:  str
    created_by:  str
    updated_at:  str

    @property
    def idempotency_sha1(self) -> str:
        material = f"legacy_psc:{self.batch_id}:{self.client_name}:{self.charge_type}"
        return hashlib.sha1(material.encode("utf-8")).hexdigest()

    @property
    def amount_minor(self) -> int:
        """Convert REAL amount → minor units safely. Uses Decimal to avoid
        float drift (e.g. 3.49 * 100 != 348.99999... after rounding)."""
        try:
            d = Decimal(str(self.amount))
        except (InvalidOperation, ValueError):
            raise ValueError(f"cannot parse amount={self.amount!r} as Decimal")
        return int((d * 100).quantize(Decimal("1"), rounding="ROUND_HALF_EVEN"))


@dataclass
class GroupKey:
    batch_id:    str
    client_name: str

    @property
    def synthetic_posting_id(self) -> str:
        material = f"legacy_psc_posting:{self.batch_id}:{self.client_name}"
        return POSTING_SYNTHETIC_PREFIX + hashlib.sha1(material.encode("utf-8")).hexdigest()[:16]


@dataclass
class BackfillReport:
    started_at:   str = ""
    finished_at:  str = ""
    mode:         str = "dry-run"
    source_db:    str = ""
    target_db:    str = ""
    snapshot:     Optional[str] = None
    chunk_size:   int = 100
    # Counters
    source_rows:           int = 0
    eligible_rows:         int = 0
    blocked_rows:          int = 0
    skipped_zero:          int = 0
    duplicate_skipped:     int = 0
    charges_to_create:     int = 0
    postings_to_create:    int = 0
    charges_created:       int = 0
    postings_created:      int = 0
    blocked_reasons:       Dict[str, int] = field(default_factory=dict)
    blocked_examples:      List[Dict[str, Any]] = field(default_factory=list)
    synthetic_postings:    List[Dict[str, Any]] = field(default_factory=list)

    def add_blocked(self, reason: str, row: LegacyCharge) -> None:
        self.blocked_rows += 1
        self.blocked_reasons[reason] = self.blocked_reasons.get(reason, 0) + 1
        if len(self.blocked_examples) < 10:
            self.blocked_examples.append({
                "id": row.id, "batch_id": row.batch_id,
                "client_name": row.client_name, "charge_type": row.charge_type,
                "reason": reason,
            })

    def to_dict(self) -> Dict[str, Any]:
        return {
            "started_at":          self.started_at,
            "finished_at":         self.finished_at,
            "mode":                self.mode,
            "source_db":           self.source_db,
            "target_db":           self.target_db,
            "snapshot":            self.snapshot,
            "chunk_size":          self.chunk_size,
            "source_rows":         self.source_rows,
            "eligible_rows":       self.eligible_rows,
            "blocked_rows":        self.blocked_rows,
            "skipped_zero":        self.skipped_zero,
            "duplicate_skipped":   self.duplicate_skipped,
            "charges_to_create":   self.charges_to_create,
            "postings_to_create":  self.postings_to_create,
            "charges_created":     self.charges_created,
            "postings_created":    self.postings_created,
            "blocked_reasons":     dict(self.blocked_reasons),
            "blocked_examples":    list(self.blocked_examples),
            "synthetic_postings":  list(self.synthetic_postings),
        }


# ── Source read ────────────────────────────────────────────────────────────

def read_legacy_charges(source_db: Path) -> List[LegacyCharge]:
    """Read all rows from the legacy proforma_service_charges table.

    Returns an empty list if the source file does not exist or the table
    is missing (cleanly indicating "no legacy data to backfill")."""
    source_db = Path(source_db)
    if not source_db.exists():
        return []
    with sqlite3.connect(str(source_db)) as conn:
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                f"SELECT id, batch_id, client_name, charge_type, amount, "
                f"currency, note, created_at, created_by, updated_at "
                f"FROM {LEGACY_TABLE} ORDER BY id ASC"
            ).fetchall()
        except sqlite3.OperationalError:
            return []
    out: List[LegacyCharge] = []
    for r in rows:
        out.append(LegacyCharge(
            id=int(r["id"]), batch_id=str(r["batch_id"] or ""),
            client_name=str(r["client_name"] or ""),
            charge_type=str(r["charge_type"] or ""),
            amount=float(r["amount"] or 0),
            currency=str(r["currency"] or "").strip().upper(),
            note=str(r["note"] or ""),
            created_at=str(r["created_at"] or ""),
            created_by=str(r["created_by"] or ""),
            updated_at=str(r["updated_at"] or ""),
        ))
    return out


# ── Eligibility ────────────────────────────────────────────────────────────

def classify_row(row: LegacyCharge) -> Tuple[str, Optional[str]]:
    """Return ('eligible', None) / ('blocked', reason) / ('skipped_zero', None)."""
    # Empty currency → BLOCKED (operator must triage)
    if not row.currency:
        return ("blocked", "empty_currency")
    if not _ISO_4217_RE.match(row.currency):
        return ("blocked", f"non_iso_currency:{row.currency}")
    if row.charge_type not in LEGACY_TO_NEW_CHARGE_TYPES:
        return ("blocked", f"unknown_charge_type:{row.charge_type}")
    if not row.batch_id:
        return ("blocked", "empty_batch_id")
    if not row.client_name:
        return ("blocked", "empty_client_name")
    # Zero amount → SKIPPED (operator-cleared row; preserved for audit)
    try:
        if row.amount_minor == 0:
            return ("skipped_zero", None)
    except ValueError as e:
        return ("blocked", f"amount_parse_error:{e}")
    return ("eligible", None)


# ── Target query helpers (read-only on existing charges) ──────────────────

def _conn(db_path: Path) -> sqlite3.Connection:
    c = sqlite3.connect(str(db_path))
    c.row_factory = sqlite3.Row
    return c


def find_existing_backfill_charge(target_db: Path, idempotency_sha1: str) -> Optional[int]:
    """Return the id of an existing backfilled charge for this idempotency
    key, or None if not present. Read-only."""
    target_db = Path(target_db)
    if not target_db.exists():
        return None
    with _conn(target_db) as c:
        try:
            r = c.execute(
                "SELECT id FROM charges "
                "WHERE source=? AND notes LIKE ? LIMIT 1",
                ("legacy_backfill", f"{IDEMPOTENCY_PREFIX}{idempotency_sha1}]%"),
            ).fetchone()
        except sqlite3.OperationalError:
            return None
    return int(r["id"]) if r else None


def find_existing_synthetic_posting(target_db: Path,
                                    synthetic_id: str) -> Optional[int]:
    """Return the id of an existing synthetic posting for this group key,
    or None if not present."""
    target_db = Path(target_db)
    if not target_db.exists():
        return None
    with _conn(target_db) as c:
        try:
            r = c.execute(
                "SELECT id FROM postings WHERE wfirma_invoice_id=? LIMIT 1",
                (synthetic_id,),
            ).fetchone()
        except sqlite3.OperationalError:
            return None
    return int(r["id"]) if r else None


# ── Snapshot ──────────────────────────────────────────────────────────────

def take_snapshot(target_db: Path, snapshot_dir: Path) -> Path:
    """Copy target_db into snapshot_dir with timestamped filename. Returns
    the snapshot path. Raises if snapshot_dir is not writeable or target
    file does not exist."""
    target_db = Path(target_db)
    snapshot_dir = Path(snapshot_dir)
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = snapshot_dir / f"finance_postings.pre-6F2.{ts}.sqlite"
    if target_db.exists():
        shutil.copy2(str(target_db), str(out))
    else:
        # Target doesn't exist yet — write an empty marker so the snapshot
        # entry is still recorded (operator can interpret as "fresh state")
        out.write_bytes(b"")
    return out


# ── Live insertion ─────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _ensure_target_schema(target_db: Path) -> None:
    """Lazily init the target DB using finance_postings_db.init_db. Imported
    inside the function to avoid coupling at module-load time."""
    # We're invoking the production-approved init path here. This is the only
    # path in 6F.2.a that imports the DB module.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.services.finance_postings_db import init_db  # type: ignore
    init_db(target_db)


def insert_charges_chunk(target_db: Path,
                          group: GroupKey,
                          rows: List[LegacyCharge]) -> Tuple[int, int]:
    """Insert one synthetic posting + N charges for a group. Returns
    (postings_inserted, charges_inserted). All inserts wrapped in one
    transaction per group; commits at end.

    Idempotent: if the synthetic posting or any charge already exists by
    its idempotency marker, that row is skipped without raising.
    """
    synthetic_id = group.synthetic_posting_id
    posted_id = find_existing_synthetic_posting(target_db, synthetic_id)
    postings_inserted = 0
    charges_inserted  = 0

    # All rows in the group should share a currency; assert this defensively.
    currencies = {r.currency for r in rows}
    if len(currencies) > 1:
        raise ValueError(
            f"mixed currencies in group ({group.batch_id}, "
            f"{group.client_name}): {sorted(currencies)}"
        )
    currency = next(iter(currencies))

    issued_total_minor = sum(r.amount_minor for r in rows)
    earliest_created  = min((r.created_at for r in rows
                              if r.created_at), default=None)

    now = _now()
    with _conn(target_db) as c:
        # Posting (synthetic)
        if posted_id is None:
            cur = c.execute(
                """INSERT INTO postings (batch_id, client_name,
                   wfirma_invoice_id, wfirma_doc_number, posting_kind,
                   posted_at, issued_total_minor, currency,
                   fx_rate_at_issue, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (group.batch_id, group.client_name,
                 synthetic_id, None, "proforma",
                 earliest_created, issued_total_minor, currency,
                 None, now, now),
            )
            posted_id = int(cur.lastrowid)
            postings_inserted += 1

        # Charges
        for row in rows:
            existing = find_existing_backfill_charge(target_db, row.idempotency_sha1)
            if existing is not None:
                continue
            note_with_marker = (
                f"{IDEMPOTENCY_PREFIX}{row.idempotency_sha1}]"
                + (("\n" + row.note) if row.note else "")
            )
            cur = c.execute(
                """INSERT INTO charges (batch_id, client_name, charge_type,
                   amount_minor, currency, source, posting_id, notes,
                   created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (row.batch_id, row.client_name,
                 LEGACY_TO_NEW_CHARGE_TYPES[row.charge_type],
                 row.amount_minor, row.currency, "legacy_backfill",
                 posted_id, note_with_marker, now, now),
            )
            charges_inserted += 1
        c.commit()

    return postings_inserted, charges_inserted


# ── Orchestration ──────────────────────────────────────────────────────────

def run_backfill(*, source_db: Path, target_db: Path, report_path: Path,
                  write: bool = False, snapshot_dir: Optional[Path] = None,
                  chunk_size: int = 100) -> Tuple[int, BackfillReport]:
    """Main orchestration. Returns (exit_code, report).

    exit_code:
      0 — success (dry-run completed; or live write committed)
      1 — completed but blocked rows exist (still wrote report)
      2 — fatal error before any inserts (missing source DB; snapshot failure)
    """
    report = BackfillReport(
        started_at=_now(),
        mode="live" if write else "dry-run",
        source_db=str(source_db),
        target_db=str(target_db),
        chunk_size=chunk_size,
    )

    source_db   = Path(source_db)
    target_db   = Path(target_db)
    report_path = Path(report_path)

    # Live-mode preconditions
    if write:
        if snapshot_dir is None:
            report.finished_at = _now()
            _write_report(report, report_path)
            return 2, report
        snapshot_path = take_snapshot(target_db, Path(snapshot_dir))
        report.snapshot = str(snapshot_path)
        _ensure_target_schema(target_db)

    # Read source
    legacy = read_legacy_charges(source_db)
    report.source_rows = len(legacy)
    if not legacy:
        report.finished_at = _now()
        _write_report(report, report_path)
        return 0, report

    # Classify + group
    groups: Dict[Tuple[str, str], List[LegacyCharge]] = {}
    for row in legacy:
        verdict, reason = classify_row(row)
        if verdict == "blocked":
            report.add_blocked(reason or "unknown", row)
            continue
        if verdict == "skipped_zero":
            report.skipped_zero += 1
            continue
        # Eligible — check idempotency BEFORE counting "to-create"
        existing = find_existing_backfill_charge(target_db, row.idempotency_sha1) if target_db.exists() else None
        if existing is not None:
            report.duplicate_skipped += 1
            continue
        report.eligible_rows += 1
        groups.setdefault((row.batch_id, row.client_name), []).append(row)

    # Synthesise posting metadata for the report
    for (batch_id, client_name), rows in groups.items():
        gk = GroupKey(batch_id=batch_id, client_name=client_name)
        synthetic_id = gk.synthetic_posting_id
        already = find_existing_synthetic_posting(target_db, synthetic_id) if target_db.exists() else None
        if already is None:
            report.postings_to_create += 1
        report.charges_to_create += len(rows)
        report.synthetic_postings.append({
            "batch_id":             batch_id,
            "client_name":          client_name,
            "synthetic_posting_id": synthetic_id,
            "charge_count":         len(rows),
            "currency":             rows[0].currency,
            "amount_total_minor":   sum(r.amount_minor for r in rows),
            "already_exists":       already is not None,
        })

    # Write phase
    if write:
        # Chunk by groups (each group = one transaction)
        for (batch_id, client_name), rows in groups.items():
            gk = GroupKey(batch_id=batch_id, client_name=client_name)
            for i in range(0, len(rows), chunk_size):
                sub = rows[i:i+chunk_size]
                p_n, c_n = insert_charges_chunk(target_db, gk, sub)
                report.postings_created += p_n
                report.charges_created  += c_n

    report.finished_at = _now()
    _write_report(report, report_path)

    exit_code = 0 if report.blocked_rows == 0 else 1
    return exit_code, report


def _write_report(report: BackfillReport, report_path: Path) -> None:
    report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = report_path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    tmp.replace(report_path)


# ── CLI ───────────────────────────────────────────────────────────────────

def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="backfill_finance_postings",
        description="Backfill legacy proforma_service_charges into the new "
                    "finance_postings schema. Default mode is dry-run; live "
                    "mode requires --write AND --snapshot-dir."
    )
    p.add_argument("--source-db", type=Path, required=True,
                    help="Path to legacy proforma_links.db")
    p.add_argument("--target-db", type=Path, required=True,
                    help="Path to finance_postings.sqlite")
    p.add_argument("--report-path", type=Path, required=True,
                    help="Where to write the JSON report")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true",
                       help="Read-only — report only; no writes")
    mode.add_argument("--write", action="store_true",
                       help="LIVE: insert rows into target DB. "
                            "Requires --snapshot-dir.")
    p.add_argument("--snapshot-dir", type=Path,
                    help="Required with --write. Target DB is copied here "
                         "before writes.")
    p.add_argument("--chunk-size", type=int, default=100,
                    help="Rows per transaction (default 100).")
    args = p.parse_args(argv)

    if args.write and args.snapshot_dir is None:
        print("ERROR: --write requires --snapshot-dir", file=sys.stderr)
        return 2

    rc, report = run_backfill(
        source_db=args.source_db,
        target_db=args.target_db,
        report_path=args.report_path,
        write=args.write,
        snapshot_dir=args.snapshot_dir,
        chunk_size=args.chunk_size,
    )
    print(f"Mode: {report.mode}")
    print(f"Source rows:       {report.source_rows}")
    print(f"Eligible:          {report.eligible_rows}")
    print(f"Blocked:           {report.blocked_rows}  reasons={report.blocked_reasons}")
    print(f"Skipped zero:      {report.skipped_zero}")
    print(f"Duplicate skipped: {report.duplicate_skipped}")
    print(f"Charges to create: {report.charges_to_create}")
    print(f"Postings to create:{report.postings_to_create}")
    if args.write:
        print(f"Charges created:  {report.charges_created}")
        print(f"Postings created: {report.postings_created}")
        print(f"Snapshot:         {report.snapshot}")
    print(f"Report:           {args.report_path}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
