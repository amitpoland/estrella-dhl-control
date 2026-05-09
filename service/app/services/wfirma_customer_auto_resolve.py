"""
wfirma_customer_auto_resolve.py — Batch customer-name resolver for the
Proforma readiness gate.

Read-first, never creates. The service walks distinct client names from
``sales_documents`` (primary) and ``sales_packing_lines`` (fallback),
normalizes each, and resolves against the local ``wfirma_customers``
table first — falling through to a live wFirma ``contractors/find``
search only when local lookup misses. Any successful resolution is
mirrored into both ``wfirma_customers`` (master mirror) and
``reservation_queue.wfirma_customer_mapping`` (parallel registry the
reservation worker consults), keeping both registries consistent.

Hard rules
----------
* NEVER calls ``wfirma_client.create_customer``. The single-customer
  create path remains operator-only.
* NEVER mutates live wFirma data (only the local mirror tables).
* Honors no flag — read-only by definition.
* Idempotent: re-running on the same batch updates the same rows in
  place; ``UNIQUE(client_name)`` constraints prevent duplicates.

Per-name result statuses
------------------------
``exact_match``       Local ``wfirma_customers`` row matched by exact
                       (case-insensitive) ``client_name``.
``normalized_match``  After whitespace strip + case-fold the local row
                       matches; the raw input had stray whitespace.
``prefix_match``      Local row's stored name starts with the input
                       (e.g. input ``"Clear-Diamonds"`` → stored
                       ``"Clear-Diamonds Ltd"``). Auto-resolves only
                       when EXACTLY ONE candidate matches.
``reverse_prefix_match`` Input starts with the stored name (covers the
                       symmetric case).
``ambiguous``         Multiple prefix candidates → no auto-pick;
                       ``candidates`` lists every match.
``missing``           Zero candidates locally; live ``contractors/find``
                       (when configured) also returned no result.
``invalid_name``      Empty / whitespace-only after normalization.

Public API
----------
``ensure_customers_for_batch(batch_id, *, dry_run=True) -> dict``

Returns::

    {
      'batch_id':           str,
      'dry_run':            bool,           # always True for now
      'scanned':            int,
      'exact_match':        int,
      'normalized_match':   int,
      'prefix_match':       int,
      'reverse_prefix_match': int,
      'ambiguous':          int,
      'missing':            int,
      'invalid_name':       int,
      'errors':             [str],
      'results': [
         {
           'raw_name':            str,
           'normalized_name':     str,
           'status':              <one of the values above>,
           'wfirma_customer_id':  str | '',
           'matched_name':        str,
           'candidates':          [str],
           'warnings':            [str],
         },
         ...
      ],
    }
"""
from __future__ import annotations

import logging
import re
import sqlite3
from typing import Any, Dict, List, Optional

from ..core.config import settings
from . import wfirma_db as wfdb

log = logging.getLogger(__name__)


# ── Name normalization (mirrors the Proforma resolver behaviour) ──────────
def _normalize_name(raw: str) -> str:
    """Strip outer whitespace and collapse internal whitespace to single
    space. Case is preserved in the returned form; comparison is done
    case-insensitively elsewhere."""
    if not raw:
        return ""
    return re.sub(r"\s+", " ", raw.strip())


# ── VAT normalization (identity-first resolution) ─────────────────────────
# VAT IDs across systems show up in multiple forms:
#   "PL 525-281-21-19"      operator copy-paste from invoice
#   "PL5252812119"          canonical EU form
#   "5252812119"            stripped (Polish bare NIP)
#   " pl5252812119 "        stray whitespace, lowercase
# All four are the same identity. The normalizer reduces every variant
# to a canonical uppercase string with no separators. Comparison helpers
# also try the bare form (without 2-letter country prefix) so a stored
# "5252812119" matches an input "PL5252812119".

# Two-letter ISO country codes that legitimately prefix EU VAT numbers.
# We use this list to detect when a leading 2-letter token is the
# country prefix vs part of the actual VAT number.
_EU_COUNTRY_VAT_PREFIXES = frozenset({
    "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "EL", "ES", "FI",
    "FR", "GB", "GR", "HR", "HU", "IE", "IT", "LT", "LU", "LV", "MT",
    "NL", "PL", "PT", "RO", "SE", "SI", "SK", "XI",
})


def _normalize_vat(vat_id: str) -> str:
    """Reduce a VAT/NIP string to its canonical comparison form.

    Uppercases the input, removes spaces, hyphens, dots, slashes, and
    colons. Returns the empty string for ``None`` / empty input. Does
    NOT strip the country prefix here — that's handled by the variant
    list so a normalized form retains the prefix when present.
    """
    if not vat_id:
        return ""
    s = re.sub(r"[\s\-\.\/:]+", "", str(vat_id)).upper()
    return s


