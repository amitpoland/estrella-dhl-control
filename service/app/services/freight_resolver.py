"""
freight_resolver.py — customer-specific freight resolution.

Decision flow (locked):
    1. Local DB (customer_freight_history) — fastest, fully offline
    2. wFirma final invoices (type=normal) for same contractor + currency
    3. wFirma proformas (type=proforma) for same contractor + currency
    4. Manual operator input (raises FreightUnresolved)

Why invoices first:
    Final invoices represent committed commercial reality. Proformas are
    offers that may have been edited or never finalised. We trust the
    invoice number over the proforma when both exist.

Side effects:
    When freight is resolved from wFirma history (steps 2 or 3), the value
    is automatically saved into the local DB so the next call hits step 1.
    Manual operator overrides are also saved with source_type='manual'.

I/O policy:
    The resolver itself orchestrates DB + wFirma. The wFirma search function
    is injectable so tests run without network. The DB is a Path argument.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable, List, Optional
import xml.etree.ElementTree as ET

from app.services.freight_history_db import (
    FreightRecord,
    get_latest_freight,
    init_db,
    save_freight_history,
)


# ── Constants ─────────────────────────────────────────────────────────────────

# wFirma good_id for the freight service line (live-confirmed 2026-05-03).
# Same constant is also imported by send_wfirma_proforma_live_test.py — both
# must agree.
FREIGHT_SERVICE_ID_DEFAULT = "13002743"

# Keywords that classify an invoicecontent line as freight when good_id alone
# isn't enough (e.g. operator entered a freight charge with a different service id).
FREIGHT_KEYWORDS = (
    "fedex", "freight", "fracht", "courier", "dhl",
    "transport", "shipping", "shipment", "porto", "postage",
)


# ── Public types ──────────────────────────────────────────────────────────────

class FreightUnresolved(Exception):
    """Raised when no freight history exists for this customer + currency
    in the DB, in invoices, or in proformas. The operator must supply
    a manual amount before the proforma can be generated."""

    def __init__(self, contractor_id: str, currency: str, message: str = "") -> None:
        msg = message or (
            f"No freight history found for contractor_id={contractor_id!r} "
            f"in currency {currency!r}. Operator must supply --freight."
        )
        super().__init__(msg)
        self.contractor_id = contractor_id
        self.currency      = currency


@dataclass(frozen=True)
class ResolvedFreight:
    """Freight resolution outcome — what value to use AND where it came from."""
    amount:             Decimal
    source_type:        str            # db | invoice | proforma | manual
    source_doc_id:      Optional[str] = None
    source_doc_number:  Optional[str] = None
    source_doc_date:    Optional[str] = None
    contractor_id:      str = ""
    contractor_name:    str = ""
    country:            str = ""
    currency:           str = ""
    freight_service_id: str = FREIGHT_SERVICE_ID_DEFAULT


# ── wFirma search (live) — injectable for tests ──────────────────────────────

def find_freight_in_wfirma(contractor_id: str,
                           currency:      str,
                           doc_type:      str,
                           freight_service_id: str = FREIGHT_SERVICE_ID_DEFAULT,
                           limit:         int = 20) -> Optional[ResolvedFreight]:
    """Search wFirma for the most recent doc of `doc_type` ('normal'/'proforma')
    for this contractor in this currency, and return its freight line if any.

    Read-only. Returns None if no match found. Raises ConnectionError on
    network failure (caller decides whether to swallow or propagate).
    """
    from app.services import wfirma_client as wfc

    body = f"""<?xml version="1.0" encoding="UTF-8"?>
<api>
  <invoices>
    <parameters>
      <conditions>
        <condition><field>type</field><operator>eq</operator><value>{doc_type}</value></condition>
        <condition><field>contractor_id</field><operator>eq</operator><value>{contractor_id}</value></condition>
        <condition><field>currency</field><operator>eq</operator><value>{currency}</value></condition>
      </conditions>
      <order><asc>0</asc><field>id</field></order>
      <page><start>0</start><limit>{int(limit)}</limit></page>
    </parameters>
  </invoices>
