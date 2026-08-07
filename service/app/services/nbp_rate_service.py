"""nbp_rate_service.py — canonical Proforma/Invoice FX authority over the PZ NBP service.

The ONE rate-fetch authority remains ``pz_import_processor.get_nbp_rate`` (the PZ
engine). This adapter does NOT reimplement HTTP access and adds NO second NBP
client — it CALLS the engine function and makes it safe to invoke from FastAPI:

  * Neutralises the engine's interactive ``input()`` fallback (never blocks a worker).
  * Never fabricates a fallback rate for a missing foreign currency.
  * Owns the document-currency registry (PLN / USD / EUR / INR, extensible).
  * Owns PLN-hub conversion: source → NBP/PLN → document currency.
  * Normalises NBP quotation units (e.g. HTML "100 INR") to PLN-per-1.

Currency model
--------------
PLN is the accounting base. Commercial source data (Sales Packing) may be in
USD / EUR / INR / …; the operator selects the Proforma document currency.
Conversion always goes through authoritative NBP/PLN rates — never an invented
cross-rate:

    source commercial currency → NBP/PLN → selected Proforma currency

Rate date: the engine resolves the NBP Table A for the business day preceding
the commercial issue / accounting date, walking back across weekends and
holidays until a published table is found.
"""
from __future__ import annotations

import io
import sys
import threading
from typing import Any, Dict, List, Optional, Tuple

# ── Currency registry (ONE source for Proforma / UI / validators) ─────────────
# Extensible: append a row to add a document currency. ``nbp`` means the currency
# is fetched from NBP Table A; PLN is identity. ``html_quote_unit`` is the unit
# shown on the NBP HTML table (JSON Table A already returns mid per 1 unit).

CURRENCY_REGISTRY: Tuple[Dict[str, Any], ...] = (
    {"code": "PLN", "label": "PLN · Polish Złoty",   "nbp": False, "html_quote_unit": 1},
    {"code": "USD", "label": "USD · US Dollar",      "nbp": True,  "html_quote_unit": 1},
    {"code": "EUR", "label": "EUR · Euro",           "nbp": True,  "html_quote_unit": 1},
    {"code": "INR", "label": "INR · Indian Rupee",   "nbp": True,  "html_quote_unit": 100},
)

DOCUMENT_CURRENCIES: Tuple[str, ...] = tuple(c["code"] for c in CURRENCY_REGISTRY)
FETCH_CURRENCIES: Tuple[str, ...] = tuple(
    c["code"] for c in CURRENCY_REGISTRY if c["nbp"]
)
SUPPORTED_CURRENCIES: Tuple[str, ...] = DOCUMENT_CURRENCIES  # identity + fetch

# HTML / XML quotation units (defensive — JSON Table A is already per-1).
NBP_HTML_QUOTE_UNITS: Dict[str, int] = {
    c["code"]: int(c["html_quote_unit"]) for c in CURRENCY_REGISTRY
}
# Common Table A multi-unit quotes beyond the document registry.
NBP_HTML_QUOTE_UNITS.update({
    "JPY": 100, "HUF": 100, "ISK": 100, "KRW": 100, "CLP": 100, "IDR": 10000,
})


# Serialises the stdin swap in ``_call_engine``. Sync FastAPI endpoints run in a
# threadpool, so without this two concurrent fetches could interleave the
# save/restore and leave the process stdin pointing at another call's stream.
_STDIN_LOCK = threading.Lock()