def _vat_variants(vat_id: str, country_code: str = "") -> List[str]:
    """All equivalent canonical forms of a VAT id that should match each
    other. Returned with no duplicates and no empty strings.

    Examples
    --------
    ``_vat_variants("PL5252812119")``           → ``["PL5252812119", "5252812119"]``
    ``_vat_variants("5252812119", "PL")``       → ``["5252812119", "PL5252812119"]``
    ``_vat_variants("HU 32207880")``            → ``["HU32207880", "32207880"]``
    ``_vat_variants("")`` / ``_vat_variants(None)`` → ``[]``
    """
    norm = _normalize_vat(vat_id)
    if not norm:
        return []
    cc = (country_code or "").strip().upper()
    variants: List[str] = [norm]

    # If the normalized VAT starts with a known EU country prefix and
    # the rest is digit-heavy, also try the bare form.
    if (len(norm) >= 4 and norm[:2] in _EU_COUNTRY_VAT_PREFIXES
            and norm[2:].isalnum()):
        bare = norm[2:]
        if bare and bare not in variants:
            variants.append(bare)

    # If a country code was supplied separately and the VAT has no
    # prefix, also try the prefixed form.
    if cc and cc in _EU_COUNTRY_VAT_PREFIXES:
        with_prefix = cc + norm
        if with_prefix not in variants and (
            len(norm) < 2 or norm[:2] not in _EU_COUNTRY_VAT_PREFIXES
        ):
            variants.append(with_prefix)

    return variants


def _vat_matches(stored_vat: str, input_variants: List[str],
                 stored_country: str = "", input_country: str = "") -> bool:
    """True when any variant of the input VAT matches the stored VAT
    (under normalization). Country code is treated as supplementary —
    if both sides supply one and they differ, that's a soft signal but
    NOT a disqualifier on its own (operators commonly leave country
    blank in one place)."""
    if not stored_vat:
        return False
    stored_norm = _normalize_vat(stored_vat)
    if not stored_norm:
        return False
    stored_set = set(_vat_variants(stored_norm, stored_country))
    return any(v in stored_set for v in input_variants)


# ── Source: distinct client names from sales tables ──────────────────────
def _collect_client_names(batch_id: str) -> List[str]:
    """Read DISTINCT client_name values from sales_documents (primary).
    Falls back to sales_packing_lines when sales_documents is empty for
    the batch. Names are returned in the raw form they were stored —
    normalization happens per-name during resolution so the diagnostic
    can show the original spelling."""
    try:
        from . import document_db as ddb
        # Prefer sales_documents
        if ddb._db_path is None:
            return []
        with sqlite3.connect(str(ddb._db_path)) as con:
            con.row_factory = sqlite3.Row
            rows = con.execute(
                "SELECT DISTINCT client_name FROM sales_documents "
                "WHERE batch_id=? AND client_name <> ''",
                (batch_id,),
            ).fetchall()
            if rows:
                return [r["client_name"] for r in rows]
            # Fallback to sales_packing_lines
            rows = con.execute(
                "SELECT DISTINCT client_name FROM sales_packing_lines "
                "WHERE batch_id=? AND client_name <> ''",
                (batch_id,),
            ).fetchall()
            return [r["client_name"] for r in rows]
    except Exception as exc:
        log.warning("[customer_auto_resolve] sales-name read failed: %s", exc)
        return []


# ── VAT-first lookups (local + live) ─────────────────────────────────────

def _resolve_local_by_vat(input_variants: List[str],
                          input_country: str = "") -> List[Dict[str, Any]]:
    """Walk wfirma_customers and return EVERY row whose stored VAT
    matches any of the input variants. Empty list when no match."""
    if not input_variants:
        return []
    out: List[Dict[str, Any]] = []
    rows = wfdb.list_customers()
    for row in rows:
        if not row.get("wfirma_customer_id"):
            continue
        if _vat_matches(
            stored_vat     = row.get("vat_id", "") or "",
            input_variants = input_variants,
            stored_country = (row.get("country", "") or "").upper(),
            input_country  = input_country,
        ):
            out.append(row)
    return out


def _search_live_by_vat(vat_id: str) -> List[Dict[str, str]]:
    """Live wFirma contractors/find by NIP. Uses the existing client
    helper which already accepts a ``nip`` parameter and matches via
    ``operator=eq`` (exact). Returns a list (0 or 1 rows from
    search_customer's LIMIT 1; for >1 we'd need a multi-candidate
    helper, but VAT eq-matches almost always return at most one row).
    """
    if not vat_id:
        return []
    try:
        from . import wfirma_client as _wfc
        contractor = _wfc.search_customer("", nip=vat_id)
    except Exception as exc:
        log.info("[customer_auto_resolve] live VAT search failed for %r: %s",
                 vat_id, exc)
        return []
    if contractor is None:
        return []
    return [{
        "wfirma_id": contractor.wfirma_id,
        "name":      contractor.name or "",
        "nip":       contractor.nip or vat_id,
        "country":   contractor.country or "",
    }]


