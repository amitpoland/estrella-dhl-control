"""
sync_customer_invoice_snapshot.py — fetch wFirma sales invoices into local DB.

Reads sales invoices from wFirma (type=normal + type=correction) within a date
window, stores headers + lines locally, and regenerates per-customer commercial
profiles. Excludes proformas, PZ, purchase docs.

Read-only on wFirma. Writes only to a local SQLite DB.

Idempotency:
  - invoice_id is the upsert key. Re-running updates changed invoices.
  - Lines for an updated invoice are replaced in full (delete + insert).
  - Profiles are recomputed from the DB content after sync.

Usage:
    python3 -m app.tools.sync_customer_invoice_snapshot --months 6
    python3 -m app.tools.sync_customer_invoice_snapshot --from 2025-11-03 --to 2026-05-03
    python3 -m app.tools.sync_customer_invoice_snapshot --dry-run
    python3 -m app.tools.sync_customer_invoice_snapshot --only 38582303
    python3 -m app.tools.sync_customer_invoice_snapshot --db /path/to.sqlite
"""
from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple


def _bootstrap() -> None:
    here = Path(__file__).resolve()
    repo_root = here.parents[3]
    service_dir = here.parents[2]
    for p in (str(repo_root), str(service_dir)):
        if p not in sys.path:
            sys.path.insert(0, p)


_bootstrap()

from app.services.customer_invoice_snapshot_db import (   # noqa: E402
    InvoiceLineRow, InvoiceSnapshotRow, ProfileSnapshotRow,
    init_db, list_distinct_contractors, list_invoices,
    upsert_invoice_with_lines, upsert_profile,
)


# ── Constants (line classification) ───────────────────────────────────────────

FREIGHT_SERVICE_ID    = "13002743"
INSURANCE_SERVICE_ID  = "13102217"
FREIGHT_KEYWORDS      = ("fedex", "freight", "fracht", "courier", "dhl",
                          "transport", "shipping", "shipment", "postage")
INSURANCE_KEYWORDS    = ("insurance", "ubezpieczenie")

# Document types we sync from wFirma. Proforma is intentionally EXCLUDED.
INVOICE_TYPES_SYNCED  = ("normal", "correction")

# Profile thresholds
RECENT_WINDOW_MONTHS  = 12
FREIGHT_RECENT_N      = 5
INSURANCE_RATE        = Decimal("0.0035")
INSURANCE_RATE_TOL    = Decimal("0.0002")
INSURANCE_FORMULA_FRACTION_THRESHOLD = Decimal("0.80")


# ── Confidence states ────────────────────────────────────────────────────────

CONF_EMPTY              = "EMPTY"
CONF_SINGLE_DOC         = "SINGLE_DOC"
CONF_STALE_LOW          = "STALE_LOW"
CONF_CONSISTENT_RECENT  = "CONSISTENT_RECENT"
CONF_VARYING            = "VARYING"


# ── Reporting ────────────────────────────────────────────────────────────────

@dataclass
class SyncSummary:
    period_from:        str
    period_to:          str
    fetched:            int = 0
    inserted:           int = 0
    updated:            int = 0
    skipped_proforma:   int = 0
    skipped_no_export:  int = 0   # invoices outside window or wrong type
    profiles_built:     int = 0
    errors:             int = 0


# ── Date window resolution ───────────────────────────────────────────────────

def resolve_window(months:    Optional[int] = None,
                   date_from: Optional[str] = None,
                   date_to:   Optional[str] = None,
                   today:     Optional[date] = None) -> Tuple[str, str]:
    """Return (from_iso, to_iso). Either months or both date_from + date_to.

    months=N (and no explicit dates) → window = [today - N*31, today]
    """
    today = today or date.today()
    if date_from and date_to:
        return date_from, date_to
    if months is None:
        months = 6
    if months <= 0:
        raise ValueError(f"months must be > 0, got {months}")
    start = today - timedelta(days=int(months * 31))
    return start.isoformat(), today.isoformat()


# ── wFirma fetcher (live; injectable) ────────────────────────────────────────

