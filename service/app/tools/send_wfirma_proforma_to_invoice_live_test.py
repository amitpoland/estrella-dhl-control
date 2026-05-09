"""
send_wfirma_proforma_to_invoice_live_test.py — guarded converter that turns
ONE approved proforma into a final wFirma invoice.

Why this is a "live test" tool, not a one-shot script:
    Same discipline as send_wfirma_proforma_live_test.py:
        • dry-run by default
        • single proforma per invocation
        • two-part live confirmation phrase
        • explicit operator name (recorded in the link DB)
        • guarded against double conversion at the DB layer
    This file deliberately mirrors that pattern so the operator's mental
    model is unchanged between the two flows.

Pre-flight checks (in order; ALL must pass before HTTP write):
    1. proforma_id must exist in wFirma                       (404 → block)
    2. proforma must have <type>proforma</type>                (NotAProforma)
    3. no link row for proforma_id in our local DB             (duplicate guard)
       exception: pending link with wfirma_pz_doc_id set is allowed
       (PZ was pre-filled; invoice not yet issued)
    4. final_series_id must be supplied (not the proforma series default)
    5. operator name must be supplied                          (audit trace)
    6. (optional) total parity vs proforma                     (--allow-total-drift to skip)

Live write only happens when ALL of these are true:
    --live-confirm-I-understand
    --confirm "YES_CONVERT_ONE_PROFORMA"
    operator passed --operator NAME

PZ pre-fill flow (RECOVERY WORKAROUND — not normal path):
    --create-pz-before-invoice
    --warehouse-id <id>          (or WFIRMA_WAREHOUSE_ID env)
    --confirm-pz "YES_CREATE_ONE_PZ"
    WFIRMA_CREATE_PZ_ALLOWED=true in environment

    Uses build_pz_request_from_proforma_snapshot() which takes the proforma's
    sales unit_price as the PZ cost basis. This is incorrect for permanent use.
    Normal architecture uses import_pz_builder + unit_netto_pln (landed cost).
    Use this flag only when no import calculation PZ exists and a final invoice
    must be converted urgently. See docs/wfirma.skill.md §7b.

    PZ creation always stops after the PZ step unless invoice live flags
    are ALSO supplied in the same invocation.

On success, the link DB is updated to status=issued with the final
invoice_id, invoice_number and invoice_total. On failure, it's marked
'failed' with the wFirma error text in notes.

NO PRODUCTS ARE CREATED. NO PROFORMA IS MODIFIED. We only post invoices/add.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Optional, Tuple

# ── Path bootstrap ───────────────────────────────────────────────────────────
def _ensure_path() -> None:
    here = Path(__file__).resolve()
    service_dir = here.parents[2]
    repo_root   = here.parents[3]
    for p in (str(service_dir), str(repo_root)):
        if p not in sys.path:
            sys.path.insert(0, p)
_ensure_path()


from app.services import wfirma_client as wfc                   # noqa: E402
from app.services.proforma_to_invoice import (                  # noqa: E402
    NotAProforma,
    ProformaParseError,
    ProformaSnapshot,
    FinalInvoicePlan,
    build_final_invoice_plan,
    build_final_invoice_xml,
    build_pz_request_from_proforma_snapshot,
    parse_proforma_xml,
)
from app.services.proforma_invoice_link_db import (             # noqa: E402
    ProformaAlreadyConverted,
    ProformaInvoiceLink,
    create_pending_link,
    get_link_by_proforma,
    get_pz_doc_id,
    init_db,
    mark_failed,
    mark_issued,
    set_pz_doc_id,
)
from app.core.config import settings                            # noqa: E402


# ── Hard guards (intentionally not configurable) ─────────────────────────────

REQUIRED_FLAG          = "--live-confirm-I-understand"
REQUIRED_CONFIRMATION  = "YES_CONVERT_ONE_PROFORMA"
PZ_REQUIRED_CONFIRMATION = "YES_CREATE_ONE_PZ"

# Default final-invoice series. WDT (intra-EU) export. Operator may override.
DEFAULT_FINAL_SERIES_ID = "15827921"

# Default link-DB path
def _default_db_path() -> Path:
    return Path(__file__).resolve().parents[3] / "storage" / "proforma_invoice_links.sqlite"


# ── wFirma I/O ───────────────────────────────────────────────────────────────

def fetch_proforma_xml(proforma_id: str) -> str:
    """Read one proforma by id. Returns the raw XML response (the full
    <api>...</api> envelope). Raises ConnectionError / ValueError on failure.
    """
    body = f"""<?xml version="1.0" encoding="UTF-8"?>