# ── Local-only resolution (case-insensitive + prefix tolerance) ──────────
def _resolve_local(normalized: str) -> Dict[str, Any]:
    """Try every local-only strategy. Returns the same shape as the
    public per-name result minus the live-search fallback step."""
    out: Dict[str, Any] = {
        "status":             "missing",
        "wfirma_customer_id": "",
        "matched_name":       "",
        "candidates":         [],
    }
    if not normalized:
        return out

    # 1. Exact match (wfdb.get_customer is case-insensitive on UPPER).
    cust = wfdb.get_customer(normalized)
    if cust and cust.get("wfirma_customer_id"):
        out.update({
            "status":             "exact_match",
            "wfirma_customer_id": cust["wfirma_customer_id"],
            "matched_name":       cust.get("client_name", "") or normalized,
        })
        return out

    # 2. Walk all rows for normalized / prefix / reverse-prefix candidates.
    norm_lc = normalized.lower()
    rows = wfdb.list_customers()
    prefix_rows: List[Dict[str, Any]] = []
    reverse_rows: List[Dict[str, Any]] = []
    for row in rows:
        wf_name = (row.get("client_name") or "").strip()
        if not wf_name or not row.get("wfirma_customer_id"):
            continue
        wf_norm_lc = _normalize_name(wf_name).lower()
        if wf_norm_lc == norm_lc:
            out.update({
                "status":             "normalized_match",
                "wfirma_customer_id": row["wfirma_customer_id"],
                "matched_name":       wf_name,
            })
            return out
        if wf_norm_lc.startswith(norm_lc + " ") or wf_norm_lc.startswith(norm_lc + ","):
            prefix_rows.append(row)
        elif norm_lc.startswith(wf_norm_lc + " ") or norm_lc.startswith(wf_norm_lc + ","):
            reverse_rows.append(row)

    if len(prefix_rows) == 1:
        row = prefix_rows[0]
        out.update({
            "status":             "prefix_match",
            "wfirma_customer_id": row["wfirma_customer_id"],
            "matched_name":       row["client_name"],
        })
        return out

    if len(prefix_rows) > 1:
        out.update({
            "status":     "ambiguous",
            "candidates": [r["client_name"] for r in prefix_rows],
        })
        return out

    if len(reverse_rows) == 1:
        row = reverse_rows[0]
        out.update({
            "status":             "reverse_prefix_match",
            "wfirma_customer_id": row["wfirma_customer_id"],
            "matched_name":       row["client_name"],
        })
        return out

    if len(reverse_rows) > 1:
        out.update({
            "status":     "ambiguous",
            "candidates": [r["client_name"] for r in reverse_rows],
        })
        return out

    return out


# ── Live wFirma fallback (search-only, never creates) ────────────────────
#
# wfirma_client.search_customer issues a contractors/find with LIMIT 1, so
# it cannot detect ambiguity — a substring-LIKE match like "OMARA" would
# silently pick whichever single contractor the API decides to return out
# of "OMARA s.r.o", "OMARA TRADING SP. Z O.O.", etc.
#
# The multi-candidate helper below issues the same query with a higher
# limit so we see every candidate, then applies the SAME resolution rules
# the local resolver uses (exact / normalized / prefix / reverse_prefix /
# ambiguous). Auto-mirror only happens when EXACTLY ONE safe candidate
# survives. Multiple candidates surface as `ambiguous` with the full
# candidate list and NO mirror writes.
#
# Never calls create_customer. Never raises.

_LIVE_CANDIDATE_LIMIT = 20


def _search_live_candidates(normalized: str) -> List[Dict[str, str]]:
    """Issue a contractors/find LIKE query with a higher LIMIT and return
    EVERY contractor row in the response. Returns an empty list on
    miss / error (errors logged at info level; never raised).

    Each row dict carries: wfirma_id, name, nip, country.
    """
    if not normalized:
        return []
    try:
        # Borrow the existing private helpers — search_customer does the
        # same. Limit is widened from 1 to _LIVE_CANDIDATE_LIMIT so we
        # can detect ambiguity instead of silently picking the first row.
        from . import wfirma_client as _wfc
        body = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<api>'
            '  <contractors>'
            '    <parameters>'
            '      <conditions>'
            '        <condition>'
            f'          <field>name</field>'
            f'          <operator>like</operator>'
            f'          <value>%{_wfc._esc(normalized)}%</value>'
            '        </condition>'
            '      </conditions>'
            f'      <page><start>0</start><limit>{_LIVE_CANDIDATE_LIMIT}</limit></page>'
            '    </parameters>'
            '  </contractors>'
            '</api>'
        )
        http_status, response_text = _wfc._http_request(
            "GET", "contractors", "find", body,
        )
        if http_status >= 400:
            log.info("[customer_auto_resolve] live search HTTP %d for %r",
                     http_status, normalized)
            return []
        code, desc = _wfc._parse_status(response_text)
        if code != "OK":
            log.info("[customer_auto_resolve] live search wFirma status=%s "
                     "for %r: %s", code, normalized, desc)
            return []
        import xml.etree.ElementTree as ET
        root = ET.fromstring(response_text)
        out: List[Dict[str, str]] = []
        for node in root.findall(".//contractor"):
            out.append({
                "wfirma_id": _wfc._find_text(node, "id"),
                "name":      _wfc._find_text(node, "name"),
                "nip":       _wfc._find_text(node, "nip"),
                "country":   _wfc._find_text(node, "country"),
            })
        return [c for c in out if c.get("wfirma_id")]
    except Exception as exc:
        log.info("[customer_auto_resolve] live search failed for %r: %s",
                 normalized, exc)
        return []


