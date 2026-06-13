"""Master Data Intelligence — Phase 4+5+6+8 advisory scoring engine.

Deterministic, read-only. llm_used=False. No writes.

Domains:
  customer   — completeness, VAT status, duplicate probability
  product    — completeness, HS classification, finishing coverage,
               description quality, near-duplicate detection, product_local coverage
  finishing  — metal/stone/unit field coverage per design,
               metal/stone compatibility advisory, non-standard metal detection
  supplier   — completeness, wFirma integration, duplicate probability
  document   — document/evidence completeness, extraction coverage, AWB/MRN/PZ
               linkage, customs declaration coverage, WorkDrive upload tracking
               (Phase 6 addition)
  graph      — link-completeness aggregate across batch_id hubs: what % of batches
               have each relationship (AWB, tracking, customer, supplier, invoice,
               customs) linked vs missing (Phase 8 addition)
  readiness  — cross-domain gap analysis, actionable blockers

Output contract: score | confidence | advisory | recommendations | explanation
Forbidden: write | modify | execute | correct | approve | create | delete
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.config import settings
from ..core.logging import get_logger
from . import name_normalization
from .customer_master_db import list_customers, init_db as cm_init
from .master_data_db import list_designs, list_product_local, init_db as md_init
from .suppliers_db import list_suppliers, init_db as supp_init
from .document_db import get_document_coverage_summary

log = get_logger(__name__)

# ── DB paths (read-only) ──────────────────────────────────────────────────────

_CM_DB   = settings.storage_root / "customer_master.sqlite"
_MD_DB   = settings.storage_root / "master_data.sqlite"
_SUPP_DB = settings.storage_root / "suppliers.sqlite"
_DOC_DB  = settings.storage_root / "documents.db"

# ── Output types ─────────────────────────────────────────────────────────────

@dataclass
class FieldGap:
    field: str
    affected_count: int
    pct: float          # 0.0–100.0
    severity: str       # "critical" | "important" | "optional"
    advisory: str


@dataclass
class DuplicateCluster:
    key: str            # normalized dedup key
    entity_keys: List[str]
    probability: float  # 0.0–1.0


@dataclass
class DomainScore:
    domain: str
    entity_count: int
    completeness_score: float   # 0.0–1.0
    confidence: float           # 0.0–1.0
    field_gaps: List[FieldGap]
    duplicate_clusters: List[DuplicateCluster]
    advisory: str
    recommendations: List[str]
    details: Dict[str, Any]


@dataclass
class MasterDataIntelligenceReport:
    generated_at: str
    llm_used: bool
    advisory_class: str
    platform_score: float
    customer: DomainScore
    product: DomainScore
    finishing: DomainScore
    supplier: DomainScore
    document: DomainScore       # Phase 6: document/evidence coverage
    graph: DomainScore          # Phase 8: link-completeness aggregate across batches
    readiness: DomainScore
    top_recommendations: List[str]

    def to_dict(self) -> Dict[str, Any]:
        def _ds(d: DomainScore) -> Dict[str, Any]:
            return {
                "domain": d.domain,
                "entity_count": d.entity_count,
                "completeness_score": round(d.completeness_score, 3),
                "confidence": round(d.confidence, 3),
                "field_gaps": [
                    {"field": g.field, "affected_count": g.affected_count,
                     "pct": round(g.pct, 1), "severity": g.severity,
                     "advisory": g.advisory}
                    for g in d.field_gaps
                ],
                "duplicate_clusters": [
                    {"key": c.key, "entity_keys": c.entity_keys,
                     "probability": round(c.probability, 2)}
                    for c in d.duplicate_clusters
                ],
                "advisory": d.advisory,
                "recommendations": d.recommendations,
                "details": d.details,
            }
        return {
            "generated_at": self.generated_at,
            "llm_used": self.llm_used,
            "advisory_class": self.advisory_class,
            "platform_score": round(self.platform_score, 3),
            "customer": _ds(self.customer),
            "product": _ds(self.product),
            "finishing": _ds(self.finishing),
            "supplier": _ds(self.supplier),
            "document": _ds(self.document),
            "graph": _ds(self.graph),
            "readiness": _ds(self.readiness),
            "top_recommendations": self.top_recommendations,
        }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _norm(s: Optional[str]) -> str:
    return name_normalization.master_data_norm(s)


def _pct(n: int, total: int) -> float:
    return round(100.0 * n / total, 1) if total else 0.0


def _weighted_score(present: int, weights: List[float], total_weight: float) -> float:
    return min(1.0, present / total_weight) if total_weight else 1.0


# ── Customer domain ───────────────────────────────────────────────────────────

# (field_name, severity, weight, advisory_text)
_CUSTOMER_FIELDS: List[tuple] = [
    ("nip",                    "critical",  0.20, "NIP required for Polish invoice compliance"),
    ("default_currency",       "critical",  0.15, "currency required for proforma draft generation"),
    ("vat_mode",               "critical",  0.15, "VAT mode required for correct wFirma invoicing"),
    ("bill_to_street",         "important", 0.08, "billing street missing — shipping labels incomplete"),
    ("bill_to_city",           "important", 0.06, "billing city missing"),
    ("bill_to_postal_code",    "important", 0.06, "billing postal code missing"),
    ("bill_to_email",          "important", 0.07, "email required for invoice delivery"),
    ("short_code",             "important", 0.05, "short code aids batch matching and reporting"),
    ("vat_eu_number",          "important", 0.06, "EU VAT number required for intra-EU zero-rate"),
    ("vat_eu_valid",           "optional",  0.04, "EU VAT validation status not recorded"),
    ("preferred_payment_method","optional", 0.03, "payment method not set — defaults apply"),
    ("client_type",            "optional",  0.03, "client type (client/supplier/both) not classified"),
    ("kyc_status",             "optional",  0.02, "KYC status not recorded"),
]
_CUSTOMER_TOTAL_WEIGHT = sum(w for _, _, w, _ in _CUSTOMER_FIELDS)


def _score_customers(customers: List[Any]) -> DomainScore:
    if not customers:
        return DomainScore(
            domain="customer", entity_count=0,
            completeness_score=0.0, confidence=0.0,
            field_gaps=[], duplicate_clusters=[],
            advisory="No customer master records found.",
            recommendations=["Load customer master data from wFirma to begin scoring."],
            details={},
        )

    n = len(customers)
    field_missing: Dict[str, int] = {f: 0 for f, _, _, _ in _CUSTOMER_FIELDS}
    per_entity_scores: List[float] = []

    nip_groups: Dict[str, List[str]] = {}
    name_groups: Dict[str, List[str]] = {}

    for c in customers:
        entity_score = 0.0
        for fname, _, weight, _ in _CUSTOMER_FIELDS:
            val = getattr(c, fname, None)
            if val is not None and val != "" and val is not False:
                entity_score += weight
            else:
                field_missing[fname] += 1
        per_entity_scores.append(min(1.0, entity_score / _CUSTOMER_TOTAL_WEIGHT))

        # Dedup tracking
        nip = getattr(c, "nip", None) or ""
        norm_nip = re.sub(r"\s", "", nip).upper()
        if norm_nip:
            nip_groups.setdefault(norm_nip, []).append(c.bill_to_name)

        norm_name = _norm(c.bill_to_name)
        if norm_name:
            name_groups.setdefault(norm_name, []).append(c.bill_to_contractor_id)

    completeness = sum(per_entity_scores) / n
    # Confidence degrades when >30% of entities missing critical fields
    critical_missing_pct = sum(
        field_missing[f] for f, sev, _, _ in _CUSTOMER_FIELDS if sev == "critical"
    ) / (n * sum(1 for _, sev, _, _ in _CUSTOMER_FIELDS if sev == "critical"))
    confidence = max(0.1, 1.0 - critical_missing_pct * 0.8)

    gaps: List[FieldGap] = []
    for fname, severity, _, adv in _CUSTOMER_FIELDS:
        missing = field_missing[fname]
        if missing > 0:
            gaps.append(FieldGap(
                field=fname, affected_count=missing,
                pct=_pct(missing, n), severity=severity, advisory=adv,
            ))
    gaps.sort(key=lambda g: ({"critical": 0, "important": 1, "optional": 2}[g.severity], -g.pct))

    dup_clusters: List[DuplicateCluster] = []
    for norm_nip, names in nip_groups.items():
        if len(names) > 1:
            dup_clusters.append(DuplicateCluster(
                key=f"nip:{norm_nip}", entity_keys=names, probability=0.95,
            ))
    for norm_name, cids in name_groups.items():
        if len(cids) > 1 and not any(
            dc.entity_keys == cids for dc in dup_clusters
        ):
            dup_clusters.append(DuplicateCluster(
                key=f"name:{norm_name}", entity_keys=cids, probability=0.70,
            ))

    # Recommendations
    recs: List[str] = []
    critical_gaps = [g for g in gaps if g.severity == "critical" and g.pct > 0]
    if critical_gaps:
        top = critical_gaps[0]
        recs.append(
            f"Fill '{top.field}' for {top.affected_count} customer(s) "
            f"({top.pct:.0f}%) — {top.advisory}"
        )
    important_gaps = [g for g in gaps if g.severity == "important" and g.pct > 20]
    for g in important_gaps[:2]:
        recs.append(
            f"Add '{g.field}' to {g.affected_count} customer(s) ({g.pct:.0f}%)"
        )
    if dup_clusters:
        recs.append(
            f"Review {len(dup_clusters)} potential duplicate customer cluster(s)"
        )

    vat_unvalidated = sum(
        1 for c in customers
        if getattr(c, "vat_eu_number", None) and not getattr(c, "vat_eu_valid", None)
    )
    if vat_unvalidated:
        recs.append(
            f"{vat_unvalidated} customer(s) have EU VAT numbers not yet validated via VIES"
        )

    advisory = (
        f"{n} customer(s) scored. "
        f"Completeness: {completeness:.0%}. "
        f"Critical gaps: {len(critical_gaps)} field type(s). "
        + (f"Potential duplicates: {len(dup_clusters)}." if dup_clusters else "No duplicates detected.")
    )

    return DomainScore(
        domain="customer", entity_count=n,
        completeness_score=round(completeness, 3),
        confidence=round(confidence, 3),
        field_gaps=gaps,
        duplicate_clusters=dup_clusters,
        advisory=advisory,
        recommendations=recs,
        details={
            "vat_eu_unvalidated": vat_unvalidated,
            "missing_nip_count": field_missing.get("nip", 0),
            "missing_currency_count": field_missing.get("default_currency", 0),
            "missing_vat_mode_count": field_missing.get("vat_mode", 0),
        },
    )


# ── Phase 5: Product / Finishing intelligence helpers ────────────────────────

# Material vocabulary for description quality scoring
_MATERIAL_WORDS: frozenset = frozenset({
    "gold", "silver", "platinum", "palladium", "rhodium", "titanium",
    "diamond", "pearl", "ruby", "emerald", "sapphire", "topaz", "amethyst",
    "opal", "garnet", "aquamarine", "tourmaline", "turquoise", "coral",
    "sterling", "white gold", "rose gold", "yellow gold", "zirconia", "cz",
    "moissanite",
})

# Common jewellery type tokens that don't add description value
_GENERIC_JEWELLERY_TOKENS: frozenset = frozenset({
    "ring", "necklace", "bracelet", "earring", "pendant", "brooch",
    "chain", "bangle", "stud", "hoop", "set", "collection",
    "pierscien", "naszyjnik", "bransoletka", "kolczyki",
})

# High-value stones advisorily flagged in silver (not forbidden, just unusual)
_SILVER_ADVISORY_STONES: frozenset = frozenset({
    "diamond", "emerald", "ruby", "sapphire", "tanzanite", "alexandrite",
})

# Stone vocabulary for compatibility detection
_STONE_KEYWORDS: frozenset = frozenset({
    "diamond", "emerald", "ruby", "sapphire", "tanzanite", "alexandrite",
    "pearl", "opal", "amethyst", "topaz", "garnet", "aquamarine",
    "tourmaline", "peridot", "citrine", "spinel", "zircon", "zirconia",
    "cz", "moissanite", "coral", "turquoise",
})


def _desc_quality(display_name: Optional[str]) -> str:
    """Classify display_name description quality: 'none' | 'poor' | 'ok' | 'good'."""
    if not display_name or not display_name.strip():
        return "none"
    s = display_name.strip()
    if len(s) < 5:
        return "poor"
    tokens = set(_norm(s).split())
    has_material = bool(tokens & _MATERIAL_WORDS)
    is_long_enough = len(s) >= 10
    if has_material and is_long_enough:
        return "good"
    if len(s) >= 5:
        return "ok"
    return "poor"


def _design_near_duplicates(designs: List[Any]) -> List[DuplicateCluster]:
    """Detect near-duplicate designs by normalized display_name."""
    name_groups: Dict[str, List[str]] = {}
    for d in designs:
        name = getattr(d, "display_name", None)
        if not name or not name.strip():
            continue
        # Normalize: lower, remove punctuation, strip generic jewellery tokens
        tokens = set(_norm(name).split()) - _GENERIC_JEWELLERY_TOKENS
        key = " ".join(sorted(tokens)) if tokens else _norm(name)
        if key:
            name_groups.setdefault(key, []).append(d.design_code)
    clusters: List[DuplicateCluster] = []
    for key, codes in name_groups.items():
        if len(codes) > 1:
            clusters.append(DuplicateCluster(
                key=f"name:{key}", entity_keys=codes, probability=0.80,
            ))
    return clusters


def _metal_stone_compat_warnings(designs: List[Any]) -> List[Dict[str, Any]]:
    """Return advisory compatibility warnings for unusual metal/stone combinations.

    Silver + high-value stones (diamond, emerald, ruby, sapphire) is flagged as
    advisory-unusual because high-value stones are customarily set in gold/platinum.
    This is NOT a blocking error — it may be intentional — but surfaces for review.
    """
    warnings: List[Dict[str, Any]] = []
    for d in designs:
        metal = getattr(d, "metal", None)
        stone = getattr(d, "stone_summary", None)
        if not metal or not stone:
            continue
        metal_norm = _norm(metal)
        stone_lower = stone.lower()
        if "silver" in metal_norm or "srebro" in metal_norm:
            matched_stones = [s for s in _SILVER_ADVISORY_STONES if s in stone_lower]
            if matched_stones:
                warnings.append({
                    "design_code": d.design_code,
                    "metal": metal,
                    "stone_indicator": stone[:60],
                    "matched_advisory_stones": matched_stones,
                    "advisory": (
                        f"High-value stone ({', '.join(matched_stones)}) set in silver — "
                        "typically set in gold/platinum; verify if intentional"
                    ),
                })
    return warnings


# ── Product domain (Designs) ──────────────────────────────────────────────────

_PRODUCT_FIELDS: List[tuple] = [
    ("display_name",  "critical",  0.20, "display name required for wFirma product registration"),
    ("hs_code",       "critical",  0.25, "HS code required for customs classification and duty calculation"),
    ("unit",          "critical",  0.15, "unit of measure required for wFirma goods entries"),
    ("product_ref",   "important", 0.10, "wFirma product reference missing — limits auto-mapping"),
    ("design_family", "important", 0.08, "design family not set — limits supplier intelligence grouping"),
    ("collection",    "optional",  0.05, "collection not set"),
    ("notes",         "optional",  0.03, "no notes recorded"),
]
_PRODUCT_TOTAL_WEIGHT = sum(w for _, _, w, _ in _PRODUCT_FIELDS)

_HS_CODE_RE = re.compile(r"^\d{4,12}$")


def _score_products(
    designs: List[Any],
    product_locals: Optional[List[Any]] = None,
) -> DomainScore:
    """Score product domain.

    Phase 5 additions (over Phase 4):
    - description quality breakdown (none/poor/ok/good)
    - near-duplicate detection by normalized display_name
    - product_local coverage: % of designs with ProductLocal augmentation
    """
    if not designs:
        return DomainScore(
            domain="product", entity_count=0,
            completeness_score=0.0, confidence=0.0,
            field_gaps=[], duplicate_clusters=[],
            advisory="No design/product master records found.",
            recommendations=["Register designs in the Design Master to enable product intelligence."],
            details={},
        )

    product_locals = product_locals or []
    pl_codes: frozenset = frozenset(
        getattr(pl, "product_code", None) for pl in product_locals
        if getattr(pl, "product_code", None)
    )

    n = len(designs)
    field_missing: Dict[str, int] = {f: 0 for f, _, _, _ in _PRODUCT_FIELDS}
    per_entity_scores: List[float] = []
    invalid_hs: List[str] = []

    # Phase 5: description quality counters
    desc_quality_counts: Dict[str, int] = {"none": 0, "poor": 0, "ok": 0, "good": 0}
    # Phase 5: product_local coverage
    pl_linked: int = 0

    for d in designs:
        entity_score = 0.0
        for fname, _, weight, _ in _PRODUCT_FIELDS:
            val = getattr(d, fname, None)
            if val is not None and str(val).strip():
                entity_score += weight
            else:
                field_missing[fname] += 1

        # Extra penalty: HS code present but malformed
        hs = getattr(d, "hs_code", None)
        if hs and not _HS_CODE_RE.match(str(hs).replace(" ", "").replace(".", "")):
            invalid_hs.append(d.design_code)

        per_entity_scores.append(min(1.0, entity_score / _PRODUCT_TOTAL_WEIGHT))

        # Phase 5: description quality
        dq = _desc_quality(getattr(d, "display_name", None))
        desc_quality_counts[dq] += 1

        # Phase 5: product_local coverage check
        # Match on product_ref (design → wFirma product_code) or design_code
        pref = getattr(d, "product_ref", None)
        dcode = getattr(d, "design_code", None)
        if (pref and pref in pl_codes) or (dcode and dcode in pl_codes):
            pl_linked += 1

    completeness = sum(per_entity_scores) / n
    critical_missing_pct = sum(
        field_missing[f] for f, sev, _, _ in _PRODUCT_FIELDS if sev == "critical"
    ) / (n * sum(1 for _, sev, _, _ in _PRODUCT_FIELDS if sev == "critical"))
    confidence = max(0.1, 1.0 - critical_missing_pct * 0.8)

    gaps: List[FieldGap] = []
    for fname, severity, _, adv in _PRODUCT_FIELDS:
        missing = field_missing[fname]
        if missing > 0:
            gaps.append(FieldGap(
                field=fname, affected_count=missing,
                pct=_pct(missing, n), severity=severity, advisory=adv,
            ))
    gaps.sort(key=lambda g: ({"critical": 0, "important": 1, "optional": 2}[g.severity], -g.pct))

    # Phase 5: near-duplicate clusters
    dup_clusters = _design_near_duplicates(designs)

    recs: List[str] = []
    for g in [x for x in gaps if x.severity == "critical"][:2]:
        recs.append(
            f"Fill '{g.field}' for {g.affected_count} design(s) ({g.pct:.0f}%) — {g.advisory}"
        )
    if invalid_hs:
        recs.append(
            f"{len(invalid_hs)} design(s) have malformed HS codes — verify format (4–12 digits): "
            + ", ".join(invalid_hs[:5])
        )
    for g in [x for x in gaps if x.severity == "important" and x.pct > 30][:1]:
        recs.append(
            f"Add '{g.field}' to {g.affected_count} design(s) ({g.pct:.0f}%)"
        )
    # Phase 5: description quality recommendation
    poor_or_none = desc_quality_counts["none"] + desc_quality_counts["poor"]
    if poor_or_none > 0:
        recs.append(
            f"{poor_or_none} design(s) have missing or very short display names — "
            "improve for wFirma product registration and customs descriptions"
        )
    # Phase 5: product_local coverage recommendation
    pl_coverage_pct = _pct(pl_linked, n)
    if pl_coverage_pct < 50 and product_locals:
        recs.append(
            f"Only {pl_coverage_pct:.0f}% of designs have ProductLocal augmentation — "
            "link designs to product_local records for HS code overrides and customs accuracy"
        )
    # Phase 5: near-duplicate advisory
    if dup_clusters:
        recs.append(
            f"Review {len(dup_clusters)} near-duplicate design cluster(s) — "
            "possible data entry duplication in Design Master"
        )

    advisory = (
        f"{n} design(s) scored. "
        f"Completeness: {completeness:.0%}. "
        f"HS code coverage: {_pct(n - field_missing.get('hs_code', 0), n):.0f}%. "
        f"Description quality: {desc_quality_counts['good']} good / "
        f"{desc_quality_counts['ok']} ok / {poor_or_none} poor-or-none."
        + (f" {len(invalid_hs)} malformed HS code(s)." if invalid_hs else "")
        + (f" {len(dup_clusters)} near-duplicate cluster(s)." if dup_clusters else "")
    )

    return DomainScore(
        domain="product", entity_count=n,
        completeness_score=round(completeness, 3),
        confidence=round(confidence, 3),
        field_gaps=gaps,
        duplicate_clusters=dup_clusters,
        advisory=advisory,
        recommendations=recs,
        details={
            "missing_hs_code_count": field_missing.get("hs_code", 0),
            "invalid_hs_code_count": len(invalid_hs),
            "missing_display_name_count": field_missing.get("display_name", 0),
            "missing_unit_count": field_missing.get("unit", 0),
            # Phase 5 additions
            "description_quality": desc_quality_counts,
            "product_local_coverage_pct": round(pl_coverage_pct, 1),
            "product_local_linked_count": pl_linked,
        },
    )


# ── Finishing domain ──────────────────────────────────────────────────────────

_FINISHING_FIELDS: List[tuple] = [
    ("metal",         "critical",  0.40, "metal type required for customs description and HS classification"),
    ("stone_summary", "important", 0.35, "stone summary required for accurate customs description"),
    ("unit",          "important", 0.25, "unit of measure required for PZ line entries"),
]
_FINISHING_TOTAL_WEIGHT = sum(w for _, _, w, _ in _FINISHING_FIELDS)

_KNOWN_METALS = {"gold", "silver", "platinum", "palladium", "rhodium", "titanium",
                 "zoloto", "srebro", "złoto", "gold 14k", "gold 18k", "gold 9k",
                 "white gold", "yellow gold", "rose gold"}


def _score_finishing(designs: List[Any]) -> DomainScore:
    """Score finishing domain.

    Phase 5 additions (over Phase 4):
    - metal/stone compatibility warnings (silver + high-value stone advisory)
    - stone coverage breakdown by stone keyword presence
    """
    if not designs:
        return DomainScore(
            domain="finishing", entity_count=0,
            completeness_score=0.0, confidence=0.0,
            field_gaps=[], duplicate_clusters=[],
            advisory="No design records to score for finishing fields.",
            recommendations=["Register designs with metal/stone data for finishing intelligence."],
            details={},
        )

    n = len(designs)
    field_missing: Dict[str, int] = {f: 0 for f, _, _, _ in _FINISHING_FIELDS}
    per_entity_scores: List[float] = []
    non_standard_metals: List[str] = []
    # Phase 5: stone coverage (designs with at least one recognized stone keyword)
    has_stone_keyword: int = 0

    for d in designs:
        entity_score = 0.0
        for fname, _, weight, _ in _FINISHING_FIELDS:
            val = getattr(d, fname, None)
            if val is not None and str(val).strip():
                entity_score += weight
            else:
                field_missing[fname] += 1

        metal = getattr(d, "metal", None)
        if metal and _norm(metal) not in _KNOWN_METALS:
            non_standard_metals.append(f"{d.design_code}:{metal}")

        # Phase 5: stone keyword presence
        stone = getattr(d, "stone_summary", None)
        if stone:
            stone_lower = stone.lower()
            if any(kw in stone_lower for kw in _STONE_KEYWORDS):
                has_stone_keyword += 1

        per_entity_scores.append(min(1.0, entity_score / _FINISHING_TOTAL_WEIGHT))

    completeness = sum(per_entity_scores) / n
    critical_missing_pct = field_missing.get("metal", 0) / n
    confidence = max(0.1, 1.0 - critical_missing_pct * 0.9)

    gaps: List[FieldGap] = []
    for fname, severity, _, adv in _FINISHING_FIELDS:
        missing = field_missing[fname]
        if missing > 0:
            gaps.append(FieldGap(
                field=fname, affected_count=missing,
                pct=_pct(missing, n), severity=severity, advisory=adv,
            ))
    gaps.sort(key=lambda g: ({"critical": 0, "important": 1, "optional": 2}[g.severity], -g.pct))

    # Phase 5: metal/stone compatibility warnings
    compat_warnings = _metal_stone_compat_warnings(designs)

    recs: List[str] = []
    for g in [x for x in gaps if x.severity == "critical"][:1]:
        recs.append(
            f"Fill '{g.field}' for {g.affected_count} design(s) ({g.pct:.0f}%) — {g.advisory}"
        )
    if non_standard_metals:
        recs.append(
            f"{len(non_standard_metals)} design(s) have non-standard metal values — "
            "review for normalization: " + ", ".join(non_standard_metals[:4])
        )
    stone_gap = field_missing.get("stone_summary", 0)
    if stone_gap > 0:
        recs.append(
            f"{stone_gap} design(s) missing stone_summary — "
            "fill for complete customs description generation"
        )
    # Phase 5: compatibility advisory recommendation
    if compat_warnings:
        recs.append(
            f"{len(compat_warnings)} design(s) have unusual metal/stone combinations — "
            "review: " + "; ".join(
                w["advisory"][:80] for w in compat_warnings[:2]
            )
        )

    advisory = (
        f"{n} design(s) scored for finishing completeness. "
        f"Metal coverage: {_pct(n - field_missing.get('metal', 0), n):.0f}%. "
        f"Stone summary coverage: {_pct(n - field_missing.get('stone_summary', 0), n):.0f}%."
        + (f" {len(compat_warnings)} compatibility advisory flag(s)." if compat_warnings else "")
    )

    return DomainScore(
        domain="finishing", entity_count=n,
        completeness_score=round(completeness, 3),
        confidence=round(confidence, 3),
        field_gaps=gaps,
        duplicate_clusters=[],
        advisory=advisory,
        recommendations=recs,
        details={
            "missing_metal_count": field_missing.get("metal", 0),
            "missing_stone_summary_count": field_missing.get("stone_summary", 0),
            "non_standard_metal_count": len(non_standard_metals),
            # Phase 5 additions
            "stone_keyword_coverage_count": has_stone_keyword,
            "metal_stone_compat_warnings": compat_warnings,
        },
    )


# ── Supplier domain ───────────────────────────────────────────────────────────

_SUPPLIER_FIELDS: List[tuple] = [
    ("wfirma_id",     "critical",  0.25, "wFirma contractor ID required for PZ purchase document linking"),
    ("vat_id",        "critical",  0.20, "VAT ID required for supplier identity verification"),
    ("eori",          "important", 0.15, "EORI required for EU customs declarations"),
    ("contact_email", "important", 0.15, "contact email required for operational communication"),
    ("address",       "important", 0.10, "supplier address required for customs documents"),
    ("contact_phone", "optional",  0.08, "contact phone useful for urgent customs queries"),
    ("bank_account",  "optional",  0.07, "bank account useful for payment processing"),
]
_SUPPLIER_TOTAL_WEIGHT = sum(w for _, _, w, _ in _SUPPLIER_FIELDS)


def _score_suppliers(suppliers: List[Any]) -> DomainScore:
    if not suppliers:
        return DomainScore(
            domain="supplier", entity_count=0,
            completeness_score=0.0, confidence=0.0,
            field_gaps=[], duplicate_clusters=[],
            advisory="No supplier records found.",
            recommendations=["Register suppliers in the Supplier Master for intelligence scoring."],
            details={},
        )

    n = len(suppliers)
    field_missing: Dict[str, int] = {f: 0 for f, _, _, _ in _SUPPLIER_FIELDS}
    per_entity_scores: List[float] = []

    vat_groups: Dict[str, List[str]] = {}
    name_groups: Dict[str, List[str]] = {}

    for s in suppliers:
        entity_score = 0.0
        for fname, _, weight, _ in _SUPPLIER_FIELDS:
            val = getattr(s, fname, None)
            if val is not None and str(val).strip():
                entity_score += weight
            else:
                field_missing[fname] += 1
        per_entity_scores.append(min(1.0, entity_score / _SUPPLIER_TOTAL_WEIGHT))

        vat = re.sub(r"\s", "", getattr(s, "vat_id", None) or "").upper()
        if vat:
            vat_groups.setdefault(vat, []).append(s.name)

        norm_name = _norm(s.name)
        if norm_name:
            name_groups.setdefault(norm_name, []).append(s.supplier_code)

    completeness = sum(per_entity_scores) / n
    critical_missing_pct = sum(
        field_missing[f] for f, sev, _, _ in _SUPPLIER_FIELDS if sev == "critical"
    ) / (n * sum(1 for _, sev, _, _ in _SUPPLIER_FIELDS if sev == "critical"))
    confidence = max(0.1, 1.0 - critical_missing_pct * 0.8)

    gaps: List[FieldGap] = []
    for fname, severity, _, adv in _SUPPLIER_FIELDS:
        missing = field_missing[fname]
        if missing > 0:
            gaps.append(FieldGap(
                field=fname, affected_count=missing,
                pct=_pct(missing, n), severity=severity, advisory=adv,
            ))
    gaps.sort(key=lambda g: ({"critical": 0, "important": 1, "optional": 2}[g.severity], -g.pct))

    dup_clusters: List[DuplicateCluster] = []
    for norm_vat, names in vat_groups.items():
        if len(names) > 1:
            dup_clusters.append(DuplicateCluster(
                key=f"vat:{norm_vat}", entity_keys=names, probability=0.95,
            ))
    for norm_name, codes in name_groups.items():
        if len(codes) > 1 and not any(dc.entity_keys == codes for dc in dup_clusters):
            dup_clusters.append(DuplicateCluster(
                key=f"name:{norm_name}", entity_keys=codes, probability=0.70,
            ))

    recs: List[str] = []
    for g in [x for x in gaps if x.severity == "critical"][:2]:
        recs.append(
            f"Fill '{g.field}' for {g.affected_count} supplier(s) ({g.pct:.0f}%) — {g.advisory}"
        )
    if dup_clusters:
        recs.append(
            f"Review {len(dup_clusters)} potential duplicate supplier cluster(s)"
        )
    for g in [x for x in gaps if x.severity == "important" and x.pct > 30][:1]:
        recs.append(
            f"Add '{g.field}' to {g.affected_count} supplier(s) ({g.pct:.0f}%)"
        )

    advisory = (
        f"{n} supplier(s) scored. "
        f"Completeness: {completeness:.0%}. "
        f"wFirma integration: {_pct(n - field_missing.get('wfirma_id', 0), n):.0f}% linked."
        + (f" {len(dup_clusters)} potential duplicate(s)." if dup_clusters else "")
    )

    return DomainScore(
        domain="supplier", entity_count=n,
        completeness_score=round(completeness, 3),
        confidence=round(confidence, 3),
        field_gaps=gaps,
        duplicate_clusters=dup_clusters,
        advisory=advisory,
        recommendations=recs,
        details={
            "missing_wfirma_id_count": field_missing.get("wfirma_id", 0),
            "missing_vat_id_count": field_missing.get("vat_id", 0),
            "missing_eori_count": field_missing.get("eori", 0),
        },
    )


# ── Readiness domain ──────────────────────────────────────────────────────────

def _score_readiness(
    customers: List[Any],
    designs: List[Any],
    suppliers: List[Any],
    customer_score: DomainScore,
    product_score: DomainScore,
    supplier_score: DomainScore,
) -> DomainScore:
    """Cross-domain readiness: what platform-level blockers exist right now."""

    blockers: List[Dict[str, Any]] = []
    recs: List[str] = []

    # Customer readiness blockers
    no_currency = sum(1 for c in customers if not getattr(c, "default_currency", None))
    no_vat_mode = sum(1 for c in customers if not getattr(c, "vat_mode", None))
    no_nip = sum(1 for c in customers if not getattr(c, "nip", None))
    if no_currency:
        blockers.append({
            "domain": "customer", "blocker": "missing_default_currency",
            "count": no_currency, "impact": "proforma draft generation will fail for these customers",
        })
        recs.append(f"Set default_currency for {no_currency} customer(s) — blocks proforma generation")
    if no_vat_mode:
        blockers.append({
            "domain": "customer", "blocker": "missing_vat_mode",
            "count": no_vat_mode, "impact": "wFirma VAT treatment will be incorrect",
        })
        recs.append(f"Set vat_mode for {no_vat_mode} customer(s) — blocks correct VAT invoicing")

    # Product readiness blockers
    no_hs = sum(1 for d in designs if not getattr(d, "hs_code", None))
    no_metal = sum(1 for d in designs if not getattr(d, "metal", None))
    if no_hs:
        blockers.append({
            "domain": "product", "blocker": "missing_hs_code",
            "count": no_hs, "impact": "customs classification and duty calculation blocked",
        })
        recs.append(f"Add HS codes to {no_hs} design(s) — required for customs clearance")
    if no_metal:
        blockers.append({
            "domain": "finishing", "blocker": "missing_metal",
            "count": no_metal, "impact": "customs description generation incomplete",
        })

    # Supplier readiness blockers
    no_wfirma = sum(1 for s in suppliers if not getattr(s, "wfirma_id", None))
    if no_wfirma:
        blockers.append({
            "domain": "supplier", "blocker": "missing_wfirma_id",
            "count": no_wfirma, "impact": "PZ purchase document cannot be linked to these suppliers",
        })
        recs.append(f"Link {no_wfirma} supplier(s) to wFirma contractor IDs — required for PZ documents")

    # Platform score = weighted average of domain scores
    domain_scores = [customer_score.completeness_score, product_score.completeness_score,
                     supplier_score.completeness_score]
    platform_avg = sum(domain_scores) / len(domain_scores) if domain_scores else 0.0

    # Readiness score = 1 - (blocker impact ratio)
    total_entities = (len(customers) + len(designs) + len(suppliers)) or 1
    blocker_entities = sum(b["count"] for b in blockers)
    readiness_score = max(0.0, 1.0 - (blocker_entities / total_entities) * 0.5)

    confidence = 0.9 if (customers or designs or suppliers) else 0.1

    if not blockers:
        advisory = (
            f"No critical master-data blockers detected across "
            f"{len(customers)} customer(s), {len(designs)} design(s), "
            f"{len(suppliers)} supplier(s). Platform is workflow-ready."
        )
    else:
        advisory = (
            f"{len(blockers)} blocker type(s) detected. "
            f"Highest impact: {blockers[0]['blocker']} ({blockers[0]['count']} record(s)) — "
            f"{blockers[0]['impact']}."
        )

    return DomainScore(
        domain="readiness",
        entity_count=len(customers) + len(designs) + len(suppliers),
        completeness_score=round(readiness_score, 3),
        confidence=round(confidence, 3),
        field_gaps=[],
        duplicate_clusters=[],
        advisory=advisory,
        recommendations=recs,
        details={
            "blocker_count": len(blockers),
            "blockers": blockers,
            "platform_avg_completeness": round(platform_avg, 3),
            "nip_missing": no_nip,
        },
    )


# ── Document domain (Phase 6) ─────────────────────────────────────────────────

def _score_documents(summary: Dict[str, Any]) -> DomainScore:
    """Score document/evidence completeness from deterministic signals.

    Phase 6 addition. Read-only. llm_used=False. No writes.

    Inputs come from ``get_document_coverage_summary()`` — a platform-wide
    aggregate over documents.db (shipment_documents, customs_declarations,
    pz_documents, awb_documents, invoice_lines).

    Completeness score is a weighted average of five coverage dimensions:

        extraction_complete_rate  — docs with extraction_status='extracted'   (0.30)
        awb_linkage_rate          — docs with non-empty awb column             (0.20)
        mrn_linkage_rate          — docs with non-empty related_mrn            (0.15)
        pz_linkage_rate           — docs with non-empty related_pz_no          (0.15)
        workdrive_rate            — pz_documents with both pdf+xlsx uploaded   (0.20)

    Confidence degrades when total_documents == 0 (no evidence to score).
    """
    n = summary.get("total_documents", 0)

    if n == 0:
        return DomainScore(
            domain="document", entity_count=0,
            completeness_score=0.0, confidence=0.0,
            field_gaps=[], duplicate_clusters=[],
            advisory="No shipment documents registered in the document store.",
            recommendations=[
                "Upload purchase invoices, packing lists, and SAD/ZC429 files to "
                "begin document coverage scoring.",
            ],
            details={"total_documents": 0},
        )

    # ── Extraction completeness ───────────────────────────────────────────────
    extraction_counts = summary.get("extraction_status_counts", {})
    extracted = extraction_counts.get("extracted", 0)
    failed    = extraction_counts.get("failed", 0)
    pending   = sum(
        v for k, v in extraction_counts.items()
        if k not in ("extracted", "failed")
    )
    extraction_rate = extracted / n

    # ── Linkage rates ─────────────────────────────────────────────────────────
    awb_linked = summary.get("awb_linked_count", 0)
    mrn_linked = summary.get("mrn_linked_count", 0)
    pz_linked  = summary.get("pz_linked_count", 0)
    awb_rate   = awb_linked / n
    mrn_rate   = mrn_linked / n
    pz_rate    = pz_linked  / n

    # ── WorkDrive coverage ────────────────────────────────────────────────────
    pz_total     = summary.get("pz_document_count", 0)
    pz_workdrive = summary.get("pz_with_workdrive_count", 0)
    workdrive_rate = (pz_workdrive / pz_total) if pz_total > 0 else 1.0
    # No PZ docs at all: treat as neutral (1.0) so it doesn't penalise new installs

    # ── Invoice HS code coverage ──────────────────────────────────────────────
    inv_lines   = summary.get("invoice_line_count", 0)
    inv_hs      = summary.get("invoice_lines_with_hs_code", 0)
    hs_rate     = (inv_hs / inv_lines) if inv_lines > 0 else 1.0

    # ── Weighted completeness ─────────────────────────────────────────────────
    completeness = (
        0.30 * extraction_rate
        + 0.20 * awb_rate
        + 0.15 * mrn_rate
        + 0.15 * pz_rate
        + 0.20 * workdrive_rate
    )

    # ── Confidence — degrades on parser failures ──────────────────────────────
    fail_rate  = failed / n
    confidence = max(0.1, 1.0 - fail_rate * 1.5)

    # ── Field gaps ────────────────────────────────────────────────────────────
    gaps: List[FieldGap] = []

    not_extracted = n - extracted
    if not_extracted > 0:
        sev = "critical" if fail_rate > 0.20 else "important"
        gaps.append(FieldGap(
            field="extraction_status",
            affected_count=not_extracted,
            pct=_pct(not_extracted, n),
            severity=sev,
            advisory=(
                f"{failed} document(s) failed extraction, {pending} pending — "
                "evidence may be incomplete for affected shipments"
            ),
        ))

    not_awb = n - awb_linked
    if not_awb > 0:
        gaps.append(FieldGap(
            field="awb_linkage",
            affected_count=not_awb,
            pct=_pct(not_awb, n),
            severity="important",
            advisory="Documents without AWB cannot be linked to DHL shipment tracking",
        ))

    not_mrn = n - mrn_linked
    if not_mrn > 0:
        gaps.append(FieldGap(
            field="mrn_linkage",
            affected_count=not_mrn,
            pct=_pct(not_mrn, n),
            severity="important",
            advisory="Documents without MRN cannot be linked to SAD/customs clearance records",
        ))

    not_pz = n - pz_linked
    if not_pz > 0:
        gaps.append(FieldGap(
            field="pz_linkage",
            affected_count=not_pz,
            pct=_pct(not_pz, n),
            severity="optional",
            advisory="Documents without PZ reference — purchase receipt may not yet be issued",
        ))

    manual_review = summary.get("requires_manual_review_count", 0)
    if manual_review > 0:
        gaps.append(FieldGap(
            field="requires_manual_review",
            affected_count=manual_review,
            pct=_pct(manual_review, n),
            severity="important",
            advisory="Documents flagged for manual review — extraction quality uncertain",
        ))

    if pz_total > 0:
        pz_missing_wdrive = pz_total - pz_workdrive
        if pz_missing_wdrive > 0:
            gaps.append(FieldGap(
                field="pz_workdrive_upload",
                affected_count=pz_missing_wdrive,
                pct=_pct(pz_missing_wdrive, pz_total),
                severity="optional",
                advisory="PZ output documents without WorkDrive upload — PDF/XLSX not shared",
            ))

    if inv_lines > 0 and hs_rate < 0.90:
        missing_hs = inv_lines - inv_hs
        gaps.append(FieldGap(
            field="invoice_hs_code",
            affected_count=missing_hs,
            pct=_pct(missing_hs, inv_lines),
            severity="important",
            advisory="Invoice lines missing HS code — customs classification incomplete",
        ))

    gaps.sort(key=lambda g: ({"critical": 0, "important": 1, "optional": 2}[g.severity], -g.pct))

    # ── Recommendations ───────────────────────────────────────────────────────
    recs: List[str] = []
    for g in [x for x in gaps if x.severity == "critical"][:1]:
        recs.append(
            f"Resolve extraction failures for {g.affected_count} document(s) "
            f"({g.pct:.0f}%) — {g.advisory}"
        )
    for g in [x for x in gaps if x.severity == "important"][:2]:
        recs.append(
            f"Fix '{g.field}' for {g.affected_count} document(s) "
            f"({g.pct:.0f}%) — {g.advisory}"
        )
    if pz_total > 0 and pz_workdrive < pz_total:
        recs.append(
            f"Upload {pz_total - pz_workdrive} PZ document(s) to WorkDrive "
            "for complete evidence chain"
        )

    # ── Advisory text ─────────────────────────────────────────────────────────
    customs_decl = summary.get("customs_declaration_count", 0)
    customs_cleared = summary.get("customs_with_clearance_date", 0)
    advisory = (
        f"{n} document(s) registered. "
        f"Extraction complete: {extracted}/{n} ({extraction_rate*100:.0f}%). "
        f"AWB linked: {awb_linked}/{n}. "
        f"MRN linked: {mrn_linked}/{n}. "
        f"Customs declarations: {customs_decl}"
        + (f" ({customs_cleared} cleared)." if customs_decl else ".")
    )

    return DomainScore(
        domain="document",
        entity_count=n,
        completeness_score=round(completeness, 3),
        confidence=round(confidence, 3),
        field_gaps=gaps,
        duplicate_clusters=[],
        advisory=advisory,
        recommendations=recs,
        details={
            "total_documents":              n,
            "extraction_complete_count":    extracted,
            "extraction_failed_count":      failed,
            "extraction_pending_count":     pending,
            "awb_linked_count":             awb_linked,
            "mrn_linked_count":             mrn_linked,
            "pz_linked_count":              pz_linked,
            "requires_manual_review_count": manual_review,
            "customs_declaration_count":    customs_decl,
            "customs_with_clearance_date":  customs_cleared,
            "pz_document_count":            pz_total,
            "pz_with_workdrive_count":      pz_workdrive,
            "awb_document_count":           summary.get("awb_document_count", 0),
            "invoice_line_count":           inv_lines,
            "invoice_lines_with_hs_code":   inv_hs,
            "document_type_counts":         summary.get("document_type_counts", {}),
        },
    )


# ── Graph domain (Phase 8) ────────────────────────────────────────────────────

def _score_graph(
    doc_db:      Optional[Path] = None,
    tracking_db: Optional[Path] = None,
) -> DomainScore:
    """Score link-completeness across all batch_id hubs.

    Phase 8 addition. Read-only. llm_used=False. No writes.

    For each distinct batch_id in documents.db, checks which of six link
    dimensions are present:
        awb      -- at least one row with non-empty awb column
        invoice  -- at least one row with non-empty related_invoice_no
        customs  -- at least one row with non-empty related_mrn
        pz       -- at least one row with non-empty related_pz_no
        customer -- at least one row with non-empty client_contractor_id
        supplier -- at least one row with non-empty supplier_contractor_id

    tracking dimension requires tracking_events.db (optional):
        tracking -- at least one shipment_tracking_events row for the batch_id

    completeness_score = average link score across all batches
                         where link_score = linked_dimensions / total_dimensions

    Confidence: 0.3 if no batches; scales toward 0.9 as batch count grows.
    """
    import sqlite3  # local import -- module-level import already present above

    _doc_path  = doc_db      or _DOC_DB
    _track_path = tracking_db or (settings.storage_root / "tracking_events.db")

    _DIMENSIONS = ("awb", "invoice", "customs", "pz", "customer", "supplier", "tracking")
    _n_dims = len(_DIMENSIONS)

    batch_scores:      List[float] = []
    dim_linked_counts: Dict[str, int] = {d: 0 for d in _DIMENSIONS}
    batch_ids:         List[str] = []

    # --- read all batch_ids from documents.db ---------------------------------
    if not _doc_path.exists():
        return DomainScore(
            domain="graph",
            entity_count=0,
            completeness_score=0.0,
            confidence=0.0,
            field_gaps=[FieldGap(
                field="documents_db",
                affected_count=0,
                pct=100.0,
                severity="critical",
                advisory="documents.db not found -- graph link-completeness cannot be scored",
            )],
            duplicate_clusters=[],
            advisory="Graph domain: No data. documents.db absent.",
            recommendations=["Ensure documents.db is initialised and populated before scoring."],
            details={"batch_count": 0, "dimensions": {}, "tracking_db_available": False},
        )

    try:
        con = sqlite3.connect(str(_doc_path), check_same_thread=False, timeout=5)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA query_only = ON")
        rows = con.execute(
            """
            SELECT batch_id,
                   MAX(CASE WHEN awb != '' THEN 1 ELSE 0 END)                    AS has_awb,
                   MAX(CASE WHEN related_invoice_no != '' THEN 1 ELSE 0 END)     AS has_invoice,
                   MAX(CASE WHEN related_mrn != '' THEN 1 ELSE 0 END)            AS has_customs,
                   MAX(CASE WHEN related_pz_no != '' THEN 1 ELSE 0 END)          AS has_pz,
                   MAX(CASE WHEN client_contractor_id != '' THEN 1 ELSE 0 END)   AS has_customer,
                   MAX(CASE WHEN supplier_contractor_id != '' THEN 1 ELSE 0 END) AS has_supplier
            FROM shipment_documents
            WHERE batch_id != ''
            GROUP BY batch_id
            """
        ).fetchall()
        con.close()
    except Exception as exc:  # noqa: BLE001
        log.warning("[mdi] _score_graph documents read failed: %s", exc)
        return DomainScore(
            domain="graph",
            entity_count=0,
            completeness_score=0.0,
            confidence=0.3,
            field_gaps=[],
            duplicate_clusters=[],
            advisory="Graph domain: documents.db read failed.",
            recommendations=[],
            details={"error": str(exc), "batch_count": 0},
        )

    for row in rows:
        bid = row["batch_id"]
        batch_ids.append(bid)
        dim_present = {
            "awb":      bool(row["has_awb"]),
            "invoice":  bool(row["has_invoice"]),
            "customs":  bool(row["has_customs"]),
            "pz":       bool(row["has_pz"]),
            "customer": bool(row["has_customer"]),
            "supplier": bool(row["has_supplier"]),
            "tracking": False,  # filled below if tracking_db available
        }
        for dim, linked in dim_present.items():
            if linked:
                dim_linked_counts[dim] += 1

    # --- check tracking dimension per batch -----------------------------------
    if _track_path.exists() and batch_ids:
        try:
            tcon = sqlite3.connect(str(_track_path), check_same_thread=False, timeout=5)
            tcon.row_factory = sqlite3.Row
            tcon.execute("PRAGMA query_only = ON")
            tracked_batches = set()
            t_rows = tcon.execute(
                "SELECT DISTINCT batch_id FROM shipment_tracking_events WHERE batch_id != '' AND direction='inbound'"
            ).fetchall()
            tcon.close()
            tracked_batches = {r["batch_id"] for r in t_rows}
            for bid in batch_ids:
                if bid in tracked_batches:
                    dim_linked_counts["tracking"] += 1
        except Exception as exc:  # noqa: BLE001
            log.debug("[mdi] _score_graph tracking read failed: %s", exc)

    tracking_db_available = _track_path.exists()
    n_batches = len(batch_ids)

    # --- per-batch scores (tracking only counted if DB available) -------------
    effective_dims = _n_dims if tracking_db_available else (_n_dims - 1)
    if n_batches == 0:
        return DomainScore(
            domain="graph",
            entity_count=0,
            completeness_score=0.0,
            confidence=0.3,
            field_gaps=[FieldGap(
                field="batch_coverage",
                affected_count=0,
                pct=100.0,
                severity="important",
                advisory="No batches with batch_id found in documents.db",
            )],
            duplicate_clusters=[],
            advisory="Graph domain: 0 batches found. Link-completeness cannot be scored.",
            recommendations=["Process at least one shipment batch to enable graph scoring."],
            details={"batch_count": 0, "dimensions": {}, "tracking_db_available": tracking_db_available},
        )

    # Recompute per-batch link score using effective_dims
    # (simplified: use aggregate rates since we don't have per-batch tracking booleans)
    agg_link_sum = sum(
        dim_linked_counts[d]
        for d in ("awb", "invoice", "customs", "pz", "customer", "supplier")
    )
    if tracking_db_available:
        agg_link_sum += dim_linked_counts["tracking"]

    completeness_score = agg_link_sum / (n_batches * effective_dims) if n_batches > 0 else 0.0
    completeness_score = min(1.0, completeness_score)

    confidence = min(0.9, 0.3 + (n_batches / 20.0) * 0.6)

    # --- field gaps (dimensions with <80% coverage) ---------------------------
    gaps: List[FieldGap] = []
    dim_labels = {
        "awb":      "AWB not linked",
        "invoice":  "Invoice reference missing",
        "customs":  "Customs MRN not linked",
        "pz":       "PZ reference missing",
        "customer": "Customer contractor not identified",
        "supplier": "Supplier contractor not identified",
        "tracking": "No tracking events recorded",
    }
    check_dims = list(_DIMENSIONS) if tracking_db_available else [d for d in _DIMENSIONS if d != "tracking"]
    for dim in check_dims:
        rate = dim_linked_counts[dim] / n_batches if n_batches > 0 else 0.0
        missing_pct = round((1.0 - rate) * 100, 1)
        if missing_pct > 20.0:
            severity = "critical" if missing_pct > 60.0 else "important" if missing_pct > 35.0 else "optional"
            gaps.append(FieldGap(
                field=dim,
                affected_count=n_batches - dim_linked_counts[dim],
                pct=missing_pct,
                severity=severity,
                advisory=f"{dim_labels.get(dim, dim)}: {missing_pct}% of batches ({n_batches - dim_linked_counts[dim]}/{n_batches})",
            ))

    # --- recommendations ------------------------------------------------------
    recs: List[str] = []
    if dim_linked_counts.get("awb", 0) < n_batches:
        recs.append("Ensure AWB is populated on all shipment documents.")
    if dim_linked_counts.get("customs", 0) < n_batches:
        recs.append("Link customs MRN to all batches for complete duty traceability.")
    if dim_linked_counts.get("pz", 0) < n_batches:
        recs.append("Link PZ reference on all batches for accounting completeness.")
    if dim_linked_counts.get("supplier", 0) < n_batches:
        recs.append("Identify supplier contractor on all shipment documents.")
    if not tracking_db_available:
        recs.append("Enable DHL tracking pipeline to populate tracking events for all batches.")

    advisory_parts = [
        f"{n_batches} batch(es) scored across {effective_dims} link dimensions.",
        f"Link completeness: {round(completeness_score * 100, 1)}%.",
    ]
    if gaps:
        advisory_parts.append(f"{len(gaps)} dimension(s) below 80% coverage threshold.")

    return DomainScore(
        domain="graph",
        entity_count=n_batches,
        completeness_score=round(completeness_score, 3),
        confidence=round(confidence, 3),
        field_gaps=gaps,
        duplicate_clusters=[],
        advisory=" ".join(advisory_parts),
        recommendations=recs,
        details={
            "batch_count":           n_batches,
            "tracking_db_available": tracking_db_available,
            "dimensions": {
                dim: {
                    "linked": dim_linked_counts[dim],
                    "total":  n_batches,
                    "rate":   round(dim_linked_counts[dim] / n_batches, 3) if n_batches else 0.0,
                }
                for dim in (check_dims)
            },
        },
    )


# ── Entry point ───────────────────────────────────────────────────────────────

def generate_report(domain: Optional[str] = None) -> MasterDataIntelligenceReport:
    """
    Produce a MasterDataIntelligenceReport. Never raises. Never writes.

    domain: None (all) | "customer" | "product" | "finishing" | "supplier"
            | "document" | "graph" | "readiness"
    """
    customers: List[Any] = []
    designs: List[Any] = []
    product_locals: List[Any] = []
    suppliers: List[Any] = []
    doc_summary: Dict[str, Any] = {}

    try:
        cm_init(_CM_DB)
        customers = list_customers(_CM_DB, limit=5000)
    except Exception as exc:
        log.warning("[mdi] customer_master read failed: %s", exc)

    try:
        md_init(_MD_DB)
        designs = list_designs(_MD_DB, limit=5000)
        # Phase 4B Wave 4: overlay-coverage metric counts ACTIVE overlays only.
        product_locals = list_product_local(_MD_DB, active=True, limit=5000)
    except Exception as exc:
        log.warning("[mdi] master_data (designs/product_locals) read failed: %s", exc)

    try:
        supp_init(_SUPP_DB)
        suppliers = list_suppliers(_SUPP_DB, limit=2000)
    except Exception as exc:
        log.warning("[mdi] suppliers read failed: %s", exc)

    try:
        doc_summary = get_document_coverage_summary(_DOC_DB)
    except Exception as exc:
        log.warning("[mdi] document coverage summary failed: %s", exc)

    customer_score  = _score_customers(customers)
    product_score   = _score_products(designs, product_locals=product_locals)
    finishing_score = _score_finishing(designs)
    supplier_score  = _score_suppliers(suppliers)
    document_score  = _score_documents(doc_summary)
    graph_score     = _score_graph()
    readiness_score = _score_readiness(
        customers, designs, suppliers,
        customer_score, product_score, supplier_score,
    )

    # Platform score: weighted average across 7 domains
    # Phase 8 rebalance (7 domains): customer=0.22, product=0.20, finishing=0.16,
    #                                supplier=0.11, document=0.12, graph=0.09, readiness=0.10
    weights = [0.22, 0.20, 0.16, 0.11, 0.12, 0.09, 0.10]
    scores  = [
        customer_score.completeness_score,
        product_score.completeness_score,
        finishing_score.completeness_score,
        supplier_score.completeness_score,
        document_score.completeness_score,
        graph_score.completeness_score,
        readiness_score.completeness_score,
    ]
    platform_score = sum(w * s for w, s in zip(weights, scores))

    # Top 6 recommendations across all domains
    all_recs: List[tuple] = []  # (severity_rank, text)
    for score_obj in (
        customer_score, product_score, finishing_score,
        supplier_score, document_score, graph_score, readiness_score,
    ):
        for i, rec in enumerate(score_obj.recommendations):
            all_recs.append((i, rec))
    top_recs = [r for _, r in sorted(all_recs, key=lambda x: x[0])[:6]]

    return MasterDataIntelligenceReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        llm_used=False,
        advisory_class="R",
        platform_score=round(platform_score, 3),
        customer=customer_score,
        product=product_score,
        finishing=finishing_score,
        supplier=supplier_score,
        document=document_score,
        graph=graph_score,
        readiness=readiness_score,
        top_recommendations=top_recs,
    )
