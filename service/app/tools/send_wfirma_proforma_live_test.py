"""
send_wfirma_proforma_live_test.py — guarded live writer for ONE proforma in wFirma.

Scope:
  - Creates exactly ONE proforma via POST invoices/add.
  - Single customer. Single product. Single line. No batch.
  - No invoice finalization. No reservation. No WZ. No payment record.

Hard guards (cannot be removed via env vars or runtime config):
  1. Required flag: --live-confirm-I-understand
  2. Typed confirmation: YES_CREATE_ONE_TEST_PROFORMA
  3. Target registry: only pre-vetted (customer × product) pairs allowed.
  4. Pre-flight: live fetch_contractor_terms + resolve_proforma BEFORE
     any HTTP write. If anything blocks, no POST is made.
  5. The internal sender posts at most ONE request per invocation.

Schema (locked from live wFirma probes 2026-05-03):
    <api>
      <invoices>
        <invoice>
          <type>proforma</type>
          <date>YYYY-MM-DD</date>
          <paymentdate>YYYY-MM-DD</paymentdate>          <!-- doc + payment_days -->
          <currency>USD|EUR|PLN</currency>
          <price_currency_exchange>4.0885</price_currency_exchange>
          <vat_payer>1</vat_payer>
          <price_type>netto</price_type>
          <paymentmethod>transfer</paymentmethod>
          <description>...</description>
          <contractor><id>NNNNN</id></contractor>
          <warehouse><id>0</id></warehouse>
          <series><id>15827088</id></series>
          <company_account><id>NNNN</id></company_account>
          <translation_language><id>N</id></translation_language>
          <invoicecontents>
            <invoicecontent>
              <name>Polish / English description</name>
              <good><id>NNNNN</id></good>
              <unit>szt.</unit>
              <unit_count>1.0000</unit_count>
              <price>25.00</price>
              <vat_code><id>222|228|229</id></vat_code>
            </invoicecontent>
          </invoicecontents>
        </invoice>
      </invoices>
    </api>

Usage (REQUIRED ORDER):
    # Dry-run first (always safe, no flag → no HTTP call)
    python3 -m app.tools.send_wfirma_proforma_live_test --target sd-no-test

    # Live (requires flag + typed confirmation)
    python3 -m app.tools.send_wfirma_proforma_live_test --target sd-no-test \\
        --live-confirm-I-understand
    # then type EXACTLY: YES_CREATE_ONE_TEST_PROFORMA
"""
from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional
from xml.sax.saxutils import escape


def _bootstrap() -> None:
    here = Path(__file__).resolve()
    repo_root = here.parents[3]
    service_dir = here.parents[2]
    for p in (str(repo_root), str(service_dir)):
        if p not in sys.path:
            sys.path.insert(0, p)


_bootstrap()

from app.models.proforma_resolver import (   # noqa: E402
    COMPANY_ACCOUNT_BY_CURRENCY,
    ContractorTerms,
    ProformaResolution,
    ProformaResolutionBlocked,
    fetch_contractor_terms,
    resolve_proforma,
)
from app.models.vat_resolver import (         # noqa: E402
    CustomerForVAT,
    ManualReviewRequired,
)
from app.services.freight_resolver import (   # noqa: E402
    FreightUnresolved,
    ResolvedFreight,
    resolve_freight,
)
from app.services.customer_master import (    # noqa: E402
    CustomerMasterResolver,
    CustomerNotFound,
    SHIP_TO_NONE,
    SHIP_TO_ALTERNATE_ADDRESS,
    SHIP_TO_SEPARATE_CONTRACTOR,
    pick_currency as cm_pick_currency,
    pick_freight as cm_pick_freight,
    pick_freight_service_id as cm_pick_freight_service_id,
    pick_insurance_min as cm_pick_insurance_min,
    pick_insurance_service_id as cm_pick_insurance_service_id,
    pick_invoice_series_id as cm_pick_invoice_series_id,
    pick_language_id as cm_pick_language_id,
    pick_proforma_series_id as cm_pick_proforma_series_id,
    pick_vat_mode as cm_pick_vat_mode,
    ship_to_shape as cm_ship_to_shape,
    to_vat_input as cm_to_vat_input,
)


# ── Hard-coded guards (intentionally not configurable) ────────────────────────

REQUIRED_FLAG          = "--live-confirm-I-understand"
REQUIRED_CONFIRMATION  = "YES_CREATE_ONE_TEST_PROFORMA"
WFIRMA_INVOICES_MODULE = "invoices"
WFIRMA_INVOICES_ACTION = "add"

# Live-confirmed defaults for THIS account (wFirma probes 2026-05-03)
PROFORMA_SERIES_ID     = "15827088"
PROFORMA_WAREHOUSE_ID  = "0"            # proforma does not bind to a warehouse

# Insurance service line — every proforma carries one
# Live-confirmed wFirma good_id (type=service, name "Insurance covers the Door
# to Door delivery..."). Live probe 2026-05-03.
INSURANCE_SERVICE_ID   = "13102217"
INSURANCE_LINE_NAME    = (
    "Insurance / Ubezpieczenie — Door-to-Door package delivery"
)
INSURANCE_RATE         = Decimal("0.0035")    # 0.35% of FOB/CIF base value