class NbpRateError(Exception):
    """Controlled adapter failure.

    ``kind`` ∈ {"unsupported_currency", "upstream", "missing_rate"} — the route
    maps it to the appropriate HTTP status (422 / 502).
    """

    def __init__(self, kind: str, message: str, *, leg: Optional[str] = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.leg = leg  # "source" | "doc" | None — set by convert()


def currencies() -> List[Dict[str, Any]]:
    """Operator-facing currency list (code + label). Single registry."""
    return [{"code": c["code"], "label": c["label"]} for c in CURRENCY_REGISTRY]


def is_document_currency(code: Any) -> bool:
    return str(code or "").strip().upper() in DOCUMENT_CURRENCIES


def normalize_nbp_mid(code: str, mid: float) -> float:
    """Return PLN per 1 unit of *code*.

    The NBP JSON Table A API already returns ``mid`` per 1 foreign unit even when
    the HTML table quotes per 100 (INR/JPY/…). If a caller feeds the HTML form
    (e.g. INR mid ≈ 3.97 for 100 units), detect and divide by the quote unit.
    """
    ccy = str(code or "").strip().upper()
    try:
        m = float(mid)
    except (TypeError, ValueError):
        return 0.0
    if m <= 0:
        return 0.0
    unit = int(NBP_HTML_QUOTE_UNITS.get(ccy, 1) or 1)
    if unit <= 1:
        return m
    # Heuristic: per-100 INR/JPY HTML mids are > 0.5; JSON per-1 mids are ≪ 0.5.
    if m >= 0.5:
        return m / unit
    return m


def _call_engine(accounting_date: str) -> Dict[str, Any]:
    """Invoke the sole PZ NBP authority with stdin neutralised."""
    from pz_import_processor import get_nbp_rate  # the ONE authority — not reimplemented
    with _STDIN_LOCK:
        saved_stdin = sys.stdin
        try:
            sys.stdin = io.StringIO("")
            return get_nbp_rate(accounting_date)
        finally:
            sys.stdin = saved_stdin


def fetch_table(accounting_date: str) -> Dict[str, Any]:
    """Fetch one NBP Table A (via the engine) and normalise every mid to PLN/1.

    Returns::
        {
          "table_number": str,
          "table_date": str,
          "accounting_date": str,
          "rates": {"USD": float, "EUR": float, "INR": float, ...},  # PLN per 1
          "source": "NBP",
        }
    """
    try:
        res = _call_engine(accounting_date)
    except (RuntimeError, SystemExit) as exc:
        raise NbpRateError("upstream", f"NBP rate service unavailable: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 — network / JSON / any engine error
        raise NbpRateError("upstream", f"NBP rate fetch failed: {exc}") from exc

    if not isinstance(res, dict):
        raise NbpRateError("upstream", "NBP service returned a malformed response")
    table_no = res.get("table_no")
    if table_no in (None, "", "MANUAL"):
        raise NbpRateError("upstream", "NBP service did not return a live table")

    rates_out: Dict[str, float] = {}
    raw_rates = res.get("rates") if isinstance(res.get("rates"), dict) else {}
    # Prefer the engine's rates dict (post-extension); fall back to usd/eur/inr keys.
    if raw_rates:
        for code, mid in raw_rates.items():
            n = normalize_nbp_mid(str(code), mid)
            if n > 0:
                rates_out[str(code).upper()] = n
    for code, key in (("USD", "usd_rate"), ("EUR", "eur_rate"), ("INR", "inr_rate")):
        if code in rates_out:
            continue
        n = normalize_nbp_mid(code, res.get(key) or 0)
        if n > 0:
            rates_out[code] = n

    return {
        "table_number": str(table_no),
        "table_date": res.get("table_date"),
        "accounting_date": accounting_date,
        "rates": rates_out,
        "source": "NBP",
    }


def fetch_rate(currency: str, accounting_date: str) -> Dict[str, Any]:
    """Resolve the NBP (or identity) rate for *currency* keyed to *accounting_date*.

    Returns::
        ``{"rate": float, "source": "NBP"|"identity", "table_number": str|None,
           "table_date": str|None, "accounting_date": str, "currency": str}``

    ``rate`` is always PLN per 1 unit of *currency* (identity 1.0 for PLN).
    """
    ccy = str(currency or "").strip().upper()

    if ccy == "PLN":
        return {
            "rate": 1.0, "source": "identity", "table_number": None,
            "table_date": None, "accounting_date": accounting_date, "currency": "PLN",
        }

    if ccy not in FETCH_CURRENCIES:
        raise NbpRateError(
            "unsupported_currency",
            f"NBP fetch supports {', '.join(FETCH_CURRENCIES)} and PLN only; "
            f"{ccy or '(blank)'} is not supported",
        )

    table = fetch_table(accounting_date)
    rate = float(table["rates"].get(ccy) or 0)
    if rate <= 0:
        raise NbpRateError(
            "missing_rate",
            f"NBP table {table['table_number']} has no {ccy} rate",
        )

    return {
        "rate": rate,
        "source": "NBP",
        "table_number": table["table_number"],
        "table_date": table["table_date"],
        "accounting_date": accounting_date,
        "currency": ccy,
    }


def convert(
    source_ccy: str,
    amount: float,
    doc_ccy: str,
    issue_date: str,
) -> Dict[str, Any]:
    """Convert *amount* from source currency to document currency via PLN.

    Always uses one NBP table (same accounting date for both legs)::

        amount_pln = amount_source * rate(source→PLN)
        amount_doc = amount_pln / rate(doc→PLN)
        rate_normalized = rate(source→PLN) / rate(doc→PLN)   # doc per 1 source

    PLN on either leg is identity. Same-currency is a no-op that still attaches
    the accounting PLN equivalent (and table evidence when a foreign currency
    is involved).
    """
    src = str(source_ccy or "").strip().upper()
    doc = str(doc_ccy or "").strip().upper()
    try:
        amt = float(amount)
    except (TypeError, ValueError):
        raise NbpRateError("missing_rate", f"amount must be numeric, got {amount!r}")

    if not src or not is_document_currency(src):
        raise NbpRateError(
            "unsupported_currency",
            f"source currency {source_ccy!r} is not a supported document currency",
            leg="source",
        )
    if not doc or not is_document_currency(doc):
        raise NbpRateError(
            "unsupported_currency",
            f"document currency {doc_ccy!r} is not a supported document currency",
            leg="doc",
        )

    # Identity short-circuit when both PLN — no table needed.
    if src == "PLN" and doc == "PLN":
        return {
            "source_currency": src,
            "doc_currency": doc,
            "amount_source": amt,
            "amount_doc": amt,
            "pln_equivalent": amt,
            "rate_normalized": 1.0,          # doc per 1 source
            "doc_to_pln_rate": 1.0,
            "source_to_pln_rate": 1.0,
            "nbp_table": None,
            "nbp_date": None,
            "accounting_date": issue_date,
            "source": "identity",
            "cross_leg": {
                "source_to_pln": {"rate": 1.0, "table": None, "date": None, "source": "identity"},
                "doc_to_pln":    {"rate": 1.0, "table": None, "date": None, "source": "identity"},
            },
        }

    # One table for both legs (guarantees a consistent cross-rate).
    need_table = src != "PLN" or doc != "PLN"
    table = fetch_table(issue_date) if need_table else None

    def _leg(ccy: str) -> Dict[str, Any]:
        if ccy == "PLN":
            return {"rate": 1.0, "table": None, "date": None, "source": "identity"}
        assert table is not None
        rate = float(table["rates"].get(ccy) or 0)
        if rate <= 0:
            raise NbpRateError(
                "missing_rate",
                f"NBP table {table['table_number']} has no {ccy} rate",
                leg="source" if ccy == src else "doc",
            )
        return {
            "rate": rate,
            "table": table["table_number"],
            "date": table["table_date"],
            "source": "NBP",
        }

    try:
        src_leg = _leg(src)
    except NbpRateError as exc:
        if exc.leg is None:
            exc.leg = "source"
        raise
    try:
        doc_leg = _leg(doc)
    except NbpRateError as exc:
        if exc.leg is None:
            exc.leg = "doc"
        raise

    src_pln = float(src_leg["rate"])
    doc_pln = float(doc_leg["rate"])
    pln_equivalent = round(amt * src_pln, 4)
    amount_doc = round(pln_equivalent / doc_pln, 4) if doc_pln else 0.0
    rate_normalized = round(src_pln / doc_pln, 8) if doc_pln else 0.0

    # Prefer the foreign leg's table evidence; either leg works (same table).
    nbp_table = src_leg["table"] or doc_leg["table"]
    nbp_date = src_leg["date"] or doc_leg["date"]
    source_label = "NBP" if nbp_table else "identity"

    return {
        "source_currency": src,
        "doc_currency": doc,
        "amount_source": amt,
        "amount_doc": amount_doc,
        "pln_equivalent": round(pln_equivalent, 4),
        "rate_normalized": rate_normalized,   # doc currency per 1 source unit
        "doc_to_pln_rate": doc_pln,           # PLN per 1 doc (wFirma exchange_rate)
        "source_to_pln_rate": src_pln,
        "nbp_table": nbp_table,
        "nbp_date": nbp_date,
        "accounting_date": issue_date,
        "source": source_label,
        "cross_leg": {
            "source_to_pln": src_leg,
            "doc_to_pln": doc_leg,
        },
    }


def resolve_source_currency(
    *,
    draft_source_currency: Any = None,
    draft_currency: Any = None,
    lines: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Commercial source currency authority for a draft.

    Prefer the persisted ``source_currency`` (frozen at birth / first FX apply).
    Else the dominant line currency. Else the current document currency.
    Never invents a currency outside the document registry.
    """
    stored = str(draft_source_currency or "").strip().upper()
    if stored and is_document_currency(stored):
        return stored
    counts: Dict[str, int] = {}
    for ln in (lines or []):
        c = str(ln.get("currency") or "").strip().upper()
        if c and is_document_currency(c):
            counts[c] = counts.get(c, 0) + 1
    if counts:
        return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    doc = str(draft_currency or "").strip().upper()
    if doc and is_document_currency(doc):
        return doc
    return "PLN"


def revalue_commercial_snapshot(
    *,
    lines: List[Dict[str, Any]],
    service_charges: List[Dict[str, Any]],
    source_ccy: str,
    doc_ccy: str,
    issue_date: str,
) -> Dict[str, Any]:
    """Revalue editable lines + same-currency service charges via ``convert()``.

    Source commercial authority (original amounts in *source_ccy*) is preserved
    on each line as ``source_unit_price`` / ``source_currency`` when missing, so
    repeated currency changes do not compound. Returns the convert() evidence
    plus the revalued line/charge lists.
    """
    src = str(source_ccy or "").strip().upper()
    doc = str(doc_ccy or "").strip().upper()
    # One convert() call establishes the rate evidence (amount=1).
    evidence = convert(src, 1.0, doc, issue_date)
    rate = float(evidence["rate_normalized"])

    new_lines: List[Dict[str, Any]] = []
    for ln in lines or []:
        out = dict(ln)
        # Freeze source commercial price the first time we revalue.
        if out.get("source_unit_price") in (None, ""):
            try:
                out["source_unit_price"] = float(out.get("unit_price") or 0)
            except (TypeError, ValueError):
                out["source_unit_price"] = 0.0
        if not out.get("source_currency"):
            out["source_currency"] = str(out.get("currency") or src).strip().upper() or src
        try:
            src_price = float(out["source_unit_price"])
        except (TypeError, ValueError):
            src_price = 0.0
        line_src = str(out.get("source_currency") or src).strip().upper() or src
        if line_src == doc:
            out["unit_price"] = round(src_price, 4)
        else:
            conv = convert(line_src, src_price, doc, issue_date)
            out["unit_price"] = conv["amount_doc"]
        out["currency"] = doc
        new_lines.append(out)

    new_charges: List[Dict[str, Any]] = []
    for ch in service_charges or []:
        out = dict(ch)
        ch_ccy = str(out.get("currency") or src).strip().upper() or src
        if out.get("source_amount") in (None, ""):
            try:
                out["source_amount"] = float(out.get("amount") or 0)
            except (TypeError, ValueError):
                out["source_amount"] = 0.0
        if not out.get("source_currency"):
            out["source_currency"] = ch_ccy
        try:
            src_amt = float(out["source_amount"])
        except (TypeError, ValueError):
            src_amt = 0.0
        line_src = str(out.get("source_currency") or ch_ccy).strip().upper() or src
        if line_src == doc:
            out["amount"] = round(src_amt, 4)
        else:
            conv = convert(line_src, src_amt, doc, issue_date)
            out["amount"] = conv["amount_doc"]
        out["currency"] = doc
        new_charges.append(out)

    # PLN equivalent of the revalued goods subtotal (doc × doc→PLN).
    goods_doc = 0.0
    for ln in new_lines:
        try:
            goods_doc += float(ln.get("qty") or 0) * float(ln.get("unit_price") or 0)
        except (TypeError, ValueError):
            pass
    pln_equivalent = round(goods_doc * float(evidence["doc_to_pln_rate"]), 4)

    return {
        **evidence,
        "rate_normalized": rate,
        "lines": new_lines,
        "service_charges": new_charges,
        "pln_equivalent": pln_equivalent,
        "goods_doc_total": round(goods_doc, 4),
    }