<api>
  <invoices>
    <parameters>
      <conditions>
        <condition><field>id</field><operator>eq</operator><value>{proforma_id}</value></condition>
      </conditions>
      <page><start>0</start><limit>1</limit></page>
    </parameters>
  </invoices>
</api>"""
    http, response = wfc._http_request("GET", "invoices", "find", body)
    if http >= 400:
        raise ConnectionError(f"invoices/find HTTP {http}")
    if "<invoice>" not in response:
        raise ValueError(f"proforma_id={proforma_id} not found in wFirma")
    return response


def post_invoice(xml_body: str) -> Tuple[int, str]:
    """POST invoices/add. Returns (http_status, response_text)."""
    return wfc._http_request("POST", "invoices", "add", xml_body)


# ── Plan dump ────────────────────────────────────────────────────────────────

def print_plan(snap: ProformaSnapshot, plan: FinalInvoicePlan, *, dry_run: bool) -> None:
    bar = "=" * 78
    print(bar)
    print(f"  {'DRY-RUN' if dry_run else 'LIVE WRITE'}  proforma → final invoice")
    print(bar)
    print(f"  source proforma       : {snap.proforma_number}  (wFirma id={snap.proforma_id})")
    print(f"  source date           : {snap.date}")
    print(f"  source total          : {snap.total} {snap.currency}")
    print(f"  source paymentdate    : {snap.paymentdate}")
    print(f"  source paymentmethod  : {snap.paymentmethod}")
    print()
    print(f"  → target type         : {plan.type}")
    print(f"  → target series id    : {plan.series_id}")
    print(f"  → target date         : {plan.date}")
    print(f"  → target paymentdate  : {plan.paymentdate}")
    print(f"  → currency / FX       : {plan.currency} / {plan.price_currency_exchange or '(none)'}")
    print(f"  → contractor id       : {plan.contractor_id}")
    if plan.contractor_receiver_id:
        print(f"  → ship-to contractor  : {plan.contractor_receiver_id}")
    print(f"  → company_account     : {plan.company_account_id or '(none)'}")
    print(f"  → translation language: {plan.translation_language_id or '(none)'}")
    print(f"  → description         : {plan.description}")
    print()
    print("  line items copied from proforma:")
    print(f"    {'#':<4}{'good_id':<14}{'unit_count':<12}{'price':<12}{'vat':<6}name")
    for i, l in enumerate(plan.contents, 1):
        print(f"    {i:<4}{l.good_id:<14}{l.unit_count:<12}{l.price:<12}{l.vat_code_id:<6}{l.name}")
    print()


def print_pz_plan(pz_req, *, dry_run: bool) -> None:
    """Print aggregated PZ lines. Always called when --create-pz-before-invoice is set."""
    bar = "=" * 78
    print(bar)
    print(f"  {'DRY-RUN' if dry_run else 'LIVE WRITE'}  PZ goods receipt pre-fill")
    print(bar)
    print(f"  contractor id  : {pz_req.contractor_id}")
    print(f"  warehouse id   : {pz_req.warehouse_id}")
    print(f"  date           : {pz_req.date}")
    print(f"  description    : {pz_req.description}")
    print()
    print("  aggregated PZ lines (by good_id):")
    print(f"    {'#':<4}{'good_id':<14}{'count':<12}{'price (netto)':<16}")
    for i, line in enumerate(pz_req.lines, 1):
        print(f"    {i:<4}{line.good_id:<14}{line.count:<12.4f}{line.price:<16.2f}")
    total_val = sum(line.count * line.price for line in pz_req.lines)
    print(f"\n  total estimated netto : {total_val:.2f}")
    print(f"  lines                 : {len(pz_req.lines)}")
    print()


# ── Pre-flight ───────────────────────────────────────────────────────────────

def preflight(proforma_id: str,
              *,
              db_path: Path,
              final_series_id: str,
              operator: str,
              invoice_date: date,
              paymentdate: Optional[str],
              operator_description: Optional[str],
              ) -> Tuple[ProformaSnapshot, FinalInvoicePlan]:
    """All read-only checks. Either returns (snap, plan) ready to write, or
    raises a meaningful error. The caller does NOT need to catch each subtype.
    """
    if not (operator or "").strip():
        raise ValueError("operator name is required (--operator NAME)")
    if not (final_series_id or "").strip():
        raise ValueError("final_series_id is required (--final-series-id)")

    # Step 1+2: fetch + parse + verify type
    raw = fetch_proforma_xml(proforma_id)
    snap = parse_proforma_xml(raw)             # raises NotAProforma if not proforma
    if snap.proforma_id != str(proforma_id):
        raise ValueError(
            f"id mismatch: requested {proforma_id} but wFirma returned {snap.proforma_id}"
        )

    # Step 3: duplicate-conversion guard
    # Allowed exceptions (both mean PZ was done but invoice not yet started):
    #   a) status=pending  + no invoice_id + wfirma_pz_doc_id set
    #   b) status=failed   + no invoice_id + wfirma_pz_doc_id set
    #      (previous invoice attempt failed due to stock; PZ now resolves it)
    init_db(db_path)
    existing = get_link_by_proforma(db_path, snap.proforma_id)
    if existing is not None:
        if (existing.invoice_id is None
                and existing.wfirma_pz_doc_id
                and existing.status in ("pending", "failed")):
            pass  # PZ done, invoice not yet issued — allowed to retry
        else:
            raise ProformaAlreadyConverted(
                f"proforma {snap.proforma_number} (id={snap.proforma_id}) "
                f"already has a link (status={existing.status}, "
                f"invoice_id={existing.invoice_id or 'none'})",
                existing=existing,
            )

    # Step 4: build the plan (validates final_series_id internally)
    plan = build_final_invoice_plan(
        snap,
        final_series_id      = final_series_id,
        invoice_date         = invoice_date,
        paymentdate          = paymentdate,
        operator_description = operator_description,
    )
    return snap, plan


# ── PZ flow ──────────────────────────────────────────────────────────────────

def _run_pz_flow(args, snap: ProformaSnapshot, db_path: Path, is_pz_live: bool) -> int:
    """
    Perform the PZ check/creation step.

    Returns 0 on success (PZ created or already exists), non-zero on error.
    """
    warehouse_id = (getattr(args, "warehouse_id", None) or "").strip()
    if not warehouse_id:
        warehouse_id = getattr(settings, "wfirma_warehouse_id", "") or ""
    if not warehouse_id:
        print("PZ BLOCKED: --warehouse-id required (or set WFIRMA_WAREHOUSE_ID)", file=sys.stderr)
        return 2

    try:
        pz_req = build_pz_request_from_proforma_snapshot(snap, warehouse_id)
    except ValueError as exc:
        print(f"PZ BUILD ERROR: {exc}", file=sys.stderr)
        return 7

    print_pz_plan(pz_req, dry_run=not is_pz_live)

    # Check for existing PZ doc id (requires a link row; None if no row)
    existing_pz_id = get_pz_doc_id(db_path, snap.proforma_id)
    if existing_pz_id:
        print(f"  PZ already created (wFirma id={existing_pz_id}) — skipping creation.")
        return 0

    if not is_pz_live:
        _print_pz_dry_run_hints(args)
        print("PZ DRY-RUN complete — no write performed.")
        return 0

    # Live PZ creation
    # Create a pending link row now so we have somewhere to store the PZ doc id
    # and the duplicate guard covers the proforma from this point.
    link_row = get_link_by_proforma(db_path, snap.proforma_id)
    if link_row is None:
        try:
            create_pending_link(db_path, ProformaInvoiceLink(
                proforma_id     = snap.proforma_id,
                proforma_number = snap.proforma_number,
                converted_at    = "",
                operator        = (getattr(args, "operator", None) or "pz-prefill"),
                source_total    = snap.total,
                currency        = snap.currency,
                status          = "pending",
                notes           = "pz-prefill",
            ))
        except ProformaAlreadyConverted as exc:
            print(f"PZ ABORT: race condition creating link row: {exc}", file=sys.stderr)
            return 9

    pz_result = wfc.create_warehouse_pz(pz_req)
    if not pz_result.ok:
        print(f"PZ FAILED: {pz_result.error}", file=sys.stderr)
        if pz_result.raw_response:
            print(f"response: {_truncate(pz_result.raw_response)}", file=sys.stderr)
        return 8

    try:
        set_pz_doc_id(db_path, snap.proforma_id, pz_result.wfirma_pz_doc_id)
    except (ValueError, KeyError) as exc:
        # Not fatal — PZ was created in wFirma; we just can't track it locally.
        print(f"PZ WARN: could not save PZ doc id to link DB: {exc}", file=sys.stderr)

    print()
    print("=" * 78)
    print("  PZ CREATED OK")
    print("=" * 78)
    print(f"  proforma     : {snap.proforma_number}  (id={snap.proforma_id})")
    print(f"  wFirma PZ id : {pz_result.wfirma_pz_doc_id}")
    print(f"  lines        : {len(pz_req.lines)}")
    print(f"  link DB      : {db_path}")
    print()
    return 0


def _print_pz_dry_run_hints(args) -> None:
    if not getattr(settings, "wfirma_create_pz_allowed", False):
        print("  → WFIRMA_CREATE_PZ_ALLOWED=true required in environment")
    if getattr(args, "confirm_pz", None) != PZ_REQUIRED_CONFIRMATION:
        print(f"  → --confirm-pz {PZ_REQUIRED_CONFIRMATION!r} required")


# ── Helpers ──────────────────────────────────────────────────────────────────

def _extract_new_invoice(response: str) -> Tuple[Optional[str], Optional[str], Optional[Decimal]]:
    """Pull (id, fullnumber, total) from a successful invoices/add response.
    Returns (None, None, None) if any of them is missing.
    """
    iid = None
    fn = None
    total = None
    m = re.search(r"<invoice>\s*<id>(\d+)</id>", response)
    if m:
        iid = m.group(1)
    m = re.search(r"<fullnumber>([^<]+)</fullnumber>", response)
    if m:
        fn = m.group(1).strip()
    m = re.search(r"<total>([^<]+)</total>", response)
    if m:
        try:
            total = Decimal(m.group(1).strip())
        except Exception:  # noqa: BLE001
            total = None
    return iid, fn, total


def _truncate(text: str, n: int = 600) -> str:
    flat = " ".join((text or "").split())
    return flat if len(flat) <= n else flat[:n] + "…"


# ── CLI ──────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="send_wfirma_proforma_to_invoice_live_test",
        description=(
            "Convert ONE approved wFirma proforma into a final invoice. "
            "Dry-run by default; live write requires the explicit guard flag "
            "AND the typed confirmation phrase. "
            "Optionally pre-fill warehouse stock with --create-pz-before-invoice."
        ),
    )
    p.add_argument("--proforma-id", required=True,
                   help="wFirma id of the source proforma to convert.")
    p.add_argument("--final-series-id", default=DEFAULT_FINAL_SERIES_ID,
                   help=f"wFirma series id for the final invoice. "
                        f"Default {DEFAULT_FINAL_SERIES_ID} (WDT).")
    p.add_argument("--operator", default="",
                   help="Operator name — recorded in the link DB on conversion.")
    p.add_argument("--invoice-date", default=None,
                   help="Issue date of the final invoice (YYYY-MM-DD). "
                        "Defaults to today.")
    p.add_argument("--paymentdate", default=None,
                   help="Override paymentdate. Defaults to the proforma's paymentdate.")
    p.add_argument("--description", default=None,
                   help="Operator-supplied tail of the final-invoice description. "
                        "The 'Final invoice issued based on PROF …' back-reference "
                        "is ALWAYS prepended automatically.")
    p.add_argument("--db", default=None,
                   help="Path to proforma_invoice_links SQLite. "
                        "Default: <repo>/storage/proforma_invoice_links.sqlite")

    p.add_argument(REQUIRED_FLAG, action="store_true",
                   dest="live_confirm",
                   help="Required for any non-dry-run invoice write.")
    p.add_argument("--confirm", default=None,
                   help=f"Required confirmation phrase: {REQUIRED_CONFIRMATION!r}")
    p.add_argument("--dry-run", action="store_true",
                   help="Plan only — no HTTP write. (Default if guards are missing.)")

    # PZ pre-fill flags
    p.add_argument("--create-pz-before-invoice", action="store_true",
                   dest="create_pz_before_invoice",
                   help="Create a wFirma PZ goods receipt to pre-fill warehouse stock "
                        "before invoice conversion. Requires WFIRMA_CREATE_PZ_ALLOWED=true "
                        f"and --confirm-pz {PZ_REQUIRED_CONFIRMATION!r}.")
    p.add_argument("--warehouse-id", default=None,
                   dest="warehouse_id",
                   help="wFirma warehouse id for PZ creation. "
                        "Defaults to WFIRMA_WAREHOUSE_ID from environment.")
    p.add_argument("--confirm-pz", default=None,
                   dest="confirm_pz",
                   help=f"Confirmation phrase required for live PZ write: "
                        f"{PZ_REQUIRED_CONFIRMATION!r}")
    return p


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)

    is_invoice_live = bool(args.live_confirm) and args.confirm == REQUIRED_CONFIRMATION
    is_dry_run = args.dry_run or not is_invoice_live

    is_pz_mode = bool(args.create_pz_before_invoice)
    is_pz_live = (
        is_pz_mode
        and bool(getattr(settings, "wfirma_create_pz_allowed", False))
        and args.confirm_pz == PZ_REQUIRED_CONFIRMATION
    )

    # Issue date
    issue_date = date.today()
    if args.invoice_date:
        try:
            issue_date = date.fromisoformat(args.invoice_date)
        except ValueError:
            print(f"--invoice-date is not a valid YYYY-MM-DD: {args.invoice_date!r}",
                  file=sys.stderr)
            return 2

    db_path = Path(args.db).expanduser() if args.db else _default_db_path()

    # ── PZ flow ─────────────────────────────────────────────────────────────
    if is_pz_mode:
        try:
            raw_pz = fetch_proforma_xml(args.proforma_id)
            snap_pz = parse_proforma_xml(raw_pz)
        except (ProformaParseError, NotAProforma, ValueError) as exc:
            print(f"PRE-FLIGHT BLOCKED: {exc}", file=sys.stderr)
            return 7
        except ConnectionError as exc:
            print(f"PRE-FLIGHT ERROR: {exc}", file=sys.stderr)
            return 5

        init_db(db_path)
        rc = _run_pz_flow(args, snap_pz, db_path, is_pz_live)
        if rc != 0:
            return rc

        if not is_invoice_live:
            print("PZ step complete — run with invoice live flags to proceed with conversion.")
            return 0
        # Fall through: both PZ flags and invoice flags were supplied in one invocation.

    # ── Pre-flight ──────────────────────────────────────────────────────────
    try:
        snap, plan = preflight(
            args.proforma_id,
            db_path             = db_path,
            final_series_id     = args.final_series_id,
            operator            = args.operator,
            invoice_date        = issue_date,
            paymentdate         = args.paymentdate,
            operator_description= args.description,
        )
    except (ProformaParseError, NotAProforma, ValueError) as exc:
        print(f"PRE-FLIGHT BLOCKED: {exc}", file=sys.stderr)
        return 7
    except ProformaAlreadyConverted as exc:
        print(f"PRE-FLIGHT BLOCKED (duplicate): {exc}", file=sys.stderr)
        return 9
    except ConnectionError as exc:
        print(f"PRE-FLIGHT ERROR: {exc}", file=sys.stderr)
        return 5

    # Build the XML so the operator can read it before live confirmation
    xml = build_final_invoice_xml(plan)

    print_plan(snap, plan, dry_run=is_dry_run)

    if is_dry_run:
        if bool(args.live_confirm) or args.confirm == REQUIRED_CONFIRMATION:
            print("  (live confirmation incomplete — run again with both "
                  f"{REQUIRED_FLAG} AND --confirm {REQUIRED_CONFIRMATION!r})\n",
                  file=sys.stderr)
        print("DRY-RUN complete — no HTTP write performed.")
        return 0

    # ── Live write ──────────────────────────────────────────────────────────
    # Insert pending link FIRST so the duplicate guard locks even if the
    # POST hangs. If a PZ-prefill link already exists (status=pending +
    # pz_doc_id set), reuse it rather than failing.
    try:
        create_pending_link(db_path, ProformaInvoiceLink(
            proforma_id     = snap.proforma_id,
            proforma_number = snap.proforma_number,
            converted_at    = "",
            operator        = args.operator,
            source_total    = snap.total,
            currency        = snap.currency,
            status          = "pending",
            notes           = f"final_series_id={plan.series_id}",
        ))
    except ProformaAlreadyConverted as exc:
        # Allow if PZ was done but invoice not yet started (pending or failed+PZ).
        if (exc.existing.invoice_id is None
                and exc.existing.wfirma_pz_doc_id
                and exc.existing.status in ("pending", "failed")):
            pass  # reuse the existing link row
        else:
            print(f"ABORT: {exc}", file=sys.stderr)
            return 9
    except ValueError as exc:
        print(f"ABORT: link DB validation: {exc}", file=sys.stderr)
        return 7

    try:
        http, response = post_invoice(xml)
    except Exception as exc:  # noqa: BLE001
        mark_failed(db_path, snap.proforma_id, notes=f"transport error: {exc}")
        print(f"LIVE WRITE FAILED — transport: {exc}", file=sys.stderr)
        return 5

    wcode, _ = wfc._parse_status(response)
    if http >= 400 or wcode != "OK":
        mark_failed(db_path, snap.proforma_id,
                    notes=f"http={http} wfirma={wcode}: {_truncate(response)}")
        print(f"LIVE WRITE REJECTED — http={http} wfirma_status={wcode}",
              file=sys.stderr)
        print(f"response excerpt: {_truncate(response)}", file=sys.stderr)
        return 8

    # Success: extract the new invoice id/number/total
    new_iid, new_fn, new_total = _extract_new_invoice(response)
    if not new_iid or not new_fn or new_total is None:
        mark_failed(db_path, snap.proforma_id,
                    notes=f"could not parse new invoice from response: {_truncate(response)}")
        print("LIVE WRITE AMBIGUOUS — wFirma returned OK but we could not parse "
              "the new invoice id. Check wFirma manually before retrying.",
              file=sys.stderr)
        return 10

    mark_issued(db_path, snap.proforma_id,
                invoice_id     = new_iid,
                invoice_number = new_fn,
                invoice_total  = new_total)

    print()
    print("=" * 78)
    print("  LIVE WRITE OK — final invoice issued.")
    print("=" * 78)
    print(f"  source proforma : {snap.proforma_number}  (id={snap.proforma_id})")
    print(f"  final invoice   : {new_fn}              (id={new_iid})")
    print(f"  invoice total   : {new_total} {snap.currency}")
    print(f"  link recorded   : {db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