</api>"""
    http_status, response = wfc._http_request("GET", "invoices", "find", body)
    if http_status >= 400:
        raise ConnectionError(f"invoices/find HTTP {http_status} for {doc_type}")

    try:
        root = ET.fromstring(response)
    except ET.ParseError:
        return None

    for inv in root.findall("invoices/invoice"):
        contents = inv.find("invoicecontents")
        if contents is None:
            continue
        for c in contents.findall("invoicecontent"):
            gid_el = c.find("good/id")
            gid = (gid_el.text or "").strip() if gid_el is not None else ""
            name = (c.findtext("name") or "")
            if _is_freight_line(gid, name, freight_service_id):
                price = (c.findtext("price") or "0").strip()
                try:
                    amount = Decimal(price)
                except (InvalidOperation, ValueError):
                    continue
                if amount <= 0:
                    continue
                cd_name = inv.find("contractor_detail/name")
                cd_country = inv.find("contractor_detail/country")
                return ResolvedFreight(
                    amount             = amount,
                    source_type        = "invoice" if doc_type == "normal" else "proforma",
                    source_doc_id      = inv.findtext("id"),
                    source_doc_number  = inv.findtext("fullnumber"),
                    source_doc_date    = inv.findtext("date"),
                    contractor_id      = contractor_id,
                    contractor_name    = (cd_name.text if cd_name is not None and cd_name.text else ""),
                    country            = (cd_country.text if cd_country is not None and cd_country.text else ""),
                    currency           = currency,
                    freight_service_id = gid or freight_service_id,
                )
    return None


def _is_freight_line(good_id: str, name: str, configured_id: str) -> bool:
    """A line is freight if its good_id matches the configured service or
    its name contains a freight keyword."""
    if good_id and good_id == configured_id:
        return True
    n = name.lower()
    return any(k in n for k in FREIGHT_KEYWORDS)


# ── Cascading resolver ────────────────────────────────────────────────────────

def resolve_freight(db_path:       Path,
                    contractor_id: str,
                    currency:      str,
                    *,
                    manual_amount:    Optional[Decimal] = None,
                    contractor_name:  Optional[str] = None,
                    country:          Optional[str] = None,
                    freight_service_id: str = FREIGHT_SERVICE_ID_DEFAULT,
                    wfirma_search:    Optional[Callable] = None) -> ResolvedFreight:
    """Resolve freight for one (contractor_id, currency) using the 4-step cascade.

    Order:
      0. manual_amount (if caller passed --freight) → save as source='manual', return
      1. local DB (customer_freight_history) → return without API call
      2. wFirma invoices (type=normal)        → save to DB, return
      3. wFirma proformas (type=proforma)     → save to DB, return
      4. raise FreightUnresolved              → operator must intervene

    `wfirma_search` is the injectable hook for steps 2 and 3, signature:
        wfirma_search(contractor_id, currency, doc_type) → Optional[ResolvedFreight]
    Defaults to live find_freight_in_wfirma. Tests pass a stub.
    """
    init_db(db_path)
    search = wfirma_search or find_freight_in_wfirma

    # 0. manual override — save and return
    if manual_amount is not None:
        amt = Decimal(manual_amount)
        if amt <= 0:
            raise ValueError(f"manual_amount must be > 0, got {amt}")
        rec = ResolvedFreight(
            amount             = amt,
            source_type        = "manual",
            contractor_id      = contractor_id,
            contractor_name    = contractor_name or "",
            country            = country or "",
            currency           = currency,
            freight_service_id = freight_service_id,
        )
        _persist(db_path, rec)
        return rec

    # 1. local DB
    cached = get_latest_freight(db_path, contractor_id, currency)
    if cached is not None:
        return ResolvedFreight(
            amount             = cached.freight_amount,
            source_type        = "db",
            source_doc_id      = cached.source_doc_id,
            source_doc_number  = cached.source_doc_number,
            source_doc_date    = cached.source_doc_date,
            contractor_id      = cached.contractor_id,
            contractor_name    = cached.contractor_name,
            country            = cached.country,
            currency           = cached.currency,
            freight_service_id = cached.freight_service_id,
        )

    # 2. wFirma final invoices first (committed commercial documents)
    inv_match = search(contractor_id, currency, "normal")
    if inv_match is not None:
        # Force the queried contractor_id + currency onto the result. The
        # search filtered by these so the answer applies to them; never
        # trust whatever the response payload happens to carry.
        inv_match = _force_keys(inv_match, contractor_id, currency,
                                contractor_name, country)
        _persist(db_path, inv_match)
        return inv_match

    # 3. wFirma proformas (lower trust)
    prof_match = search(contractor_id, currency, "proforma")
    if prof_match is not None:
        prof_match = _force_keys(prof_match, contractor_id, currency,
                                 contractor_name, country)
        _persist(db_path, prof_match)
        return prof_match

    # 4. block
    raise FreightUnresolved(contractor_id, currency)


def _force_keys(rec:             ResolvedFreight,
                contractor_id:   str,
                currency:        str,
                contractor_name: Optional[str],
                country:         Optional[str]) -> ResolvedFreight:
    """Lock contractor_id + currency to what we queried for. Fill in
    contractor_name + country from caller if the response didn't carry them."""
    return replace(
        rec,
        contractor_id   = contractor_id,
        currency        = currency,
        contractor_name = rec.contractor_name or (contractor_name or ""),
        country         = rec.country         or (country         or ""),
    )


def _persist(db_path: Path, rec: ResolvedFreight) -> None:
    """Save a resolved freight to the local DB."""
    db_rec = FreightRecord(
        contractor_id      = rec.contractor_id,
        contractor_name    = rec.contractor_name,
        country            = rec.country,
        currency           = rec.currency,
        freight_service_id = rec.freight_service_id,
        freight_amount     = rec.amount,
        source_type        = rec.source_type,
        source_doc_id      = rec.source_doc_id,
        source_doc_number  = rec.source_doc_number,
        source_doc_date    = rec.source_doc_date,
    )
    save_freight_history(db_path, db_rec)


__all__ = [
    "FreightUnresolved",
    "ResolvedFreight",
    "FREIGHT_SERVICE_ID_DEFAULT",
    "FREIGHT_KEYWORDS",
    "find_freight_in_wfirma",
    "resolve_freight",
]