# Customer-specific insurance minimum, keyed by the proforma's vat_code_id.
# Derived from historical export invoicing patterns:
#   PL  (vat 222) → 10 PLN  (EU domestic, mirrors WDT pattern)
#   WDT (vat 228) → 10 EUR/USD  (EU export, observed in 2021 EU customer history)
#   EXP (vat 229) → 20 USD/EUR  (non-EU export, observed for NO customer in 2020)
INSURANCE_MIN_BY_VAT_CODE: Dict[int, Decimal] = {
    222: Decimal("10"),
    228: Decimal("10"),
    229: Decimal("20"),
}

# Freight service line — every export proforma carries one
# Live-confirmed wFirma good_id (type=service, name "Fedex Courier"),
# observed in 34 historical export documents to USD and EUR customers.
# Amount is ALWAYS operator-supplied (real shipment cost, not a formula) —
# the writer blocks if --freight is missing.
FREIGHT_SERVICE_ID     = "13002743"
FREIGHT_LINE_NAME      = "Fedex Courier"


# ── Target registry — pre-vetted (customer × product) pairs ──────────────────

@dataclass(frozen=True)
class ProformaTarget:
    """One vetted test target. Each field is operator-confirmed at registry time."""
    key:                       str
    target_description:        str             # short label of THIS target (operator-readable)
    # Customer / contractor
    contractor_id:             str
    customer_country:          str
    customer_vat_eu_valid:     Optional[bool]   # True/False/None
    customer_vat_eu_number:    Optional[str]
    # Product
    wfirma_good_id:            str
    product_code:              str
    line_name:                 str             # bilingual "Polish / English"
    # Money
    currency:                  str             # PLN | USD | EUR
    qty:                       Decimal
    unit_price:                Decimal         # in `currency`
    price_currency_exchange:   Decimal         # FX rate to PLN, 1.0 if PLN
    # Doc
    doc_description:           str             # text put into <description> on the proforma
    fallback_payment_days:     Optional[int] = None    # used only if contractor profile is empty
    fallback_payment_method:   Optional[str] = None


# A SINGLE registered target — Scandinavian Diamond (Norway, non-EU, USD).
# Norway is NOT in EU → vat_code 229 (EXP 0%).
# This contractor was used in 2020 proformas, has payment_method=transfer/payment_days=7.
_TARGETS: Dict[str, ProformaTarget] = {
    "sd-no-test": ProformaTarget(
        key                     = "sd-no-test",
        target_description      = "Scandinavian Diamond (NO) — single line silver pendant USD test proforma",
        contractor_id           = "38582303",
        customer_country        = "NO",
        customer_vat_eu_valid   = None,           # Norway is non-EU; field is irrelevant
        customer_vat_eu_number  = None,
        wfirma_good_id          = "48461283",     # EJL/26-27/015-3
        product_code            = "EJL/26-27/015-3",
        line_name               = ("Wisiorek ze srebra próby 925 z diamentami laboratoryjnymi"
                                   " / SL925 Silver LGD Diamond Pendant"),
        currency                = "USD",
        qty                     = Decimal("1"),
        unit_price              = Decimal("25.00"),     # USD — small + verifiable
        price_currency_exchange = Decimal("4.0000"),    # safe round rate; wFirma may auto-correct
        doc_description         = "Test proforma — single line, automation guard validation",
    ),
}


def list_targets() -> List[str]:
    return list(_TARGETS.keys())


def get_target(key: str) -> ProformaTarget:
    if key not in _TARGETS:
        raise KeyError(f"unknown target {key!r}; known: {list_targets()}")
    return _TARGETS[key]


# ── Layer 2: customer-master-driven target builder ───────────────────────────

def _default_lookup_good(product_code: Optional[str],
                         good_id:      Optional[str]) -> dict:
    """Live wFirma lookup: code → (wfirma_good_id, name). Pass good_id to skip lookup.

    Returns dict {wfirma_good_id, name, unit}.
    """
    if good_id and not product_code:
        # Caller already has the id; we don't need to look it up. They must
        # pass --line-name in this case (since we don't fetch the master record).
        return {"wfirma_good_id": good_id, "name": "", "unit": "szt."}
    if not product_code:
        raise ValueError("product_code is required when good_id not given")
    from app.services import wfirma_client as wfc
    prod = wfc.get_product_by_code(product_code)
    if prod is None:
        raise ValueError(f"product code {product_code!r} not found in wFirma goods/find")
    return {
        "wfirma_good_id": prod.wfirma_id,
        "name":           prod.name,
        "unit":           prod.unit or "szt.",
    }


