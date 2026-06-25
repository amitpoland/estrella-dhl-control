"""proforma_intelligence.py — Phase 6 AI intelligence helpers.

Bounded AI enrichment zones for commercial document preparation.
All functions are strictly read-only:
  - No wFirma writes
  - No audit.json mutations
  - No draft mutations
  - No DHL writes
  - No PZ writes

AI is assistive only. Every return value requires operator review or
explicit confirmation before any downstream action.

Language policy (binding): PL + EN only. No name_sk, no third-language
field is returned or surfaced from any function in this module.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


# ── Anomaly types ──────────────────────────────────────────────────────────────

ANOMALY_ZERO_PRICE    = "zero_price"
ANOMALY_NEGATIVE_PRICE = "negative_price"
ANOMALY_MISSING_HS    = "missing_hs_code"
ANOMALY_MISSING_PC    = "missing_product_code"
ANOMALY_PRICE_OUTLIER = "price_outlier"
ANOMALY_MISSING_NAME_PL = "missing_name_pl"
ANOMALY_MISSING_NAME_EN = "missing_name_en"
ANOMALY_OPERATOR_DESCRIPTION_MISMATCH = "operator_description_mismatch"

SEVERITY_HIGH   = "high"
SEVERITY_MEDIUM = "medium"
SEVERITY_LOW    = "low"


@dataclass
class LineAnomaly:
    line_id:    Optional[str]
    product_code: Optional[str]
    anomaly_type: str
    severity:   str
    message:    str
    confidence: float          # 0.0–1.0; 1.0 = certain


@dataclass
class FieldSuggestion:
    product_code: str
    field:        str
    suggested_value: str
    confidence:   float
    source:       str          # "product_descriptions", "corpus", "hs_codes"


@dataclass
class CorpusStats:
    """Aggregated statistics from historical editable_lines_json rows."""
    product_avg_price: Dict[str, float] = field(default_factory=dict)
    product_hs_codes:  Dict[str, Dict[str, int]] = field(default_factory=dict)  # pc → {hs: count}
    corpus_size:       int = 0         # number of historical drafts examined


@dataclass
class DraftConfidence:
    overall:    float          # 0.0–1.0
    company:    float          # company profile completeness
    lines:      float          # line data completeness
    shipment:   float          # shipment data completeness
    pricing:    float          # pricing completeness


# ── Anomaly detection ──────────────────────────────────────────────────────────

def detect_line_anomalies(
    lines: List[Dict[str, Any]],
    corpus: Optional[CorpusStats] = None,
    price_outlier_threshold: float = 3.0,
) -> List[LineAnomaly]:
    """Inspect editable lines for anomalies.

    Arguments:
        lines: list of editable_line dicts (product_code, unit_price,
               hs_code, name_pl, name_en, …)
        corpus: optional corpus stats used for price-outlier detection
        price_outlier_threshold: flag when line price > N × corpus avg

    Returns list of LineAnomaly. Empty list = no anomalies detected.
    Never raises; bad data is absorbed with reduced confidence.
    """
    results: List[LineAnomaly] = []

    for ln in lines:
        lid  = str(ln.get("line_id") or ln.get("id") or "")
        pc   = str(ln.get("product_code") or "").strip()
        price = float(ln.get("unit_price") or 0)

        if not pc:
            results.append(LineAnomaly(
                line_id=lid, product_code=None,
                anomaly_type=ANOMALY_MISSING_PC,
                severity=SEVERITY_HIGH,
                message="Line has no product_code — cannot resolve to wFirma product.",
                confidence=1.0,
            ))
            continue

        if price == 0:
            results.append(LineAnomaly(
                line_id=lid, product_code=pc,
                anomaly_type=ANOMALY_ZERO_PRICE,
                severity=SEVERITY_HIGH,
                message=f"{pc}: unit_price is 0 — pricing refresh required.",
                confidence=1.0,
            ))
        elif price < 0:
            results.append(LineAnomaly(
                line_id=lid, product_code=pc,
                anomaly_type=ANOMALY_NEGATIVE_PRICE,
                severity=SEVERITY_HIGH,
                message=f"{pc}: unit_price is negative ({price}) — data error.",
                confidence=1.0,
            ))

        hs = str(ln.get("hs_code") or ln.get("hsn_code") or "").strip()
        if not hs:
            results.append(LineAnomaly(
                line_id=lid, product_code=pc,
                anomaly_type=ANOMALY_MISSING_HS,
                severity=SEVERITY_MEDIUM,
                message=f"{pc}: HS code absent — required for customs clearance.",
                confidence=1.0,
            ))

        # PL name required; EN name strongly recommended
        if not str(ln.get("name_pl") or "").strip():
            results.append(LineAnomaly(
                line_id=lid, product_code=pc,
                anomaly_type=ANOMALY_MISSING_NAME_PL,
                severity=SEVERITY_MEDIUM,
                message=f"{pc}: Polish name (name_pl) is missing.",
                confidence=1.0,
            ))
        if not str(ln.get("name_en") or "").strip():
            results.append(LineAnomaly(
                line_id=lid, product_code=pc,
                anomaly_type=ANOMALY_MISSING_NAME_EN,
                severity=SEVERITY_LOW,
                message=f"{pc}: English name (name_en) is missing.",
                confidence=0.9,
            ))

        # Corpus-based price outlier detection
        if corpus and pc in corpus.product_avg_price and price > 0:
            avg = corpus.product_avg_price[pc]
            if avg > 0 and (price / avg) > price_outlier_threshold:
                results.append(LineAnomaly(
                    line_id=lid, product_code=pc,
                    anomaly_type=ANOMALY_PRICE_OUTLIER,
                    severity=SEVERITY_MEDIUM,
                    message=(
                        f"{pc}: unit_price {price:.2f} is "
                        f"{price / avg:.1f}× corpus average {avg:.2f}."
                    ),
                    confidence=0.75,
                ))

    return results


# ── Operator-override mismatch detection ───────────────────────────────────────

def detect_operator_override_mismatches(
    lines: List[Dict[str, Any]],
    master_db_path: Optional[Path] = None,
) -> List[LineAnomaly]:
    """Check lines where name_pl_source='operator' against canonical
    product_descriptions.description_pl.

    When an operator has explicitly set name_pl ('operator' source), it must
    not diverge silently from the customs-engine canonical sentence.  If they
    differ, surface a HIGH-severity anomaly so the operator must either accept
    the canonical description or explicitly confirm the override before legal /
    export finalization.

    Non-fatal: returns [] on any DB error.  Never raises.
    """
    if not master_db_path or not Path(master_db_path).exists():
        return []

    operator_lines = [
        ln for ln in lines
        if str(ln.get("name_pl_source") or "").strip() == "operator"
        and str(ln.get("name_pl") or "").strip()
        and str(ln.get("product_code") or "").strip()
    ]
    if not operator_lines:
        return []

    results: List[LineAnomaly] = []
    con: Optional[sqlite3.Connection] = None
    try:
        con = sqlite3.connect(str(master_db_path))
        con.row_factory = sqlite3.Row
        for ln in operator_lines:
            pc             = str(ln.get("product_code") or "").strip()
            lid            = str(ln.get("line_id") or ln.get("id") or "")
            operator_name  = str(ln.get("name_pl") or "").strip()
            row = con.execute(
                "SELECT description_pl, description_en FROM product_descriptions "
                "WHERE product_code=?",
                (pc,),
            ).fetchone()
            if row is None:
                continue
            canonical_pl = str(row["description_pl"] or "").strip()
            if not canonical_pl:
                continue

            if " / " in operator_name:
                # Operator stored combined "PL / EN" text — compare each part separately.
                # This avoids false positives when the operator confirms both the canonical
                # PL sentence and the canonical EN sentence joined with a slash separator.
                operator_pl, operator_en = (
                    p.strip() for p in operator_name.split(" / ", 1)
                )
                canonical_en = str(row["description_en"] or "").strip()
                pl_match = operator_pl == canonical_pl
                # EN is considered a match if canonical EN is absent (nothing to compare)
                # or if the operator EN equals the canonical EN exactly.
                en_match = (not canonical_en) or (operator_en == canonical_en)
                if pl_match and en_match:
                    continue
            else:
                if operator_name == canonical_pl:
                    continue

            results.append(LineAnomaly(
                line_id=lid,
                product_code=pc,
                anomaly_type=ANOMALY_OPERATOR_DESCRIPTION_MISMATCH,
                severity=SEVERITY_HIGH,
                message=(
                    f"{pc}: operator Polish description differs from canonical customs "
                    f"description. Operator: {operator_name!r}. "
                    f"Canonical (customs engine): {canonical_pl!r}. "
                    "For legal/export finalization: accept canonical or confirm "
                    "override with explicit reason."
                ),
                confidence=1.0,
            ))
    except Exception:
        pass
    finally:
        if con is not None:
            try:
                con.close()
            except Exception:
                pass
    return results


# ── Missing-field inference ────────────────────────────────────────────────────

def infer_missing_fields(
    lines: List[Dict[str, Any]],
    master_db_path: Optional[Path] = None,
) -> List[FieldSuggestion]:
    """Suggest values for missing line fields from product_descriptions
    and master_data.

    Only suggests for lines that are genuinely missing the field.
    Never overwrites existing values.
    Language policy: suggests name_pl and name_en only (no name_sk).
    """
    suggestions: List[FieldSuggestion] = []
    if not lines:
        return suggestions

    # Load product_descriptions lookup once from documents.db
    desc_lookup: Dict[str, Dict[str, Any]] = {}
    hs_lookup: Dict[str, str] = {}

    if master_db_path and Path(master_db_path).exists():
        try:
            with sqlite3.connect(str(master_db_path)) as conn:
                conn.row_factory = sqlite3.Row
                # product_local: hs_code_override, origin_country
                # Phase 4B Wave 4: only ACTIVE overlays contribute HS
                # suggestions. COALESCE tolerates pre-migration rows.
                rows = conn.execute(
                    "SELECT product_code, hs_code_override FROM product_local "
                    "WHERE hs_code_override IS NOT NULL AND hs_code_override <> '' "
                    "AND COALESCE(active, 1) = 1"
                ).fetchall()
                for r in rows:
                    hs_lookup[r["product_code"].strip()] = r["hs_code_override"].strip()
        except Exception:
            pass

    # Load product_descriptions (from documents.db path via module if available)
    try:
        from . import document_db as ddb
        docs_path = getattr(ddb, "_db_path", None)
        if docs_path and Path(str(docs_path)).exists():
            with sqlite3.connect(str(docs_path)) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT product_code, name_pl, name_en FROM product_descriptions"
                ).fetchall()
                for r in rows:
                    pc = (r["product_code"] or "").strip()
                    if pc:
                        desc_lookup[pc] = {
                            "name_pl": r["name_pl"] or "",
                            "name_en": r["name_en"] or "",
                        }
    except Exception:
        pass

    for ln in lines:
        pc = str(ln.get("product_code") or "").strip()
        if not pc:
            continue

        # HS code suggestion
        existing_hs = str(ln.get("hs_code") or ln.get("hsn_code") or "").strip()
        if not existing_hs and pc in hs_lookup:
            suggestions.append(FieldSuggestion(
                product_code=pc,
                field="hs_code",
                suggested_value=hs_lookup[pc],
                confidence=0.95,
                source="product_local.hs_code_override",
            ))

        # name_pl suggestion (PL only — language policy)
        if not str(ln.get("name_pl") or "").strip() and pc in desc_lookup:
            name_pl = desc_lookup[pc].get("name_pl", "").strip()
            if name_pl:
                suggestions.append(FieldSuggestion(
                    product_code=pc,
                    field="name_pl",
                    suggested_value=name_pl,
                    confidence=0.85,
                    source="product_descriptions",
                ))

        # name_en suggestion (EN only — language policy)
        if not str(ln.get("name_en") or "").strip() and pc in desc_lookup:
            name_en = desc_lookup[pc].get("name_en", "").strip()
            if name_en:
                suggestions.append(FieldSuggestion(
                    product_code=pc,
                    field="name_en",
                    suggested_value=name_en,
                    confidence=0.85,
                    source="product_descriptions",
                ))

    return suggestions


# ── Corpus statistics builder ──────────────────────────────────────────────────

def build_corpus_stats(
    proforma_db_path: Path,
    max_drafts: int = 50,
) -> CorpusStats:
    """Build corpus statistics from historical posted proforma drafts.

    Reads editable_lines_json from posted drafts only — never from
    drafts in editing/draft state (those are untrusted).

    Returns CorpusStats with average prices and HS code distribution
    per product_code. Safe to call with a non-existent DB path (returns
    empty corpus).
    """
    stats = CorpusStats()
    if not Path(proforma_db_path).exists():
        return stats

    try:
        with sqlite3.connect(str(proforma_db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT editable_lines_json FROM proforma_drafts "
                "WHERE draft_state = 'posted' AND editable_lines_json IS NOT NULL "
                "ORDER BY updated_at DESC LIMIT ?",
                (max_drafts,),
            ).fetchall()
    except Exception:
        return stats

    import json as _json
    price_sums:  Dict[str, float] = {}
    price_counts: Dict[str, int]  = {}

    for row in rows:
        try:
            lines = _json.loads(row["editable_lines_json"] or "[]") or []
        except Exception:
            continue

        for ln in lines:
            pc    = str(ln.get("product_code") or "").strip()
            price = float(ln.get("unit_price") or 0)
            hs    = str(ln.get("hs_code") or ln.get("hsn_code") or "").strip()

            if not pc:
                continue

            if price > 0:
                price_sums[pc]   = price_sums.get(pc, 0.0) + price
                price_counts[pc] = price_counts.get(pc, 0) + 1

            if hs:
                if pc not in stats.product_hs_codes:
                    stats.product_hs_codes[pc] = {}
                stats.product_hs_codes[pc][hs] = (
                    stats.product_hs_codes[pc].get(hs, 0) + 1
                )

        stats.corpus_size += 1

    for pc, total in price_sums.items():
        count = price_counts.get(pc, 0)
        if count > 0:
            stats.product_avg_price[pc] = total / count

    return stats


# ── Confidence scoring ─────────────────────────────────────────────────────────

def score_draft_confidence(
    lines: List[Dict[str, Any]],
    company_profile_present: bool,
    company_profile_fields_filled: int,
    company_profile_fields_total: int,
    has_shipment_awb: bool,
) -> DraftConfidence:
    """Produce a confidence score for the proforma draft.

    All inputs are plain scalars/booleans — caller reads from the draft
    and company profile before calling; no DB reads here.
    """
    # Company score
    if not company_profile_present:
        company_score = 0.0
    elif company_profile_fields_total == 0:
        company_score = 0.0
    else:
        company_score = company_profile_fields_filled / company_profile_fields_total

    # Lines score: fraction with price > 0, hs_code, name_pl present
    if not lines:
        lines_score = 0.0
    else:
        ok_count = sum(
            1 for ln in lines
            if float(ln.get("unit_price") or 0) > 0
            and str(ln.get("hs_code") or ln.get("hsn_code") or "").strip()
            and str(ln.get("name_pl") or "").strip()
        )
        lines_score = ok_count / len(lines)

    # Shipment score
    shipment_score = 1.0 if has_shipment_awb else 0.3

    # Pricing score: same as lines_score (dominant driver of pricing readiness)
    pricing_score = lines_score

    # Overall: weighted average
    overall = (
        company_score  * 0.25 +
        lines_score    * 0.45 +
        shipment_score * 0.15 +
        pricing_score  * 0.15
    )

    return DraftConfidence(
        overall=round(overall, 3),
        company=round(company_score, 3),
        lines=round(lines_score, 3),
        shipment=round(shipment_score, 3),
        pricing=round(pricing_score, 3),
    )


# ── Company profile completeness ──────────────────────────────────────────────

def company_profile_completeness(profile) -> Dict[str, Any]:
    """Return a completeness dict for a CompanyProfile (or None).

    Mandatory fields: legal_name, nip, country, iban_eur, swift.
    Recommended fields: street, postal_city, email, bank_name,
                        place_of_issue, signatory_name.
    Optional fields: short_name, iban_usd, iban_pln, vat_eu, regon,
                     phone, signatory_title, returns_policy_pl.

    Returns dict with fields, missing_mandatory, missing_recommended,
    score (0.0–1.0), and present flag.
    """
    if profile is None:
        return {
            "present": False,
            "score": 0.0,
            "missing_mandatory": ["company profile not configured"],
            "missing_recommended": [],
            "fields": {},
        }

    mandatory   = ["legal_name", "nip", "country", "iban_eur", "swift"]
    recommended = ["street", "postal_city", "email", "bank_name",
                   "place_of_issue", "signatory_name"]

    def _filled(f: str) -> bool:
        v = getattr(profile, f, None)
        return bool(v and str(v).strip())

    missing_mandatory   = [f for f in mandatory   if not _filled(f)]
    missing_recommended = [f for f in recommended if not _filled(f)]

    total_checked = len(mandatory) + len(recommended)
    filled_count  = (
        sum(1 for f in mandatory   if _filled(f)) +
        sum(1 for f in recommended if _filled(f))
    )
    score = filled_count / total_checked if total_checked else 0.0

    return {
        "present":             True,
        "score":               round(score, 3),
        "missing_mandatory":   missing_mandatory,
        "missing_recommended": missing_recommended,
        "fields": {
            f: _filled(f)
            for f in mandatory + recommended
        },
    }