def fetch_invoices_from_wfirma(invoice_type: str,
                                date_from:    str,
                                date_to:      str,
                                only_ids:     Optional[List[str]] = None,
                                page_size:    int = 200) -> List[ET.Element]:
    """Fetch invoices of the given type from wFirma. Returns parsed <invoice>
    Elements. Read-only. The returned list is not date-filtered (wFirma can
    return outside-window docs because the API filter syntax for dates is
    fragile across versions); the CALLER filters in Python."""
    from app.services import wfirma_client as wfc

    base_conditions = (
        f"<condition><field>type</field><operator>eq</operator><value>{invoice_type}</value></condition>"
    )
    only_conditions = ""
    if only_ids:
        only_conditions = "".join(
            f"<condition><field>contractor_id</field><operator>eq</operator><value>{cid}</value></condition>"
            for cid in only_ids
        )

    out: List[ET.Element] = []
    start = 0
    while True:
        body = f"""<?xml version="1.0" encoding="UTF-8"?>
<api>
  <invoices>
    <parameters>
      <conditions>
        {base_conditions}
        {only_conditions}
      </conditions>
      <page><start>{start}</start><limit>{page_size}</limit></page>
    </parameters>
  </invoices>
</api>"""
        http_status, response = wfc._http_request("GET", "invoices", "find", body)
        if http_status >= 400:
            raise ConnectionError(f"invoices/find HTTP {http_status} (start={start})")
        try:
            root = ET.fromstring(response)
        except ET.ParseError:
            break
        invoices = root.findall("invoices/invoice")
        if not invoices:
            break
        out.extend(invoices)
        if len(invoices) < page_size:
            break
        start += page_size
        if start > 5000:
            # safety: never iterate forever
            break
    return out


# ── Line classifier ──────────────────────────────────────────────────────────

def classify_line(name: str, good_id: str) -> str:
    n = (name or "").lower()
    if any(k in n for k in INSURANCE_KEYWORDS) or good_id == INSURANCE_SERVICE_ID:
        return "insurance"
    if any(k in n for k in FREIGHT_KEYWORDS) or good_id == FREIGHT_SERVICE_ID:
        return "freight"
    # Heuristic for product detection — jewellery keywords (Polish + English)
    jewelry = ("jewel", "gold", "silver", "diamond", "ring", "pendant",
               "earring", "bracelet", "pierścion", "pierscion", "wisior",
               "kolczyk", "srebr", "złot", "zlot", "platyn", "ejl/")
    if any(k in n for k in jewelry):
        return "product"
    return "service"


# ── Parse one wFirma <invoice> element → InvoiceSnapshotRow ──────────────────