def build_target_from_customer_master(cm,
                                      product_code:   Optional[str],
                                      good_id:        Optional[str],
                                      qty:            Decimal,
                                      unit_price:     Decimal,
                                      *,
                                      line_name:      Optional[str] = None,
                                      doc_description: Optional[str] = None,
                                      currency:       Optional[str] = None,
                                      fx_rate:        Optional[Decimal] = None,
                                      product_lookup_fn=None) -> ProformaTarget:
    """Construct a ProformaTarget from a CustomerMaster + product CLI inputs.

    `product_lookup_fn(product_code, good_id) → {wfirma_good_id, name, unit}` is
    injectable so tests don't hit wFirma. Defaults to live goods/find.
    """
    if cm is None:
        raise ValueError("CustomerMaster is required")

    chosen_currency = (currency or cm.default_currency or "").strip().upper()
    if not chosen_currency:
        raise ValueError(
            f"customer {cm.bill_to_contractor_id!r} has no default_currency and "
            f"--currency was not supplied"
        )

    # FX: PLN = 1.0; non-PLN must be supplied (operator) or fetched live
    chosen_fx = fx_rate if fx_rate is not None else (Decimal("1") if chosen_currency == "PLN" else None)
    if chosen_fx is None:
        raise ValueError(
            f"--fx-rate is required for currency {chosen_currency!r} "
            f"(or run NBP fetcher upstream)"
        )

    # Look up product if needed
    lookup = product_lookup_fn or _default_lookup_good
    info   = lookup(product_code, good_id)
    chosen_good_id = (good_id or info.get("wfirma_good_id") or "").strip()
    chosen_name    = line_name or info.get("name") or product_code or ""
    if not chosen_good_id:
        raise ValueError("could not resolve wfirma_good_id (pass --good-id or check --product-code)")

    return ProformaTarget(
        key                     = f"cm:{cm.bill_to_contractor_id}:{product_code or chosen_good_id}",
        target_description      = f"customer-master driven: {cm.bill_to_name} ({cm.country})",
        contractor_id           = cm.bill_to_contractor_id,
        customer_country        = cm.country,
        customer_vat_eu_valid   = cm.vat_eu_valid,
        customer_vat_eu_number  = cm.vat_eu_number,
        wfirma_good_id          = chosen_good_id,
        product_code            = product_code or chosen_good_id,
        line_name               = chosen_name,
        currency                = chosen_currency,
        qty                     = Decimal(qty),
        unit_price              = Decimal(unit_price),
        price_currency_exchange = Decimal(chosen_fx),
        doc_description         = doc_description or
            f"Proforma to {cm.bill_to_name} — automated via customer master",
    )


# ── XML payload ───────────────────────────────────────────────────────────────

def _esc(value: Any) -> str:
    return escape(str(value), {'"': "&quot;", "'": "&apos;"})


def _decimal(value: Decimal, places: int = 2) -> str:
    """Always dot-decimal in XML."""
    fmt = f"{{:.{places}f}}"
    return fmt.format(Decimal(value))


def insurance_min_for_vat(vat_code_id: int) -> Decimal:
    """Customer-specific insurance minimum, looked up by VAT code.

    Raises ValueError if the vat_code_id has no configured minimum — we
    refuse to silently default, since under-insuring is a real liability.
    """
    if vat_code_id not in INSURANCE_MIN_BY_VAT_CODE:
        raise ValueError(
            f"no insurance minimum configured for vat_code_id={vat_code_id}. "
            f"Known: {sorted(INSURANCE_MIN_BY_VAT_CODE)}. "
            f"Add the minimum to INSURANCE_MIN_BY_VAT_CODE before generating "
            f"this proforma."
        )
    return INSURANCE_MIN_BY_VAT_CODE[vat_code_id]


def calc_insurance(product_subtotal: Decimal,
                   vat_code_id: int,
                   *,
                   rate: Decimal = INSURANCE_RATE) -> Decimal:
    """Insurance = max(customer_min(vat), product_subtotal * rate). Pure function.

    The minimum is determined per customer by VAT treatment:
        PL (222)  → 10
        WDT (228) → 10
        EXP (229) → 20

    Currency follows the proforma — this function only operates on the
    numeric base value, so the result is in the same currency as input.
    Quantised to 2 decimal places.
    """
    base = Decimal(product_subtotal)
    if base < 0:
        raise ValueError(f"product_subtotal must be >= 0, got {product_subtotal}")
    min_amount = insurance_min_for_vat(int(vat_code_id))
    pct = (base * rate).quantize(Decimal("0.01"))
    return max(min_amount, pct).quantize(Decimal("0.01"))