def _resolve_live(normalized: str) -> Dict[str, Any]:
    """Live wFirma fallback that mirrors the local resolver's strategy
    on the multi-candidate response. Returns the same per-name shape as
    `_resolve_local` (without writing anything yet).

    Result statuses on this side:
      ``exact_match``         single candidate whose normalized name == input
      ``prefix_match``        single candidate whose name starts with input
                              (token-boundary safe)
      ``reverse_prefix_match`` single candidate that input starts with
      ``ambiguous``           2+ candidates after applying the same
                              token-boundary filter as local
      ``missing``             zero candidates after filtering
    """
    out: Dict[str, Any] = {
        "status":             "missing",
        "wfirma_customer_id": "",
        "matched_name":       "",
        "candidates":         [],
        "country":            "",
        "vat_id":             "",
        "live_candidate_count": 0,
        "candidate_names":    [],
    }
    if not normalized:
        return out

    rows = _search_live_candidates(normalized)
    out["live_candidate_count"] = len(rows)
    out["candidate_names"]      = [r["name"] for r in rows if r.get("name")]
    if not rows:
        return out

    norm_lc = normalized.lower()
    exact:  Optional[Dict[str, str]] = None
    prefix: List[Dict[str, str]] = []
    rev:    List[Dict[str, str]] = []

    for r in rows:
        wf_name = (r.get("name") or "").strip()
        if not wf_name:
            continue
        wf_norm_lc = _normalize_name(wf_name).lower()
        if wf_norm_lc == norm_lc:
            # First exact wins (case-insensitive on normalized form).
            if exact is None:
                exact = r
            else:
                # Two exact matches under the same normalized form is
                # the strongest ambiguity signal — list all of them.
                prefix.append(r)
        elif wf_norm_lc.startswith(norm_lc + " ") or \
             wf_norm_lc.startswith(norm_lc + ","):
            prefix.append(r)
        elif norm_lc.startswith(wf_norm_lc + " ") or \
             norm_lc.startswith(wf_norm_lc + ","):
            rev.append(r)
        # Substring-only matches that are NOT token-boundary aligned
        # (e.g. wFirma row "FOOBAR LTD" returned for input "FOO") are
        # silently dropped. wFirma's LIKE %FOO% may surface these; we
        # never auto-mirror them.

    # 1. Single exact match — best signal, highest confidence.
    if exact is not None and not prefix:
        out.update({
            "status":             "exact_match",
            "wfirma_customer_id": exact["wfirma_id"],
            "matched_name":       exact["name"],
            "country":            exact.get("country", ""),
            "vat_id":             exact.get("nip", ""),
        })
        return out

    # 2. Single prefix candidate (no competing exact).
    if exact is None and len(prefix) == 1 and not rev:
        r = prefix[0]
        out.update({
            "status":             "prefix_match",
            "wfirma_customer_id": r["wfirma_id"],
            "matched_name":       r["name"],
            "country":            r.get("country", ""),
            "vat_id":             r.get("nip", ""),
        })
        return out

    # 3. Single reverse-prefix candidate.
    if exact is None and not prefix and len(rev) == 1:
        r = rev[0]
        out.update({
            "status":             "reverse_prefix_match",
            "wfirma_customer_id": r["wfirma_id"],
            "matched_name":       r["name"],
            "country":            r.get("country", ""),
            "vat_id":             r.get("nip", ""),
        })
        return out

    # 4. Anything else: ambiguity — never auto-pick.
    if (exact is not None) or prefix or rev:
        all_safe = ([exact] if exact else []) + prefix + rev
        names = [r["name"] for r in all_safe if r.get("name")]
        out.update({
            "status":     "ambiguous",
            "candidates": names,
        })
        return out

    # All raw substring hits failed token-boundary safety → effectively missing.
    return out


# ── Mirror successful resolution into local registries ───────────────────
def _reservation_db_path():
    return settings.storage_root / "reservation_queue.db"


def _log_correction_safe(**kwargs) -> str:
    """Append-only correction-registry logging that never raises.

    Returns a warning string ("" on success). Logging failures must NOT
    break the operator action — callers append the warning to the
    result's `warnings` list.
    """
    try:
        from . import correction_registry as _cr
        _cr.record_correction(**kwargs)
        return ""
    except Exception as exc:  # pragma: no cover (defensive)
        return f"correction_registry log failed: {type(exc).__name__}: {exc}"


_ACCEPTED_LOCAL_LIVE_STATES = (
    "exact_match", "normalized_match",
    "prefix_match", "reverse_prefix_match",
)
_REJECTED_AMBIGUOUS_STATES = ("ambiguous", "ambiguous_vat")


def _mirror_resolution(
    *,
    raw_name:           str,
    normalized:         str,
    wfirma_customer_id: str,
    matched_name:       str,
    country:            str = "",
    vat_id:             str = "",
) -> List[str]:
    """Update both registries (wfirma_customers + wfirma_customer_mapping)
    with a confirmed match. Returns a list of warnings (non-fatal); empty
    on success."""
    warnings: List[str] = []

    # 1. Master mirror — wfirma_db.upsert_customer keys on client_name.
    #    We mirror under the NORMALIZED name so future lookups by either
    #    raw or normalized form succeed via the same row.
    try:
        wfdb.upsert_customer(
            client_name        = normalized or raw_name,
            wfirma_customer_id = wfirma_customer_id,
            vat_id             = vat_id,
            country            = country,
            match_status       = "matched",
        )
    except Exception as exc:
        warnings.append(
            f"wfirma_customers mirror failed: {type(exc).__name__}: {exc}"
        )

    # 2. Parallel registry — reservation_queue.wfirma_customer_mapping.
    rdb_path = _reservation_db_path()
    try:
        if not rdb_path or not rdb_path.exists():
            warnings.append(
                f"reservation_queue.db not found at {rdb_path}"
            )
        else:
            from . import reservation_db
            reservation_db.upsert_wfirma_customer_mapping(
                rdb_path,
                client_name        = normalized or raw_name,
                wfirma_customer_id = wfirma_customer_id,
                vat_id             = vat_id,
                country            = country,
                match_status       = "matched",
            )
    except Exception as exc:
        warnings.append(
            f"wfirma_customer_mapping mirror failed: {type(exc).__name__}: {exc}"
        )

    return warnings