def parse_invoice_element(inv: ET.Element) -> Optional[InvoiceSnapshotRow]:
    invid = inv.findtext("id") or ""
    if not invid:
        return None

    cd = inv.find("contractor_detail")
    cd_country = inv.find("contractor_detail/country")
    cd_name    = inv.find("contractor_detail/name")
    cd_nip     = inv.find("contractor_detail/nip")

    contractor_id_el = inv.find("contractor/id")
    contractor_id = contractor_id_el.text if contractor_id_el is not None and contractor_id_el.text else ""
    if not contractor_id:
        return None

    lang_el  = inv.find("translation_language/id")
    series_el = inv.find("series/id")
    rcv_el    = inv.find("contractor_receiver/id")

    contents = inv.find("invoicecontents")
    line_rows: List[InvoiceLineRow] = []
    vat_codes_set: set = set()
    if contents is not None:
        for c in contents.findall("invoicecontent"):
            name = c.findtext("name") or ""
            gid_el = c.find("good/id")
            gid = gid_el.text if gid_el is not None and gid_el.text else ""
            try:
                qty   = Decimal(c.findtext("unit_count") or "0")
                price = Decimal(c.findtext("price")      or "0")
            except Exception:
                qty, price = Decimal("0"), Decimal("0")
            net_el   = c.findtext("netto")
            gross_el = c.findtext("brutto")
            try:
                net   = Decimal(net_el)   if net_el   else (qty * price).quantize(Decimal("0.01"))
                gross = Decimal(gross_el) if gross_el else None
            except Exception:
                net, gross = None, None
            vc_el = c.find("vat_code/id")
            vc = vc_el.text if vc_el is not None and vc_el.text else ""
            if vc:
                vat_codes_set.add(vc)
            unit_el = c.find("unit/id")
            unit_text = c.findtext("unit") or ""
            if unit_el is not None and unit_el.text:
                unit_text = unit_el.text   # prefer id form when present

            kind = classify_line(name, gid)
            line_rows.append(InvoiceLineRow(
                line_type    = kind,
                good_id      = gid or None,
                product_code = None,   # not returned at line level
                name         = name or None,
                qty          = qty,
                unit         = unit_text or None,
                price        = price,
                vat_code_id  = vc or None,
                line_net     = net,
                line_gross   = gross,
            ))

    # Determine "type" the way our DB tracks: invoice_type matches what we synced,
    # but if the response is an actual correction we keep that.
    raw_type = inv.findtext("type") or ""
    # wFirma returns <type> values like "FAKTURA", "WDT", "EXPORT", "PROFORMA",
    # "KOREKTA". For our DB:
    #   PROFORMA → skip in caller
    #   KOREKTA  → "correction"
    #   else      → "normal"
    if raw_type.upper().startswith("KOREKT") or raw_type.upper() == "FAKTURA KORYGUJĄCA":
        invoice_type = "correction"
    elif raw_type.upper().startswith("PROFORM"):
        invoice_type = "proforma"
    else:
        invoice_type = "normal"

    return InvoiceSnapshotRow(
        invoice_id              = invid,
        contractor_id           = contractor_id,
        contractor_name         = (cd_name.text if cd_name is not None and cd_name.text else None),
        country                 = (cd_country.text if cd_country is not None and cd_country.text else None),
        nip                     = (cd_nip.text if cd_nip is not None and cd_nip.text else None),
        invoice_number          = inv.findtext("fullnumber") or None,
        invoice_type            = invoice_type,
        invoice_date            = inv.findtext("date") or None,
        currency                = inv.findtext("currency") or None,
        series_id               = series_el.text if series_el is not None and series_el.text else None,
        translation_language_id = lang_el.text   if lang_el   is not None and lang_el.text   else None,
        vat_codes_used          = ",".join(sorted(vat_codes_set)) if vat_codes_set else None,
        contractor_receiver_id  = rcv_el.text if rcv_el is not None and rcv_el.text else "0",
        description             = (inv.findtext("description") or "").strip() or None,
        total_net               = _safe_decimal(inv.findtext("netto")),
        total_gross             = _safe_decimal(inv.findtext("brutto")),
        lines                   = tuple(line_rows),
    )


def _safe_decimal(s) -> Optional[Decimal]:
    try:
        return Decimal(s) if s else None
    except Exception:
        return None


# ── Profile builder from DB content ──────────────────────────────────────────

def build_profile_for_contractor(db_path:    Path,
                                 contractor_id: str,
                                 period_from:   str,
                                 period_to:     str) -> ProfileSnapshotRow:
    """Reads back invoices for this contractor and computes a profile."""
    invoices = list_invoices(db_path,
                             contractor_id = contractor_id,
                             invoice_type  = "normal",
                             date_from     = period_from,
                             date_to       = period_to)
    return _compute_profile(contractor_id, period_from, period_to, invoices)