def build_contractor_receiver_block(ship_to_shape_value: str,
                                    ship_to_contractor_id: Optional[str]) -> str:
    """Render the <contractor_receiver> XML block based on ship-to shape.

    Layer 2 supports all 3 shapes:
      "none"                 → <contractor_receiver><id>0</id> (matches historical
                               wFirma proformas; explicit 0 = "no separate receiver")
      "alternate_address"    → <contractor_receiver><id>0</id> (delivery address
                               comes from the contractor's contact_* fields with
                               different_contact_address=1; no extra XML needed
                               on the proforma itself)
      "separate_contractor"  → <contractor_receiver><id>NNN</id> (receiver is a
                               different wFirma contractor record)
    """
    if ship_to_shape_value == "separate_contractor":
        if not ship_to_contractor_id:
            raise ValueError(
                "ship_to_shape=separate_contractor requires a non-empty ship_to_contractor_id"
            )
        return (f"<contractor_receiver>\n"
                f"        <id>{_esc(ship_to_contractor_id)}</id>\n"
                f"      </contractor_receiver>")
    # none + alternate_address both render id=0 (historical wFirma default)
    return ("<contractor_receiver>\n"
            "        <id>0</id>\n"
            "      </contractor_receiver>")


def build_proforma_xml(t: ProformaTarget,
                       resolution: ProformaResolution,
                       document_date: date,
                       *,
                       freight_service_id:   Optional[str] = None,
                       freight_amount:       Optional[Decimal] = None,
                       insurance_service_id: Optional[str] = None,
                       insurance_amount:     Optional[Decimal] = None,
                       ship_to_shape:        str = "none",
                       ship_to_contractor_id: Optional[str] = None) -> str:
    """Build the proforma XML payload (3 invoicecontent lines: product + freight + insurance).
    No HTTP call.

    The caller MUST pass all four service args; this function does NOT
    auto-compute. The CLI / preflight does that and blocks early.

    ship_to_shape ∈ {"none","alternate_address","separate_contractor"}
    Determines the <contractor_receiver> XML block. See build_contractor_receiver_block.
    """
    if not insurance_service_id:
        raise ValueError(
            "insurance_service_id is required — every proforma must carry an insurance line"
        )
    if insurance_amount is None or Decimal(insurance_amount) <= 0:
        raise ValueError(
            f"insurance_amount must be > 0, got {insurance_amount}"
        )
    if not freight_service_id:
        raise ValueError(
            "freight_service_id is required — every export proforma must carry a freight line"
        )
    if freight_amount is None or Decimal(freight_amount) <= 0:
        raise ValueError(
            f"freight_amount must be > 0, got {freight_amount}"
        )

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<api>
  <invoices>
    <invoice>
      <type>proforma</type>
      <date>{document_date.isoformat()}</date>
      <paymentdate>{resolution.payment_date.isoformat()}</paymentdate>
      <currency>{_esc(t.currency)}</currency>
      <price_currency_exchange>{_decimal(t.price_currency_exchange, 6)}</price_currency_exchange>
      <vat_payer>1</vat_payer>
      <price_type>netto</price_type>
      <paymentmethod>{_esc(resolution.payment_method)}</paymentmethod>
      <description>{_esc(t.doc_description)}</description>
      <contractor>
        <id>{_esc(t.contractor_id)}</id>
      </contractor>
      {build_contractor_receiver_block(ship_to_shape, ship_to_contractor_id)}
      <warehouse>
        <id>{PROFORMA_WAREHOUSE_ID}</id>
      </warehouse>
      <series>
        <id>{PROFORMA_SERIES_ID}</id>
      </series>
      <company_account>
        <id>{_esc(resolution.company_account_id)}</id>
      </company_account>
      <translation_language>
        <id>{_esc(resolution.language_id)}</id>
      </translation_language>
      <invoicecontents>
        <invoicecontent>
          <name>{_esc(t.line_name)}</name>
          <good>
            <id>{_esc(t.wfirma_good_id)}</id>
          </good>
          <unit>szt.</unit>
          <unit_count>{_decimal(t.qty, 4)}</unit_count>
          <price>{_decimal(t.unit_price, 2)}</price>
          <vat_code>
            <id>{resolution.vat_code_id}</id>
          </vat_code>
        </invoicecontent>
        <invoicecontent>
          <name>{_esc(FREIGHT_LINE_NAME)}</name>
          <good>
            <id>{_esc(freight_service_id)}</id>
          </good>
          <unit>szt.</unit>
          <unit_count>1.0000</unit_count>
          <price>{_decimal(freight_amount, 2)}</price>
          <vat_code>
            <id>{resolution.vat_code_id}</id>
          </vat_code>
        </invoicecontent>
        <invoicecontent>
          <name>{_esc(INSURANCE_LINE_NAME)}</name>
          <good>
            <id>{_esc(insurance_service_id)}</id>
          </good>
          <unit>szt.</unit>
          <unit_count>1.0000</unit_count>
          <price>{_decimal(insurance_amount, 2)}</price>
          <vat_code>
            <id>{resolution.vat_code_id}</id>
          </vat_code>
        </invoicecontent>
      </invoicecontents>
    </invoice>
  </invoices>