# ── Per-name resolver ────────────────────────────────────────────────────
def _maybe_log_resolution(
    result: Dict[str, Any],
    *,
    raw_name:       str,
    input_vat:      str,
    operator:       str,
    batch_id:       str,
    module_source:  str,
) -> None:
    """Append-only logging hook for resolver outcomes.

    Logs only deterministic, operator-meaningful outcomes:
      • accepted_match — when the resolver uniquely mirrored an
        existing wFirma contractor (local or live).
      • rejected_match — when the resolver returned an ambiguous
        candidate set (operator must pick).

    Pure misses, invalid_name, or empty results are NOT logged.
    Logging failures append a warning into ``result["warnings"]``
    but never raise.
    """
    status = result.get("status") or ""
    entity_key = (result.get("normalized_name") or raw_name or "").strip()
    if not entity_key:
        return

    if status in _ACCEPTED_LOCAL_LIVE_STATES:
        warn = _log_correction_safe(
            correction_type = "accepted_match",
            entity_type     = "customer",
            entity_key      = entity_key,
            old_value       = raw_name or "",
            new_value       = {
                "wfirma_customer_id": result.get("wfirma_customer_id", ""),
                "matched_name":       result.get("matched_name", ""),
                "matched_vat_id":     result.get("matched_vat_id", ""),
                "matched_country":    result.get("matched_country", ""),
                "resolution_source":  result.get("resolution_source", ""),
                "resolution_identity": result.get("resolution_identity", ""),
            },
            batch_id        = batch_id,
            operator        = operator,
            module_source   = module_source,
            confidence      = 1.0,
            approved        = True,
            notes           = status,
            evidence_refs   = [
                {"type": "endpoint",         "ref":
                    "/api/v1/wfirma/customers/auto-resolve-preview"},
                {"type": "client_name",      "ref": raw_name or ""},
                {"type": "input_vat",        "ref": input_vat or ""},
                {"type": "resolution_source", "ref":
                    result.get("resolution_source", "")},
            ],
        )
        if warn:
            result.setdefault("warnings", []).append(warn)
        return

    if status in _REJECTED_AMBIGUOUS_STATES:
        warn = _log_correction_safe(
            correction_type = "rejected_match",
            entity_type     = "customer",
            entity_key      = entity_key,
            old_value       = raw_name or "",
            new_value       = {
                "candidates":          list(result.get("candidates") or []),
                "resolution_source":   result.get("resolution_source", ""),
                "resolution_identity": result.get("resolution_identity", ""),
            },
            batch_id        = batch_id,
            operator        = operator,
            module_source   = module_source,
            confidence      = 0.0,
            approved        = False,
            notes           = status,
            evidence_refs   = [
                {"type": "endpoint",     "ref":
                    "/api/v1/wfirma/customers/auto-resolve-preview"},
                {"type": "client_name",  "ref": raw_name or ""},
                {"type": "input_vat",    "ref": input_vat or ""},
            ],
        )
        if warn:
            result.setdefault("warnings", []).append(warn)
        return
    # Any other status (missing / invalid_name / empty) → no log.


def _resolve_one(
    raw_name: str,
    *,
    input_vat:     str = "",
    input_country: str = "",
    operator:      str = "operator",
    batch_id:      str = "",
    module_source: str = "wfirma_customer_auto_resolve",
) -> Dict[str, Any]:
    """Public wrapper: runs the core resolver, then appends an
    operator-correction-registry log entry for accepted / ambiguous
    outcomes only. The core's signature and behaviour are unchanged."""
    result = _resolve_one_core(
        raw_name,
        input_vat     = input_vat,
        input_country = input_country,
    )
    _maybe_log_resolution(
        result,
        raw_name      = raw_name,
        input_vat     = input_vat,
        operator      = operator,
        batch_id      = batch_id,
        module_source = module_source,
    )
    return result


