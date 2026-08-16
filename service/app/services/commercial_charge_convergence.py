"""commercial_charge_convergence.py — the ONE charge-convergence capability.

Reads every ISSUED wFirma sales document in a window, attributes its insurance
line by canonical service identity, and records the billed amount in
``commercial_charge_record_db`` — the CommercialChargeAuthority's durable record
of what a fiscal document actually billed.

One shared ``run_charge_convergence()`` is reused by all three callers
(Business Feature Completeness Standard): the scheduler tick, the Business API
(`POST /api/v1/accounting/insurance-export/charge-convergence/run`), and the
operator's Run Now button. There is no second implementation.

Why it exists — measured 2026-08-16 over all 764 issued documents
(``reports/inspection/2026-08-16-insurance-recovered-authority-census.md``):
the authority was populated only by the draft → invoice conversion workflow, so
512 documents that bill insurance had no record at all, and 2 of the 14 that did
diverged from the issued document in both directions.

Safety (this is a financial-authority write path):
  * wFirma is READ-ONLY here — ``invoices/find`` only. Nothing is posted,
    edited or deleted. The proforma draft snapshot is never touched either.
  * Dry run is the DEFAULT. ``apply=True`` additionally requires
    ``settings.commercial_charge_convergence_apply_enabled`` — without it the
    write is REFUSED (fail-closed), never silently downgraded to a dry run.
  * Idempotent: re-running with identical evidence yields ``unchanged`` for
    every row and writes nothing.
  * A contradiction never overwrites — the stored value is kept and the row is
    flagged ``needs_manual_review`` (see ``commercial_charge_record_db``).
  * Attribution is by canonical service identity only, consumed from the
    Customer Master. A line that merely *reads* like insurance but carries an
    unknown ``good_id`` is reported unattributed and is NOT recorded — this
    capability never guesses an amount.
"""
from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.config import settings
from ..core.logging import get_logger
from . import commercial_charge_record_db as record_db
from .customer_master_db import CustomerMaster, get_customer

log = get_logger(__name__)

#: Issued sales documents. Proforma is deliberately excluded — it is not a
#: fiscal document and carries no recovered amount.
INVOICE_TYPES = ("normal", "correction")

#: Words that make a line LOOK like insurance. Used only to detect a line this
#: capability could not attribute by identity — never to record an amount.
INSURANCE_KEYWORDS = ("insurance", "ubezpieczenie")

#: Scheduler cooldown — a full re-read of the issued-document universe is a
#: wFirma-heavy scan, and nothing in it changes minute to minute.
DEFAULT_COOLDOWN_SECONDS = 6 * 3600

#: Scheduler window: recent documents only. Historical backfill is an explicit
#: operator run (never a startup or tick side effect).
DEFAULT_SCHEDULER_MONTHS = 2


class ChargeConvergenceWriteDenied(RuntimeError):
    """``apply=True`` requested while the write gate is off."""


# ── window ───────────────────────────────────────────────────────────────────


def resolve_window(
    months: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    today: Optional[date] = None,
) -> "tuple":
    today = today or date.today()
    if date_from and date_to:
        return date_from, date_to
    months = months or 1
    return (today - timedelta(days=int(months * 31))).isoformat(), today.isoformat()


# ── canonical identity (consumed from the Customer Master) ───────────────────


def insurance_service_id(
    contractor_id: str, master_db: Path, cache: Dict[str, str]
) -> str:
    """The customer's canonical wFirma insurance service id.

    Read from the Customer Master — the authority that owns the mapping — and
    falling back to the Master's own class default when the customer has no
    row. No module-local identity constant is introduced here.
    """
    cid = str(contractor_id or "").strip()
    if cid in cache:
        return cache[cid]
    sid = ""
    if cid:
        try:
            customer = get_customer(master_db, cid)
        except Exception:
            customer = None
        if customer is not None:
            sid = str(customer.insurance_service_id or "").strip()
    if not sid:
        sid = str(CustomerMaster.insurance_service_id or "").strip()
    cache[cid] = sid
    return sid


# ── wFirma read ──────────────────────────────────────────────────────────────


def fetch_invoices(invoice_type: str, page_size: int = 200) -> List[ET.Element]:
    """Every issued document of one type. Read-only.

    Live wFirma ignores the nested ``<page><start>…`` form and silently returns
    page 1 forever; only the sibling ``<page>N</page><limit>K</limit>`` form
    advances the cursor (``wfirma_client._wfirma_sibling_page_xml``). Dates are
    filtered in Python — the API's date-condition syntax is not stable across
    versions and a silently-empty window would look like "nothing to converge".
    """
    from . import wfirma_client as wfc

    out: List[ET.Element] = []
    page = 1
    while True:
        body = (
            '<?xml version="1.0" encoding="UTF-8"?>\n<api><invoices><parameters>'
            "<conditions><condition><field>type</field><operator>eq</operator>"
            "<value>%s</value></condition></conditions>"
            "%s</parameters></invoices></api>"
            % (invoice_type, wfc._wfirma_sibling_page_xml(page, page_size))
        )
        status, response = wfc._http_request("GET", "invoices", "find", body)
        if status >= 400:
            raise ConnectionError(
                "invoices/find HTTP %s (type=%s page=%s)" % (status, invoice_type, page)
            )
        got = ET.fromstring(response).findall("invoices/invoice")
        if not got:
            break
        out.extend(got)
        if len(got) < page_size:
            break
        page += 1
        if page > 100:
            raise RuntimeError("invoices/find exceeded 100 pages — refusing to loop")
    return out