</api>
"""


# ── Plan + result reporting ───────────────────────────────────────────────────

def print_plan(t: ProformaTarget,
               resolution: ProformaResolution,
               document_date: date,
               xml: str,
               contractor_terms: ContractorTerms,
               *,
               freight:          ResolvedFreight,
               insurance_amount: Decimal,
               product_subtotal: Decimal,
               grand_total:      Decimal,
               ship_to_shape:    str = "none",
               ship_to_contractor_id: Optional[str] = None) -> None:
    width = 76
    print("=" * width)
    print(" wFirma PROFORMA — LIVE WRITE PLAN")
    print("=" * width)
    print(f"  endpoint               : POST /{WFIRMA_INVOICES_MODULE}/{WFIRMA_INVOICES_ACTION}")
    print(f"  target key             : {t.key}")
    print(f"  description            : {t.target_description}")
    print()
    print("  CUSTOMER")
    print(f"    contractor id        : {t.contractor_id}")
    print(f"    country              : {t.customer_country}")
    ship_to_label = ship_to_shape
    if ship_to_shape == "separate_contractor":
        ship_to_label += f" → contractor_receiver.id = {ship_to_contractor_id}"
    elif ship_to_shape == "alternate_address":
        ship_to_label += " (uses contractor's contact_* fields; verify different_contact_address=1 in wFirma)"
    print(f"    ship_to              : {ship_to_label}")
    if t.customer_vat_eu_valid is not None:
        print(f"    vat_eu_valid         : {t.customer_vat_eu_valid}  ({t.customer_vat_eu_number})")
    print()
    print("  CONTRACTOR PROFILE (live-fetched)")
    print(f"    payment_method       : {contractor_terms.payment_method}")
    print(f"    payment_days         : {contractor_terms.payment_days}")
    print()
    print("  PRODUCT")
    print(f"    code (Indeks)        : {t.product_code}")
    print(f"    wfirma_good_id       : {t.wfirma_good_id}")
    print(f"    name (bilingual)     : {t.line_name}")
    print()
    customer_min = INSURANCE_MIN_BY_VAT_CODE.get(resolution.vat_code_id)
    customer_min_str = f"{customer_min}" if customer_min is not None else "?"
    pct_value    = (product_subtotal * INSURANCE_RATE).quantize(Decimal('0.01'))
    print("  MONEY")
    print(f"    currency             : {t.currency}")
    print(f"    qty                  : {t.qty}")
    print(f"    unit_price           : {t.unit_price} {t.currency}")
    print(f"    product subtotal     : {product_subtotal:.2f} {t.currency}")
    src_extra = ""
    if freight.source_doc_number:
        src_extra = f" — from {freight.source_doc_number} ({freight.source_doc_date or 'no-date'})"
    print(f"    freight              : {freight.amount:.2f} {t.currency}    "
          f"(service id={FREIGHT_SERVICE_ID}, source={freight.source_type}{src_extra})")
    print(f"    insurance calc       : max({customer_min_str} [vat={resolution.vat_code_id}], "
          f"{product_subtotal:.2f} × {INSURANCE_RATE} = {pct_value})")
    print(f"    insurance amount     : {insurance_amount:.2f} {t.currency}    (service id={INSURANCE_SERVICE_ID})")
    print(f"    GRAND TOTAL          : {grand_total:.2f} {t.currency}    (product + freight + insurance)")
    print(f"    fx_rate (price→PLN)  : {t.price_currency_exchange}")
    print()
    print("  RESOLVED")
    print(f"    vat_code_id          : {resolution.vat_code_id}    "
          f"({'23% PL' if resolution.vat_code_id==222 else ('WDT 0%' if resolution.vat_code_id==228 else 'EXP 0%')})")
    print(f"    company_account_id   : {resolution.company_account_id}    ({t.currency} bank)")
    print(f"    translation_language : {resolution.language_id}")
    print(f"    payment_method       : {resolution.payment_method}")
    print(f"    payment_days         : {resolution.payment_days}")
    print(f"    document_date        : {document_date}")
    print(f"    paymentdate          : {resolution.payment_date}")
    print()
    print("  XML BODY:")
    print("  " + "-" * (width - 4))
    for line in xml.splitlines():
        print(f"  {line}")
    print("  " + "-" * (width - 4))
    print()
    print("  EXPECTED RESULT")
    print("  ---------------")
    print("  ✓ wFirma returns <status><code>OK</code></status> AND")
    print("    <invoices><invoice><id>NNNNNNN</id></invoice></invoices> — the new proforma id.")
    print()
    print("  ROLLBACK / DELETE INSTRUCTION")
    print("  -----------------------------")
    print("  If created and you want to remove it (allowed before any payment recorded):")
    print("    1. wFirma UI → Przychody → Faktury → search by date → open the proforma")
    print("       → Usuń (trash icon).")
    print("    2. Or via API: DELETE invoices/delete/{id} with the same 3-header auth.")
    print("  Proformas do NOT touch warehouse stock and are not part of VAT register until")
    print("  finalised, so deletion is clean.")
    print()


@dataclass
class ProformaSendResult:
    ok:             bool
    http_status:    int
    wfirma_status:  str
    wfirma_message: str
    invoice_id:     Optional[str]
    raw_response:   str


def _parse_response(http_status: int, response_text: str) -> ProformaSendResult:
    wfirma_code, wfirma_msg, invoice_id = "", "", None
    try:
        root = ET.fromstring(response_text)
        status = root.find("status")
        if status is not None:
            ce = status.find("code")
            me = status.find("message")
            wfirma_code = (ce.text or "").strip() if ce is not None else ""
            wfirma_msg  = (me.text or "").strip() if me is not None else ""
        inv = root.find(".//invoices/invoice")
        if inv is None:
            inv = root.find(".//invoice")
        if inv is not None:
            id_el = inv.find("id")
            if id_el is not None and id_el.text:
                invoice_id = id_el.text.strip()
    except ET.ParseError:
        pass

    ok = http_status < 400 and wfirma_code == "OK" and invoice_id is not None
    return ProformaSendResult(
        ok             = ok,
        http_status    = http_status,
        wfirma_status  = wfirma_code or "(empty)",
        wfirma_message = wfirma_msg,
        invoice_id     = invoice_id,
        raw_response   = response_text,
    )


def send_proforma(xml_body: str) -> ProformaSendResult:
    """Single POST. Caller is responsible for ALL guard checks before this."""
    from app.services import wfirma_client as wfc
    http_status, response_text = wfc._http_request(
        "POST", WFIRMA_INVOICES_MODULE, WFIRMA_INVOICES_ACTION, xml_body,
    )
    return _parse_response(http_status, response_text)


def print_result(result: ProformaSendResult) -> None:
    width = 76
    print("=" * width)
    print(" wFirma PROFORMA — LIVE WRITE RESULT")
    print("=" * width)
    if result.ok:
        print(f"  STATUS         : ✓ OK")
        print(f"  invoice ID     : {result.invoice_id}")
    else:
        print(f"  STATUS         : ✗ FAILED")
        print(f"  http_status    : {result.http_status}")
        print(f"  wfirma_status  : {result.wfirma_status}")
        if result.wfirma_message:
            print(f"  wfirma_message : {result.wfirma_message}")
    print()
    print("  RAW RESPONSE:")
    print("  " + "-" * (width - 4))
    for line in result.raw_response.splitlines():
        print(f"  {line}")
    print("  " + "-" * (width - 4))
    print()


# ── Guards ────────────────────────────────────────────────────────────────────

class GuardError(Exception):
    pass


def assert_guards(args: argparse.Namespace) -> None:
    if not args.live_confirm_I_understand:
        raise GuardError(f"Refusing to send. Required flag missing: {REQUIRED_FLAG}")


def read_confirmation(stream=None) -> str:
    s = stream if stream is not None else sys.stdin
    return s.readline().rstrip("\n")


# ── Pre-flight resolution (live fetch + resolve) ──────────────────────────────

def preflight(t: ProformaTarget,
              document_date: date,
              *,
              fetch_terms_fn=None,
              lang_map: Optional[Dict[str, int]] = None,
              default_language_id: str = "1") -> tuple:
    """Live pre-flight: fetch contractor terms + run resolver. Returns
    (contractor_terms, resolution). Raises ProformaResolutionBlocked or
    ManualReviewRequired on any blocker.

    fetch_terms_fn is injectable so tests don't hit wFirma."""
    fetcher = fetch_terms_fn if fetch_terms_fn is not None else fetch_contractor_terms
    contractor_terms = fetcher(t.contractor_id)

    customer = CustomerForVAT(
        country       = t.customer_country,
        vat_eu_valid  = t.customer_vat_eu_valid,
        vat_eu_number = t.customer_vat_eu_number,
    )

    resolution = resolve_proforma(
        customer                = customer,
        currency                = t.currency,
        contractor              = contractor_terms,
        document_date           = document_date,
        lang_map                = lang_map,
        default_language_id     = default_language_id,
        fallback_payment_method = t.fallback_payment_method,
        fallback_payment_days   = t.fallback_payment_days,
    )
    return contractor_terms, resolution