def _resolve_one_core(
    raw_name: str,
    *,
    input_vat:     str = "",
    input_country: str = "",
) -> Dict[str, Any]:
    """Resolve a single contractor identity end-to-end.

    Priority (highest to lowest):
      A. VAT exact / normalized match (local, then live)
      B. Country + VAT match (handled by VAT variant list)
      C. Exact normalized legal-name match (local, then live)
      D. Prefix / reverse-prefix fallback
      E. Ambiguous (multi-candidate)
      F. Missing

    VAT identifies a contractor; name only fingerprints them. When
    ``input_vat`` is supplied, the resolver tries VAT first and falls
    back to the existing name path only when VAT lookup returns zero
    matches (a typo or truly new contractor).
    """
    out: Dict[str, Any] = {
        "raw_name":             raw_name,
        "normalized_name":      "",
        "status":               "",
        "wfirma_customer_id":   "",
        "matched_name":         "",
        "candidates":           [],
        "warnings":             [],
        # Diagnostics for the operator UI / test surface.
        "resolution_source":    "",      # "local" | "live" | ""
        "resolution_identity":  "none",  # "vat" | "name" | "prefix"
                                          # | "reverse_prefix" | "none"
        "live_candidate_count": 0,
        "candidate_names":      [],      # raw names returned by wFirma
        "matched_vat_id":       "",
        "matched_country":      "",
        "vat_match_confidence": "",      # "exact" | ""
    }

    normalized = _normalize_name(raw_name)
    out["normalized_name"] = normalized
    if not normalized:
        out["status"] = "invalid_name"
        return out

    # ── VAT-first identity resolution (when caller supplied a VAT) ────────
    # This wins over any name-based logic per the resolver contract.
    # The same branching applies on both local and live sides.
    if input_vat:
        vat_variants = _vat_variants(input_vat, input_country or "")
        # Local VAT lookup
        vat_local = _resolve_local_by_vat(vat_variants, input_country)
        if len(vat_local) >= 2:
            out.update({
                "status":               "ambiguous_vat",
                "resolution_source":    "local",
                "resolution_identity":  "vat",
                "candidates":           [r["client_name"] for r in vat_local],
            })
            return out
        if len(vat_local) == 1:
            row = vat_local[0]
            stored_name = (row.get("client_name") or "").strip()
            out.update({
                "status":               "exact_match",
                "resolution_source":    "local",
                "resolution_identity":  "vat",
                "wfirma_customer_id":   row["wfirma_customer_id"],
                "matched_name":         stored_name,
                "matched_vat_id":       row.get("vat_id", "") or input_vat,
                "matched_country":      row.get("country", "") or input_country,
                "vat_match_confidence": "exact",
            })
            # Soft warning when VAT identifies the contractor but the
            # operator-supplied name differs materially from the stored
            # one. Resolution still succeeds — VAT is authoritative —
            # but the operator should verify they meant this contractor.
            if (_normalize_name(stored_name).lower()
                    != normalized.lower()):
                out["warnings"].append(
                    f"VAT matched but legal name differs: input "
                    f"{normalized!r} vs wFirma {stored_name!r}"
                )
            cust = wfdb.get_customer(stored_name) or {}
            out["warnings"].extend(_mirror_resolution(
                raw_name           = raw_name,
                normalized         = normalized,
                wfirma_customer_id = row["wfirma_customer_id"],
                matched_name       = stored_name,
                country            = row.get("country", "") or input_country,
                vat_id             = row.get("vat_id", "") or input_vat,
            ))
            return out

        # Local VAT miss → try live VAT lookup before falling through
        # to the name resolver. Live's contractors/find with operator=eq
        # on nip is exact-match, so a single hit is high-confidence.
        vat_live = _search_live_by_vat(_normalize_vat(input_vat))
        if len(vat_live) >= 2:
            out.update({
                "status":               "ambiguous_vat",
                "resolution_source":    "live",
                "resolution_identity":  "vat",
                "candidates":           [r.get("name", "") for r in vat_live],
                "live_candidate_count": len(vat_live),
                "candidate_names":      [r.get("name", "") for r in vat_live],
            })
            return out
        if len(vat_live) == 1:
            row = vat_live[0]
            stored_name = (row.get("name") or "").strip()
            out.update({
                "status":               "exact_match",
                "resolution_source":    "live",
                "resolution_identity":  "vat",
                "wfirma_customer_id":   row["wfirma_id"],
                "matched_name":         stored_name,
                "matched_vat_id":       row.get("nip", "") or input_vat,
                "matched_country":      row.get("country", "") or input_country,
                "vat_match_confidence": "exact",
                "live_candidate_count": 1,
                "candidate_names":      [stored_name] if stored_name else [],
            })
            if stored_name and (
                _normalize_name(stored_name).lower() != normalized.lower()
            ):
                out["warnings"].append(
                    f"VAT matched but legal name differs: input "
                    f"{normalized!r} vs wFirma {stored_name!r}"
                )
            out["warnings"].extend(_mirror_resolution(
                raw_name           = raw_name,
                normalized         = normalized,
                wfirma_customer_id = row["wfirma_id"],
                matched_name       = stored_name,
                country            = row.get("country", "") or input_country,
                vat_id             = row.get("nip", "") or input_vat,
            ))
            return out
        # VAT given but no match anywhere → fall through to name logic.
        # The operator may have a typo in the VAT or it's truly new.

    # 1. Local resolution (name-based)
    local = _resolve_local(normalized)
    if local["status"] in (
        "exact_match", "normalized_match", "prefix_match", "reverse_prefix_match"
    ):
        out.update(local)
        out["resolution_source"] = "local"
        # resolution_identity reflects HOW the name path matched
        out["resolution_identity"] = (
            "name"           if local["status"] in ("exact_match", "normalized_match")
            else "prefix"    if local["status"] == "prefix_match"
            else "reverse_prefix"
        )
        # Mirror is idempotent — refreshes updated_at on existing rows.
        cust = wfdb.get_customer(local["matched_name"]) or {}
        out["warnings"].extend(_mirror_resolution(
            raw_name           = raw_name,
            normalized         = normalized,
            wfirma_customer_id = local["wfirma_customer_id"],
            matched_name       = local["matched_name"],
            country            = cust.get("country", "")  or "",
            vat_id             = cust.get("vat_id", "")   or "",
        ))
        return out

    if local["status"] == "ambiguous":
        # Local already says ambiguous — do NOT fall through to live.
        # Two ambiguous sources combined would only multiply the noise.
        out.update(local)
        out["resolution_source"] = "local"
        return out

    # 2. Live wFirma fallback — multi-candidate, ambiguity-aware.
    live = _resolve_live(normalized)
    out["resolution_source"]    = "live"
    out["live_candidate_count"] = live.get("live_candidate_count", 0)
    out["candidate_names"]      = list(live.get("candidate_names", []))

    if live["status"] in (
        "exact_match", "prefix_match", "reverse_prefix_match"
    ):
        out["status"]              = live["status"]
        out["wfirma_customer_id"]  = live["wfirma_customer_id"]
        out["matched_name"]        = live["matched_name"]
        out["resolution_identity"] = (
            "name"           if live["status"] == "exact_match"
            else "prefix"    if live["status"] == "prefix_match"
            else "reverse_prefix"
        )
        out["warnings"].extend(_mirror_resolution(
            raw_name           = raw_name,
            normalized         = normalized,
            wfirma_customer_id = live["wfirma_customer_id"],
            matched_name       = live["matched_name"],
            country            = live.get("country", ""),
            vat_id             = live.get("vat_id", ""),
        ))
        return out

    if live["status"] == "ambiguous":
        # Multiple safe candidates from wFirma — surface them all and
        # NEVER auto-mirror. Operator must pick the right contractor.
        out["status"]     = "ambiguous"
        out["candidates"] = list(live.get("candidates") or [])
        return out

    # 3. Truly missing.
    out["status"] = "missing"
    return out