def _compute_profile(contractor_id: str,
                     period_from:   str,
                     period_to:     str,
                     invoices:      List[InvoiceSnapshotRow]) -> ProfileSnapshotRow:
    if not invoices:
        return ProfileSnapshotRow(
            contractor_id    = contractor_id,
            period_from      = period_from,
            period_to        = period_to,
            invoice_count    = 0,
            confidence_state = CONF_EMPTY,
        )

    # Aggregate
    currencies = {i.currency for i in invoices if i.currency}
    languages  = {i.translation_language_id for i in invoices if i.translation_language_id}
    vat_codes  = set()
    for i in invoices:
        if i.vat_codes_used:
            for v in i.vat_codes_used.split(","):
                if v: vat_codes.add(v)
    series_ids = {i.series_id for i in invoices if i.series_id}

    pref_currency = next(iter(currencies)) if len(currencies) == 1 else None
    pref_language = next(iter(languages))  if len(languages) == 1 else None
    pref_series   = next(iter(series_ids)) if len(series_ids) == 1 else None
    vat_mode      = (228 if vat_codes == {"228"} else
                     229 if vat_codes == {"229"} else
                     None)

    # Freight / insurance from line table
    freight_history: List[Decimal] = []
    insurance_pairs: List[Tuple[Decimal, Decimal]] = []   # (subtotal, insurance)
    receiver_nonzero = False
    for inv in invoices:
        product_subtotal = Decimal("0")
        freight_in_inv = None
        insurance_in_inv = None
        for ln in inv.lines:
            if ln.line_type == "product" and ln.qty is not None and ln.price is not None:
                product_subtotal += (ln.qty * ln.price)
            elif ln.line_type == "freight" and ln.price is not None and freight_in_inv is None:
                freight_in_inv = ln.price
            elif ln.line_type == "insurance" and ln.price is not None and insurance_in_inv is None:
                insurance_in_inv = ln.price
        if freight_in_inv is not None:
            freight_history.append(freight_in_inv)
        if insurance_in_inv is not None and product_subtotal > 0:
            insurance_pairs.append((product_subtotal.quantize(Decimal("0.01")), insurance_in_inv))
        if inv.contractor_receiver_id and inv.contractor_receiver_id != "0":
            receiver_nonzero = True

    # Freight detection
    last_freight = freight_history[0] if freight_history else None
    freight_mode = "no_data"
    avg_freight = None
    if freight_history:
        recent = freight_history[:FREIGHT_RECENT_N]
        if all(h == recent[0] for h in recent):
            freight_mode = "fixed"
        else:
            freight_mode = "variable"
        # avg over all freight values seen
        avg_freight = (sum(freight_history) / Decimal(len(freight_history))).quantize(Decimal("0.01"))

    # Insurance detection
    insurance_mode = "no_data"
    insurance_min  = None
    if insurance_pairs:
        formula_hits = sum(
            1 for sub, ins in insurance_pairs
            if sub > 0 and abs((ins / sub) - INSURANCE_RATE) <= INSURANCE_RATE_TOL
        )
        fraction = Decimal(formula_hits) / Decimal(len(insurance_pairs))
        insurance_min = min(ins for _, ins in insurance_pairs)
        insurance_mode = "formula" if fraction >= INSURANCE_FORMULA_FRACTION_THRESHOLD else "fixed"

    # Confidence
    most_recent = invoices[0].invoice_date or ""
    if len(invoices) == 1:
        state = CONF_SINGLE_DOC
    elif not _is_recent(most_recent):
        state = CONF_STALE_LOW
    else:
        all_consistent = bool(pref_currency and pref_language and vat_mode is not None)
        state = CONF_CONSISTENT_RECENT if all_consistent else CONF_VARYING

    ship_to = "separate_contractor" if receiver_nonzero else "none"

    return ProfileSnapshotRow(
        contractor_id               = contractor_id,
        period_from                 = period_from,
        period_to                   = period_to,
        invoice_count               = len(invoices),
        preferred_currency          = pref_currency,
        preferred_language_id       = pref_language,
        preferred_invoice_series_id = pref_series,
        vat_mode                    = vat_mode,
        last_freight_amount         = last_freight,
        avg_freight_amount          = avg_freight,
        freight_mode                = freight_mode,
        insurance_min_detected      = insurance_min,
        insurance_mode              = insurance_mode,
        ship_to_mode                = ship_to,
        confidence_state            = state,
    )


def _is_recent(iso_date: str) -> bool:
    try:
        d = date.fromisoformat(iso_date)
    except (ValueError, TypeError):
        return False
    return (date.today() - d).days <= RECENT_WINDOW_MONTHS * 31


# ── Sync orchestrator ────────────────────────────────────────────────────────