def _dec(text: Any) -> Optional[Decimal]:
    try:
        return Decimal(str(text))
    except (InvalidOperation, ValueError, TypeError):
        return None


def read_insurance(inv: ET.Element, service_id: str) -> Dict[str, Any]:
    """What this document billed as insurance, by canonical identity.

    Returns ``{"amount", "good_id", "lines", "unattributed": [...]}``. Multiple
    insurance lines are summed; ``amount`` is Decimal("0") when the document
    bills none — which is a fact, not an absence.
    """
    total = Decimal("0")
    lines = 0
    unattributed: List[Dict[str, Any]] = []
    contents = inv.find("invoicecontents")
    for c in (contents.findall("invoicecontent") if contents is not None else []):
        name = (c.findtext("name") or "").strip()
        gid_el = c.find("good/id")
        gid = (gid_el.text or "").strip() if gid_el is not None else ""
        netto = _dec(c.findtext("netto"))
        if service_id and gid == service_id:
            total += netto if netto is not None else Decimal("0")
            lines += 1
        elif any(k in name.lower() for k in INSURANCE_KEYWORDS):
            unattributed.append({"name": name, "good_id": gid,
                                 "netto": str(netto) if netto is not None else None})
    return {"amount": total, "good_id": service_id, "lines": lines,
            "unattributed": unattributed}


# ── convergence ──────────────────────────────────────────────────────────────


def converge(
    date_from: str,
    date_to: str,
    apply: bool = False,
    record_path: Optional[Path] = None,
    master_db: Optional[Path] = None,
) -> Dict[str, Any]:
    """Read the window and (optionally) record it. The reconciliation artifact."""
    master_db = master_db or (Path(settings.storage_root) / "customer_master.db")
    cache: Dict[str, str] = {}

    documents: List[Dict[str, Any]] = []
    conflicts: List[Dict[str, Any]] = []
    unattributed: List[Dict[str, Any]] = []
    counts = {"scanned": 0, "in_window": 0, "inserted": 0, "unchanged": 0,
              "conflict": 0, "with_insurance": 0, "without_insurance": 0}
    billed: Dict[str, Decimal] = {}

    for itype in INVOICE_TYPES:
        for inv in fetch_invoices(itype):
            counts["scanned"] += 1
            doc_date = (inv.findtext("date") or "").strip()
            if not (date_from <= doc_date <= date_to):
                continue
            counts["in_window"] += 1

            invoice_id = (inv.findtext("id") or "").strip()
            currency = (inv.findtext("currency") or "").strip().upper()
            contractor_id = (inv.findtext("contractor_id") or "").strip()
            sid = insurance_service_id(contractor_id, master_db, cache)
            found = read_insurance(inv, sid)

            for u in found["unattributed"]:
                unattributed.append({"invoice_id": invoice_id,
                                     "number": (inv.findtext("fullnumber") or "").strip(),
                                     "date": doc_date, **u})

            document = {
                "invoice_id": invoice_id,
                "number": (inv.findtext("fullnumber") or "").strip(),
                "date": doc_date,
                "type": (inv.findtext("type") or itype).strip(),
                "currency": currency,
            }
            result = record_db.capture_document(
                document,
                {"insurance": {"amount": found["amount"], "good_id": found["good_id"]}},
                path=record_path,
                apply=apply,
            )
            action = result["actions"].get("insurance", "")
            counts[action] = counts.get(action, 0) + 1
            if found["amount"] > 0:
                counts["with_insurance"] += 1
                billed[currency] = billed.get(currency, Decimal("0")) + found["amount"]
            else:
                counts["without_insurance"] += 1
            conflicts.extend(result["conflicts"])
            documents.append({**document, "insurance_billed": str(found["amount"]),
                              "insurance_lines": found["lines"], "action": action})

    return {
        "mode": "apply" if apply else "dry_run",
        "window": {"from": date_from, "to": date_to},
        "counts": counts,
        "billed_insurance_by_currency": {k: str(v) for k, v in sorted(billed.items())},
        "conflicts": conflicts,
        "unattributed_insurance_lines": unattributed,
        "documents": sorted(documents, key=lambda d: (d["date"], d["number"])),
    }


# ── the ONE shared capability ────────────────────────────────────────────────