# ── Batch entrypoint ─────────────────────────────────────────────────────
def ensure_customers_for_batch(
    batch_id: str,
    *,
    dry_run:  bool = True,
    operator: str  = "operator",
) -> Dict[str, Any]:
    """Resolve every distinct customer name on the batch's sales side.
    Always read-first; never creates. ``dry_run`` is accepted for
    symmetry with the product service but is currently always treated as
    True — there is no write mode here yet.
    """
    out: Dict[str, Any] = {
        "batch_id":             batch_id,
        "dry_run":              True,   # always True; create-customer is a future task
        "scanned":              0,
        "exact_match":          0,
        "normalized_match":     0,
        "prefix_match":         0,
        "reverse_prefix_match": 0,
        "ambiguous":            0,
        "ambiguous_vat":        0,    # NEW: VAT-driven ambiguity
        "missing":              0,
        "invalid_name":         0,
        "errors":               [],
        "results":              [],
    }

    if not batch_id:
        out["errors"].append("batch_id is required")
        return out

    raw_names = _collect_client_names(batch_id)
    if not raw_names:
        out["errors"].append(
            "no client names found in sales_documents or sales_packing_lines"
        )
        return out

    # Dedupe by normalized form so two equivalent inputs don't cost two
    # live searches.
    seen: Dict[str, str] = {}
    for raw in raw_names:
        norm = _normalize_name(raw).lower()
        if norm and norm not in seen:
            seen[norm] = raw

    out["scanned"] = len(seen)

    for raw in seen.values():
        res = _resolve_one(
            raw,
            operator      = operator,
            batch_id      = batch_id,
            module_source = "wfirma_customer_auto_resolve",
        )
        out["results"].append(res)
        st = res["status"]
        if st in out:
            out[st] += 1

    log.info(
        "[wfirma_customer_auto_resolve] batch=%s scanned=%d exact=%d "
        "normalized=%d prefix=%d reverse_prefix=%d ambiguous=%d missing=%d "
        "invalid=%d",
        batch_id, out["scanned"], out["exact_match"], out["normalized_match"],
        out["prefix_match"], out["reverse_prefix_match"], out["ambiguous"],
        out["missing"], out["invalid_name"],
    )
    return out


# ── Customer create (operator-triggered single shot) ─────────────────────
#
# Mandatory pre-create gate: every create call MUST first re-run the
# resolver. Only status="missing" is permitted to proceed to
# wfirma_client.create_customer. Every other state means either a row
# already exists (refuse — would be a duplicate) or there's enough
# uncertainty to require operator review (refuse — would be unsafe).
#
# Honors settings.wfirma_create_customer_allowed (default False, defined
# in core.config). Never bypasses the flag — there is no service-actor
# exemption.
#
# On confirmed wFirma success (non-empty wfirma_id), mirrors into both
# local registries:
#   • wfirma_customers (master mirror via wfirma_db.upsert_customer)
#   • reservation_queue.wfirma_customer_mapping (parallel registry)
# On any failure path (raise, empty id, mirror raise) — NO local row is
# written and the operator can re-run safely.

# Sentinel statuses surfaced ONLY by create_one (not by _resolve_one):
_CREATE_REFUSE_STATES = (
    "exact_match", "normalized_match",
    "prefix_match", "reverse_prefix_match",
    "ambiguous", "ambiguous_vat",
)


