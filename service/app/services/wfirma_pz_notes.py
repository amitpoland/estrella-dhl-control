"""
wfirma_pz_notes.py — Compact audit-trail formatter for the wFirma PZ
`<description>` field (the operator-visible "Uwagi" column on the
posted document).

Builds an 8-line compact note from the current batch's `audit.json`:

    INV:<invoice_no>
    AWB:<awb>
    MRN:<mrn>
    SAD:<lrn-or-own-number>
    VAT:Art33a              (only when art33a is evidenced)
    NBP:<table> USD=<rate>
    SUP:<short-supplier>
    CA:<short-customs-agent>

Design rules
------------
* **Single authority** — every value is pulled from `audit` (or
  `batch_id` for the AWB fallback). No external lookups, no DB reads,
  no HTTP calls. Pure function.
* **No placeholders** — missing fields produce *no line*. The output
  never contains `UNKNOWN`, `None`, `null`, `<…>`, or any sentinel
  string. If everything is missing, the function returns `""`.
* **Fixed line order** — lines are emitted in `LINE_KEYS` order.
* **ASCII-safe by default** — non-ASCII characters are preserved only
  when they already exist in the source field (Polish names like
  "Agencja Celna Spedycja").
* **Length cap** — output is truncated at `MAX_NOTE_LEN` characters,
  cleanly at a line boundary, to stay well inside wFirma's
  description-field practical limit.

The helper is consumed by `routes_wfirma.wfirma_pz_preview`,
`wfirma_products_resolve`, and `wfirma_pz_create`, which pass the
result through `import_pz_builder.build_pz_request_from_batch`'s
new `description_override` kwarg into the PZ XML's
`<description>` element.

This module never touches existing wFirma PZ documents. Issued
documents keep whatever description was active at create time.
"""
from __future__ import annotations

import re as _re
from typing import Any, Dict, List, Optional, Tuple


# ── Public constants ─────────────────────────────────────────────────────────

MAX_NOTE_LEN: int = 500

LINE_KEYS: Tuple[str, ...] = (
    "INV", "AWB", "MRN", "SAD", "VAT", "NBP", "SUP", "CA",
)


# ── Internal value extractors ────────────────────────────────────────────────