def run_charge_convergence(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    months: Optional[int] = None,
    apply: bool = False,
    operator: str = "operator",
    record_path: Optional[Path] = None,
    master_db: Optional[Path] = None,
) -> Dict[str, Any]:
    """Converge the charge authority against the issued documents in a window.

    ``apply=False`` (default) computes every decision and writes nothing.
    ``apply=True`` requires ``commercial_charge_convergence_apply_enabled``;
    without it :class:`ChargeConvergenceWriteDenied` is raised — the run is
    never silently downgraded to a dry run, because a caller that believes it
    converged and did not is exactly how a gap comes back.

    Returns the canonical status fields plus the reconciliation artifact.
    """
    if apply and not bool(getattr(settings, "commercial_charge_convergence_apply_enabled", False)):
        raise ChargeConvergenceWriteDenied(
            "COMMERCIAL_CHARGE_CONVERGENCE_APPLY_ENABLED is off — "
            "dry run is permitted, writing the charge record is not"
        )

    df, dt = resolve_window(months, date_from, date_to)
    started = time.time()
    if apply:
        record_db.mark_run_started(df, dt, operator, path=record_path)

    try:
        artifact = converge(df, dt, apply=apply, record_path=record_path,
                            master_db=master_db)
    except Exception as exc:
        log.error("charge-convergence failed (%s..%s): %s", df, dt, exc)
        summary = _summary(
            {"mode": "apply" if apply else "dry_run",
             "window": {"from": df, "to": dt},
             "counts": {"in_window": 0, "inserted": 0, "unchanged": 0, "conflict": 0},
             "billed_insurance_by_currency": {}, "conflicts": [],
             "unattributed_insurance_lines": [], "documents": []},
            started, errors=1, last_error=str(exc),
        )
        if apply:
            record_db.mark_run_completed(summary, path=record_path)
        raise ChargeConvergenceError(str(exc), summary) from exc

    summary = _summary(artifact, started)
    if apply:
        record_db.mark_run_completed(summary, path=record_path)
    log.info(
        "charge-convergence %s %s..%s processed=%s created=%s unchanged=%s conflicts=%s",
        summary["mode"], df, dt, summary["processed"], summary["created"],
        summary["skipped"], summary["conflicts"],
    )
    return summary


class ChargeConvergenceError(RuntimeError):
    """The run failed; ``.summary`` carries what was measured before it did."""

    def __init__(self, message: str, summary: Dict[str, Any]):
        super().__init__(message)
        self.summary = summary


def _summary(artifact: Dict[str, Any], started: float, errors: int = 0,
             last_error: str = "") -> Dict[str, Any]:
    counts = artifact.get("counts") or {}
    return {
        "mode": artifact.get("mode"),
        "window": artifact.get("window"),
        "processed": int(counts.get("in_window") or 0),
        "created": int(counts.get("inserted") or 0),
        "updated": 0,   # a stored record is never overwritten — see the record DB
        "skipped": int(counts.get("unchanged") or 0),
        "conflicts": int(counts.get("conflict") or 0),
        "unattributed": len(artifact.get("unattributed_insurance_lines") or []),
        "errors": errors,
        "last_error": last_error,
        "duration_ms": int((time.time() - started) * 1000),
        "billed_insurance_by_currency": artifact.get("billed_insurance_by_currency") or {},
        "artifact": artifact,
    }


def get_status(record_path: Optional[Path] = None) -> Dict[str, Any]:
    """Canonical status contract (``docs/patterns/status-endpoint.md``)."""
    status = record_db.get_run_status(path=record_path)
    status["apply_enabled"] = bool(
        getattr(settings, "commercial_charge_convergence_apply_enabled", False)
    )
    status["documents_on_record"] = record_db.count_documents(path=record_path)
    status["open_conflicts"] = len(record_db.list_conflicts(path=record_path))
    status["healthy"] = status["errors"] == 0 and status["open_conflicts"] == 0
    return status


def run_scheduler_tick(
    cooldown_seconds: int = DEFAULT_COOLDOWN_SECONDS,
    now: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """Automation entry point — the same shared function, on a cooldown.

    Runs only the recent window: historical backfill stays an explicit operator
    action. Returns ``None`` when there is nothing to do — which is the case
    when the apply gate is disarmed, and when the cooldown since the last run
    STARTED has not elapsed.

    A disarmed gate means no unattended run at all, not an unattended dry run:
    a dry pass would re-read the wFirma document universe on every tick and
    write nothing, and the gap it would measure is already disclosed on the
    statement itself as ``insurance_recovered_rows_without_authority``. The
    status endpoint reports ``apply_enabled`` so a disarmed automation is
    visible rather than merely quiet.
    """
    if not bool(getattr(settings, "commercial_charge_convergence_apply_enabled", False)):
        return None
    if not record_db.is_run_due(cooldown_seconds, now=now):
        return None
    try:
        return run_charge_convergence(
            months=DEFAULT_SCHEDULER_MONTHS, apply=True, operator="scheduler"
        )
    except ChargeConvergenceError as exc:
        return exc.summary


__all__ = [
    "ChargeConvergenceError",
    "ChargeConvergenceWriteDenied",
    "converge",
    "get_status",
    "resolve_window",
    "run_charge_convergence",
    "run_scheduler_tick",
]