def create_one(
    client_name: str,
    *,
    vat_id:       str = "",
    country_code: str = "",
    operator:     str = "operator",
) -> Dict[str, Any]:
    """Operator-triggered single-customer create with mandatory
    resolver-gate. Read the module docstring for the full safety
    contract. Never raises — every error path returns a structured
    result.

    Returns
    -------
    {
      'status':                   <one of>:
                                   'created'                — wFirma created the row, both mirrors written
                                   'already_exists_or_ambiguous'
                                                            — resolver hit something safe; refused
                                   'blocked_flag_off'       — capability flag false
                                   'failed'                 — create raised OR returned empty id
                                   'invalid_name'           — empty/whitespace-only input
      'wfirma_customer_id':       str | '',
      'created':                  bool,
      'mirrored':                 bool,
      'warnings':                 [str],
      'resolution_before_create': <full _resolve_one result>,
      'errors':                   [str],
    }
    """
    out: Dict[str, Any] = {
        "status":                   "",
        "wfirma_customer_id":       "",
        "created":                  False,
        "mirrored":                 False,
        "warnings":                 [],
        "resolution_before_create": {},
        "errors":                   [],
    }

    # Empty-input early exit — never even resolve.
    normalized = _normalize_name(client_name)
    if not normalized:
        out["status"] = "invalid_name"
        out["errors"].append("client_name is required")
        return out

    # 1. Mandatory pre-create gate — VAT-first, ambiguity-safe resolver.
    #    Use the core resolver here so the pre-create gate does NOT emit
    #    its own correction-registry row; the create call records its own
    #    customer_resolution_override entry on confirmed success.
    resolution = _resolve_one_core(
        client_name,
        input_vat     = vat_id,
        input_country = country_code,
    )
    out["resolution_before_create"] = resolution

    if resolution["status"] in _CREATE_REFUSE_STATES:
        out["status"] = "already_exists_or_ambiguous"
        # When the resolver already mirrored a successful match, surface
        # the mirrored id so the operator can use it without re-creating.
        out["wfirma_customer_id"] = resolution.get("wfirma_customer_id", "")
        out["warnings"].extend(resolution.get("warnings", []))
        return out

    if resolution["status"] != "missing":
        # Defensive: any other status (e.g. invalid_name reached here)
        # is a refusal too.
        out["status"] = resolution["status"]
        out["errors"].append(
            f"resolver returned non-missing status {resolution['status']!r} "
            "— refusing create"
        )
        return out

    # 2. Capability flag — never bypass.
    if not getattr(settings, "wfirma_create_customer_allowed", False):
        out["status"] = "blocked_flag_off"
        out["errors"].append(
            "wfirma_create_customer_allowed is false — "
            "operator must enable WFIRMA_CREATE_CUSTOMER_ALLOWED to create"
        )
        return out

    # 3. Live create via the existing single-customer client API.
    try:
        from . import wfirma_client
        contractor = wfirma_client.create_customer(
            name    = normalized,
            nip     = _normalize_vat(vat_id),
            country = (country_code or "").strip().upper(),
        )
    except Exception as exc:
        out["status"] = "failed"
        out["errors"].append(f"{type(exc).__name__}: {exc}")
        return out

    new_id = (getattr(contractor, "wfirma_id", "") or "").strip()
    if not new_id:
        out["status"] = "failed"
        out["errors"].append(
            "contractors/add returned no wfirma_id — refusing fake mirror"
        )
        return out

    # 4. Mirror — both registries, on confirmed success only.
    out["wfirma_customer_id"] = new_id
    out["created"]            = True
    mirror_warnings = _mirror_resolution(
        raw_name           = client_name,
        normalized         = normalized,
        wfirma_customer_id = new_id,
        matched_name       = (contractor.name or normalized),
        country            = (contractor.country or country_code or ""),
        vat_id             = (contractor.nip or vat_id or ""),
    )
    out["warnings"].extend(mirror_warnings)
    out["mirrored"]           = not bool(mirror_warnings)
    out["status"]             = "created"
    # Append-only correction registry — operator-approved create outcome.
    log_warn = _log_correction_safe(
        correction_type = "customer_resolution_override",
        entity_type     = "customer",
        entity_key      = normalized,
        old_value       = "missing",
        new_value       = {
            "wfirma_customer_id": new_id,
            "matched_name":       (contractor.name or normalized),
            "vat_id":             (contractor.nip or vat_id or ""),
            "country":            (contractor.country or country_code or ""),
        },
        operator        = operator,
        module_source   = "wfirma_customer_auto_create",
        confidence      = 1.0,
        approved        = True,
        notes           = "created",
        evidence_refs   = [
            {"type": "endpoint",    "ref":
                "/api/v1/wfirma/customers/auto-create-from-name"},
            {"type": "client_name", "ref": client_name or ""},
            {"type": "input_vat",   "ref": vat_id or ""},
        ],
    )
    if log_warn:
        out["warnings"].append(log_warn)
    log.info(
        "[customer_auto_resolve] created wFirma contractor "
        "name=%r id=%s vat=%r country=%r",
        normalized, new_id, vat_id, country_code,
    )
    return out