def _s(value: Any) -> str:
    """Coerce to a stripped string. None / non-strings become ''."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _first_nonempty(*candidates: Any) -> str:
    for c in candidates:
        s = _s(c)
        if s:
            return s
    return ""


def _invoice_no(audit: Dict[str, Any]) -> str:
    """Priority chain — see `routes_dhl_clearance` invoice-position authority."""
    sidecar_rows = audit.get("_pz_engine_authority_rows")
    if isinstance(sidecar_rows, list) and sidecar_rows:
        first = sidecar_rows[0]
        if isinstance(first, dict):
            inv = _s(first.get("invoice_number"))
            if inv:
                return inv
    rows = audit.get("rows")
    if isinstance(rows, list) and rows:
        first = rows[0]
        if isinstance(first, dict):
            inv = _s(first.get("invoice_number")) or _s(first.get("invoice_no"))
            if inv:
                return inv
    direct = _s(audit.get("invoice_no"))
    if direct:
        return direct
    names = audit.get("invoice_names")
    if isinstance(names, list) and names:
        # Strip file extension and common date suffix patterns.
        stem = _s(names[0])
        if stem:
            stem = _re.sub(r"\.(pdf|xls[xm]?|jpg|jpeg|png)$", "", stem, flags=_re.IGNORECASE)
            return stem
    return ""


def _awb(audit: Dict[str, Any], batch_id: str) -> str:
    """Priority: audit.awb → audit.tracking_no → batch_id middle token.

    `batch_id` is canonically `SHIPMENT_<awb>_<yyyy-mm>_<hash>`. The
    AWB falls between the two underscores.
    """
    direct = _first_nonempty(audit.get("awb"), audit.get("tracking_no"))
    if direct:
        return direct
    bid = _s(batch_id)
    if bid.startswith("SHIPMENT_"):
        parts = bid.split("_")
        if len(parts) >= 3 and parts[1] and parts[1] != "AUTO":
            return parts[1]
    return ""


def _mrn(audit: Dict[str, Any]) -> str:
    cd = audit.get("customs_declaration") or {}
    inputs = audit.get("inputs") or {}
    zc = audit.get("zc429") or {}
    return _first_nonempty(
        cd.get("mrn"),
        inputs.get("zc429_mrn"),
        zc.get("mrn"),
    )


def _sad_ref(audit: Dict[str, Any]) -> str:
    """SAD reference — own_number / sad_own_number / LRN (operator's
    `26S00SV10S` example matches the LRN field in current audits)."""
    cd = audit.get("customs_declaration") or {}
    zc = audit.get("zc429") or {}
    return _first_nonempty(
        cd.get("own_number"),
        cd.get("sad_own_number"),
        zc.get("own_number"),
        zc.get("sad_own_number"),
        cd.get("lrn"),
        zc.get("lrn"),
    )


def _is_art33a(audit: Dict[str, Any]) -> bool:
    cd = audit.get("customs_declaration") or {}
    clr = audit.get("clearance_decision") or {}
    if cd.get("art33a") is True:
        return True
    if _s(cd.get("vat_mode")).lower() == "art33a":
        return True
    if _s(audit.get("settlement_mode")).lower() == "art33a":
        return True
    if clr.get("article_33a") is True:
        return True
    return False


def _nbp(audit: Dict[str, Any]) -> Tuple[str, Optional[float]]:
    """Return (table, rate) pair. Both required for the NBP line — if
    either is missing the caller omits the line entirely."""
    cd = audit.get("customs_declaration") or {}
    inputs = audit.get("inputs") or {}
    it = audit.get("invoice_totals") or {}
    v = audit.get("verification") or {}

    table = _first_nonempty(
        cd.get("nbp_table"),
        inputs.get("nbp_table"),
        it.get("nbp_table"),
        it.get("exchange_rate_table"),
        v.get("exchange_rate_table"),
    )
    rate: Optional[float] = None
    for cand in (cd.get("nbp_rate"), inputs.get("nbp_rate_usd"),
                 it.get("nbp_rate_usd"), v.get("nbp_rate_used")):
        if cand is None or cand == "":
            continue
        try:
            f = float(cand)
            if f > 0:
                rate = f
                break
        except (TypeError, ValueError):
            continue
    return table, rate


_SUPPLIER_TRAIL_RE = _re.compile(
    r"\s*(?:"
    r"Pvt\.?\s*Ltd\.?"          # "Pvt. Ltd." / "Pvt Ltd"
    r"|Private\s+Limited"
    r"|LLP\.?"                  # "LLP." / "LLP"
    r"|Sp\.?\s*z\s*o\.?\s*o\.?" # "Sp. z o.o."
    r"|Sp\.?\s*K\.?"            # "Sp. K."
    r"|S\.?\s*A\.?"             # "S.A."
    r"|Inc\.?"
    r"|Ltd\.?"
    r"|Limited"
    r"|GmbH"
    r"|N\.?V\.?"
    r"|B\.?V\.?"
    r"|S\.?\s*r\.?\s*o\.?"
    r")(?:\s*,?\s*(?:Pvt\.?\s*Ltd\.?|LLP\.?|Sp\.?\s*z\s*o\.?\s*o\.?|Sp\.?\s*K\.?))*\s*\.?\s*$",
    _re.IGNORECASE,
)


def _supplier_short(raw: str) -> str:
    """Strip trailing legal-entity suffixes; preserve original casing
    for the remaining words but apply Title Case when the input is all-
    upper (operator example: `ESTRELLA JEWELS SP. Z O.O.` → `Estrella
    Jewels`)."""
    s = _s(raw)
    if not s:
        return ""
    # Iteratively strip suffixes — some inputs stack multiple ("LLP. SP. K.").
    prev = None
    while prev != s:
        prev = s
        s = _SUPPLIER_TRAIL_RE.sub("", s).strip().rstrip(",.;")
    # If the remaining string is all-upper-case (or upper-with-spaces),
    # apply Title Case for legibility. Don't touch mixed-case strings.
    letters = [c for c in s if c.isalpha()]
    if letters and all(c.isupper() for c in letters):
        s = s.title()
    return s


def _supplier(audit: Dict[str, Any]) -> str:
    v = audit.get("verification") or {}
    cd = audit.get("customs_declaration") or {}
    raw = _first_nonempty(
        v.get("invoice_exporter_name"),
        audit.get("supplier_name"),
        audit.get("exporter_name"),
        cd.get("exporter_name"),
    )
    return _supplier_short(raw)


# Known agency-name normalisations. Order matters — first match wins.
_AGENCY_NORMALISATIONS: List[Tuple[str, str]] = [
    (r"agencja\s+celna\s+spedycja",      "Agencja Celna Spedycja"),
    (r"dhl\s+express",                    "DHL Express PL"),
]


def _customs_agent(audit: Dict[str, Any]) -> str:
    """DHL self-clearance produces `DHL Express PL`; agency clearance
    surfaces the agency short name from `clearance_decision.agency`
    (preferred — already curated) or `customs_declaration.customs_agent`
    (raw — apply normalisation)."""
    cd = audit.get("customs_declaration") or {}
    clr = audit.get("clearance_decision") or {}
    carrier = _s(audit.get("carrier")).upper()

    clearance_path = _s(clr.get("clearance_path")).lower()
    if clearance_path == "self_clearance" and carrier == "DHL":
        return "DHL Express PL"

    candidate = _first_nonempty(
        clr.get("agency"),
        cd.get("customs_agent"),
        cd.get("agent"),
        clr.get("agent"),
    )
    if not candidate:
        # Last-resort default: DHL-cleared shipments without explicit
        # agency carry "DHL Express PL".
        if carrier == "DHL" and clearance_path in ("", "self_clearance",
                                                   "dhl_clearance"):
            return "DHL Express PL"
        return ""

    low = candidate.lower()
    for pattern, norm in _AGENCY_NORMALISATIONS:
        if _re.search(pattern, low):
            return norm
    # Cap raw agency name length; strip "Kuźmicz K." / personal-name
    # trailing suffix beyond the first three words for compactness.
    words = candidate.split()
    if len(words) > 3:
        return " ".join(words[:3])
    return candidate


# ── Public API ───────────────────────────────────────────────────────────────

def build_wfirma_pz_notes(audit: Dict[str, Any], batch_id: str) -> str:
    """Build the 8-key compact audit-trail string for the wFirma PZ
    `<description>` field.

    Lines whose source is missing are omitted entirely. Returns ``""``
    when no key could be populated.
    """
    if not isinstance(audit, dict):
        return ""

    parts: List[str] = []

    inv = _invoice_no(audit)
    if inv:
        parts.append(f"INV:{inv}")

    awb = _awb(audit, batch_id)
    if awb:
        parts.append(f"AWB:{awb}")

    mrn = _mrn(audit)
    if mrn:
        parts.append(f"MRN:{mrn}")

    sad = _sad_ref(audit)
    if sad:
        parts.append(f"SAD:{sad}")

    if _is_art33a(audit):
        parts.append("VAT:Art33a")

    nbp_table, nbp_rate = _nbp(audit)
    if nbp_table and nbp_rate is not None and nbp_rate > 0:
        # 4-decimal formatting matches the wFirma NBP rate convention.
        parts.append(f"NBP:{nbp_table} USD={nbp_rate:.4f}")

    sup = _supplier(audit)
    if sup:
        parts.append(f"SUP:{sup}")

    ca = _customs_agent(audit)
    if ca:
        parts.append(f"CA:{ca}")

    if not parts:
        return ""

    # Truncate at a line boundary if the assembled output would exceed
    # the cap. We accumulate lines greedily — every line kept must fit
    # in full, including the line break separator.
    out: List[str] = []
    running = 0
    for line in parts:
        sep_len = 1 if out else 0   # "\n" between consecutive lines
        cost = len(line) + sep_len
        if running + cost > MAX_NOTE_LEN:
            break
        out.append(line)
        running += cost

    return "\n".join(out)