def sync(db_path:        Path,
         period_from:    str,
         period_to:      str,
         *,
         only_ids:       Optional[List[str]] = None,
         dry_run:        bool = False,
         fetcher:        Optional[Callable] = None) -> SyncSummary:
    """End-to-end sync: fetch normal + correction invoices, store, build profiles."""
    init_db(db_path)
    summary = SyncSummary(period_from=period_from, period_to=period_to)
    do_fetch = fetcher or fetch_invoices_from_wfirma

    all_parsed: List[InvoiceSnapshotRow] = []
    for inv_type in INVOICE_TYPES_SYNCED:
        try:
            invs = do_fetch(inv_type, period_from, period_to, only_ids=only_ids)
        except (ConnectionError, ValueError) as exc:
            summary.errors += 1
            print(f"[sync] fetch error for type={inv_type}: {exc}", file=sys.stderr)
            continue

        for inv_el in invs:
            summary.fetched += 1
            row = parse_invoice_element(inv_el)
            if row is None:
                summary.errors += 1
                continue
            # Filter
            if row.invoice_type == "proforma":
                summary.skipped_proforma += 1
                continue
            if not row.invoice_date or row.invoice_date < period_from or row.invoice_date > period_to:
                summary.skipped_no_export += 1
                continue
            all_parsed.append(row)

    # Persist invoice headers + lines
    if not dry_run:
        for row in all_parsed:
            existed = (
                __import__("app.services.customer_invoice_snapshot_db",
                           fromlist=["get_invoice_by_invoice_id"])
                .get_invoice_by_invoice_id(db_path, row.invoice_id)
                is not None
            )
            upsert_invoice_with_lines(db_path, row)
            if existed:
                summary.updated += 1
            else:
                summary.inserted += 1
    else:
        summary.inserted = len(all_parsed)   # would-have-inserted

    # Build profiles per contractor
    if not dry_run:
        contractors = list_distinct_contractors(db_path,
                                                invoice_type="normal",
                                                date_from=period_from,
                                                date_to=period_to)
        if only_ids:
            contractors = [c for c in contractors if c in only_ids]
        for cid in contractors:
            try:
                p = build_profile_for_contractor(db_path, cid, period_from, period_to)
                upsert_profile(db_path, p)
                summary.profiles_built += 1
            except Exception as exc:  # noqa: BLE001
                summary.errors += 1
                print(f"[sync] profile error for contractor={cid}: {exc}", file=sys.stderr)

    return summary


# ── CLI ───────────────────────────────────────────────────────────────────────

def _print_summary(s: SyncSummary, *, dry_run: bool) -> None:
    print("=" * 76)
    print(f" customer invoice snapshot sync — {'DRY-RUN' if dry_run else 'LIVE WRITE'}")
    print("=" * 76)
    print(f"  window           : {s.period_from} … {s.period_to}")
    print(f"  fetched          : {s.fetched}")
    print(f"  inserted         : {s.inserted}")
    print(f"  updated          : {s.updated}")
    print(f"  skipped_proforma : {s.skipped_proforma}")
    print(f"  skipped (out of window / type) : {s.skipped_no_export}")
    print(f"  profiles built   : {s.profiles_built}")
    print(f"  errors           : {s.errors}")
    print()


def main(argv:    Optional[List[str]] = None,
         fetcher: Optional[Callable] = None) -> int:
    p = argparse.ArgumentParser(prog="sync_customer_invoice_snapshot")
    p.add_argument("--db", default=None,
                   help="DB path. Default: <repo>/storage/customer_invoice_snapshot.sqlite")
    p.add_argument("--months",  type=int, default=None,
                   help="N months back from today (default 6 if no --from/--to)")
    p.add_argument("--from",    dest="date_from", default=None, help="ISO YYYY-MM-DD")
    p.add_argument("--to",      dest="date_to",   default=None, help="ISO YYYY-MM-DD")
    p.add_argument("--only",    default=None,
                   help="Comma-separated contractor ids — restrict sync")
    p.add_argument("--dry-run", action="store_true", help="Don't write to DB")
    args = p.parse_args(argv)

    if args.db:
        db_path = Path(args.db).expanduser()
    else:
        db_path = Path(__file__).resolve().parents[3] / "storage" / "customer_invoice_snapshot.sqlite"

    try:
        period_from, period_to = resolve_window(
            months=args.months, date_from=args.date_from, date_to=args.date_to,
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    only_ids = None
    if args.only:
        only_ids = [s.strip() for s in args.only.split(",") if s.strip()]

    summary = sync(db_path,
                   period_from=period_from,
                   period_to=period_to,
                   only_ids=only_ids,
                   dry_run=args.dry_run,
                   fetcher=fetcher)

    _print_summary(summary, dry_run=args.dry_run)
    return 0 if summary.errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