# ── CLI ───────────────────────────────────────────────────────────────────────

def main(argv: Optional[List[str]] = None,
         input_stream=None,
         http_sender=None,
         fetch_terms_fn=None,
         product_lookup_fn=None) -> int:
    """
    http_sender:       callable(xml_body) → ProformaSendResult (default = real POST)
    fetch_terms_fn:    callable(contractor_id) → ContractorTerms (default = real fetch)
    product_lookup_fn: callable(product_code, good_id) → {wfirma_good_id, name, unit}
                       (default = live goods/find). Used by --bill-to path only.
    """
    p = argparse.ArgumentParser(
        prog="send_wfirma_proforma_live_test",
        description="GUARDED live writer for ONE proforma in wFirma.",
    )
    # Mode A — customer master driven (preferred)
    p.add_argument("--bill-to", default=None,
                   help="wFirma contractor id of the bill-to customer. The writer "
                        "loads currency, language, insurance min, ship-to shape from "
                        "customer_master DB. Mutually exclusive with --target.")
    p.add_argument("--customer-master-db", default=None,
                   help="Path to customer_master SQLite. Default: <repo>/storage/customer_master.sqlite")
    p.add_argument("--product-code", default=None, help="EJL/... product code (resolves to wfirma_good_id)")
    p.add_argument("--good-id",      default=None, help="wfirma_good_id (skip product lookup)")
    p.add_argument("--qty",          default=None, help="Quantity (decimal)")
    p.add_argument("--unit-price",   default=None, help="Unit price in proforma currency (decimal)")
    p.add_argument("--currency",     default=None, help="Override customer's default_currency")
    p.add_argument("--fx-rate",      default=None, help="USD/EUR ↔ PLN exchange rate (required for non-PLN)")
    p.add_argument("--line-name",    default=None, help="Override product line name (defaults to wFirma good's name)")
    # Mode B — legacy registry target (kept for backward compat)
    p.add_argument("--target", default=None, choices=list_targets(),
                   help="Legacy: pre-vetted target key. Use --bill-to instead.")
    p.add_argument("--freight", default=None,
                   help="Freight amount override in proforma currency. If omitted, "
                        "the freight resolver looks up the customer's history "
                        "(local DB → invoices → proformas). If still unresolved, the "
                        "writer blocks and asks the operator to supply --freight.")
    p.add_argument("--freight-db", default=None,
                   help="Path to the customer_freight_history SQLite. "
                        "Defaults to <repo>/storage/freight_history.sqlite")
    p.add_argument("--date", default=None, help="Override document_date (YYYY-MM-DD)")
    p.add_argument(REQUIRED_FLAG, dest="live_confirm_I_understand",
                   action="store_true", help="Required for live POST")
    args = p.parse_args(argv)

    # Mutual exclusion + mode detection
    if not args.bill_to and not args.target:
        print("either --bill-to (preferred) or --target (legacy) is required",
              file=sys.stderr)
        return 2
    if args.bill_to and args.target:
        print("--bill-to and --target are mutually exclusive — pick one",
              file=sys.stderr)
        return 2

    document_date = (
        datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else date.today()
    )

    # ── Mode A: customer master driven ───────────────────────────────────────
    cm_record = None
    cm_ship_shape = SHIP_TO_NONE
    cm_ship_to_contractor_id = None
    if args.bill_to:
        cm_db = (Path(args.customer_master_db).expanduser()
                 if args.customer_master_db
                 else Path(__file__).resolve().parents[3] / "storage" / "customer_master.sqlite")
        try:
            cm_record = CustomerMasterResolver(cm_db).require(args.bill_to)
        except CustomerNotFound as exc:
            print(f"PRE-FLIGHT BLOCKED: {exc}", file=sys.stderr)
            return 7

        # Required CLI args for this mode
        for required in ("qty", "unit_price"):
            if getattr(args, required) is None:
                print(f"--{required.replace('_','-')} is required when --bill-to is given", file=sys.stderr)
                return 2
        try:
            qty        = Decimal(str(args.qty))
            unit_price = Decimal(str(args.unit_price))
            fx_rate    = Decimal(str(args.fx_rate)) if args.fx_rate else None
        except Exception as exc:  # noqa: BLE001
            print(f"qty/unit-price/fx-rate must be valid decimals: {exc}", file=sys.stderr)
            return 2

        try:
            target = build_target_from_customer_master(
                cm_record,
                product_code     = args.product_code,
                good_id          = args.good_id,
                qty              = qty,
                unit_price       = unit_price,
                line_name        = args.line_name,
                currency         = args.currency,
                fx_rate          = fx_rate,
                product_lookup_fn = product_lookup_fn,
            )
        except ValueError as exc:
            print(f"PRE-FLIGHT BLOCKED: {exc}", file=sys.stderr)
            return 7

        cm_ship_shape = cm_ship_to_shape(cm_record)
        cm_ship_to_contractor_id = cm_record.ship_to_contractor_id
    else:
        # Mode B: legacy registry
        target = get_target(args.target)

    # Parse freight override if supplied; otherwise we resolve below
    manual_freight: Optional[Decimal] = None
    if args.freight is not None:
        try:
            manual_freight = Decimal(str(args.freight))
        except Exception as exc:  # noqa: BLE001
            print(f"--freight is not a valid decimal: {args.freight!r} ({exc})",
                  file=sys.stderr)
            return 2
        if manual_freight <= 0:
            print(f"--freight must be > 0, got {manual_freight}", file=sys.stderr)
            return 2

    # DB path for freight history (default = <repo>/storage/freight_history.sqlite)
    if args.freight_db:
        freight_db = Path(args.freight_db).expanduser()
    else:
        freight_db = Path(__file__).resolve().parents[3] / "storage" / "freight_history.sqlite"

    # Pre-flight (always runs, even in dry-run, to surface blockers early)
    try:
        contractor_terms, resolution = preflight(
            target, document_date, fetch_terms_fn=fetch_terms_fn,
        )
    except (ProformaResolutionBlocked, ManualReviewRequired) as exc:
        print(f"PRE-FLIGHT BLOCKED: {exc}", file=sys.stderr)
        return 7
    except (ConnectionError, ValueError) as exc:
        print(f"PRE-FLIGHT ERROR: {exc}", file=sys.stderr)
        return 5

    # Service-line pre-flight — both ids MUST be configured. Block before any HTTP.
    insurance_id = (INSURANCE_SERVICE_ID or "").strip()
    if not insurance_id:
        print("PRE-FLIGHT BLOCKED: INSURANCE_SERVICE_ID is not configured.",
              file=sys.stderr)
        return 7
    freight_id = (FREIGHT_SERVICE_ID or "").strip()
    if not freight_id:
        print("PRE-FLIGHT BLOCKED: FREIGHT_SERVICE_ID is not configured.",
              file=sys.stderr)
        return 7

    # Resolve freight. Priority:
    #   1. operator --freight                       (manual override)
    #   2. customer_master.pick_freight()           (only when freight_mode=fixed)
    #   3. resolve_freight() historical cascade     (DB → invoices → proformas)
    # 1 and 2 short-circuit; cascade only runs when neither is available.
    cm_freight: Optional[Decimal] = None
    if manual_freight is None and cm_record is not None:
        cm_freight = cm_pick_freight(cm_record)
    if manual_freight is not None:
        freight = ResolvedFreight(
            amount             = manual_freight,
            currency           = target.currency,
            source_type        = "manual",
            source_doc_number  = None,
            source_doc_date    = None,
            freight_service_id = freight_id,
        )
    elif cm_freight is not None:
        freight = ResolvedFreight(
            amount             = cm_freight,
            currency           = target.currency,
            source_type        = "customer_master_fixed",
            source_doc_number  = None,
            source_doc_date    = None,
            freight_service_id = freight_id,
        )
    else:
        try:
            freight = resolve_freight(
                freight_db,
                contractor_id   = target.contractor_id,
                currency        = target.currency,
                manual_amount   = None,
                contractor_name = "",
                country         = target.customer_country,
                freight_service_id = freight_id,
            )
        except FreightUnresolved as exc:
            print(f"PRE-FLIGHT BLOCKED: {exc}", file=sys.stderr)
            return 8
        except (ConnectionError, ValueError) as exc:
            print(f"PRE-FLIGHT ERROR: freight resolver: {exc}", file=sys.stderr)
            return 5
    freight_amount = freight.amount

    product_subtotal = (Decimal(target.qty) * Decimal(target.unit_price)).quantize(Decimal("0.01"))
    try:
        insurance_amount = calc_insurance(product_subtotal, resolution.vat_code_id)
    except ValueError as exc:
        print(f"PRE-FLIGHT BLOCKED: {exc}", file=sys.stderr)
        return 7
    # Apply customer-master insurance override if set
    if cm_record is not None and cm_record.insurance_min_override is not None:
        insurance_amount = cm_pick_insurance_min(cm_record, insurance_amount)
    grand_total = (product_subtotal + freight_amount + insurance_amount).quantize(Decimal("0.01"))

    xml = build_proforma_xml(
        target, resolution, document_date,
        freight_service_id    = freight_id,
        freight_amount        = freight_amount,
        insurance_service_id  = insurance_id,
        insurance_amount      = insurance_amount,
        ship_to_shape         = cm_ship_shape,
        ship_to_contractor_id = cm_ship_to_contractor_id,
    )
    print_plan(
        target, resolution, document_date, xml, contractor_terms,
        freight                = freight,
        insurance_amount       = insurance_amount,
        product_subtotal       = product_subtotal,
        grand_total            = grand_total,
        ship_to_shape          = cm_ship_shape,
        ship_to_contractor_id  = cm_ship_to_contractor_id,
    )

    if not args.live_confirm_I_understand:
        print(f"DRY-RUN: flag {REQUIRED_FLAG} not set — no HTTP call made.\n")
        return 0

    try:
        assert_guards(args)
    except GuardError as exc:
        print(f"GUARD REFUSED: {exc}", file=sys.stderr)
        return 3

    print(
        f"You are about to create ONE REAL proforma in wFirma:\n"
        f"  customer={target.contractor_id}  good={target.wfirma_good_id}  "
        f"qty={target.qty}  total={target.qty * target.unit_price:.2f} {target.currency}\n"
        f"\n"
        f"To proceed, type exactly the following phrase and press Enter.\n"
        f"Anything else aborts with no HTTP call.\n\n"
        f"  Required phrase: {REQUIRED_CONFIRMATION}\n"
    )
    print("> ", end="", flush=True)
    typed = read_confirmation(input_stream)

    if typed != REQUIRED_CONFIRMATION:
        print(
            f"\nABORTED — confirmation phrase did not match.\n"
            f"  expected: {REQUIRED_CONFIRMATION!r}\n"
            f"  received: {typed!r}\n"
            f"No HTTP call was made.",
            file=sys.stderr,
        )
        return 4

    print("\nConfirmation accepted. Sending ONE POST to wFirma…\n")

    sender = http_sender if http_sender is not None else send_proforma
    try:
        result = sender(xml)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR sending proforma: {exc}", file=sys.stderr)
        return 5

    print_result(result)
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
