"""Master Data Intelligence — Phase 4 advisory scoring engine.

Deterministic, read-only. llm_used=False. No writes.

Domains:
  customer   — completeness, VAT status, duplicate probability
  product    — completeness, HS classification, finishing coverage
  finishing  — metal/stone/unit field coverage per design
  supplier   — completeness, wFirma integration, duplicate probability
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
from .customer_master_db import list_customers, init_db as cm_init
from .master_data_db import list_designs, init_db as md_init
from .suppliers_db import list_suppliers, init_db as supp_init

log = get_logger(__name__)

# ── DB paths (read-only) ──────────────────────────────────────────────────────

_CM_DB   = settings.storage_root / "customer_master.sqlite"
_MD_DB   = settings.storage_root / "master_data.sqlite"
_SUPP_DB = settings.storage_root / "suppliers.sqlite"

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
            "readiness": _ds(self.readiness),
            "top_recommendations": self.top_recommendations,
        }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _norm(s: Optional[str]) -> str:
    """Normalize string for dedup: lowercase, NFD, strip legal suffixes."""
    if not s:
        return ""
    t = unicodedata.normalize("NFD", s.lower().strip())
    # strip common legal entity suffixes for name-based dedup
    for suffix in (" sp z o.o.", " sp. z o.o.", " s.a.", " gmbh", " ltd", " llp",
                   " b.v.", " s.r.o.", " s.r.l.", " inc.", " inc", " corp."):
        if t.endswith(suffix):
            t = t[: -len(suffix)].strip()
    return re.sub(r"\s+", " ", t)


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


def _score_products(designs: List[Any]) -> DomainScore:
    if not designs:
        return DomainScore(
            domain="product", entity_count=0,
            completeness_score=0.0, confidence=0.0,
            field_gaps=[], duplicate_clusters=[],
            advisory="No design/product master records found.",
            recommendations=["Register designs in the Design Master to enable product intelligence."],
            details={},
        )

    n = len(designs)
    field_missing: Dict[str, int] = {f: 0 for f, _, _, _ in _PRODUCT_FIELDS}
    per_entity_scores: List[float] = []
    invalid_hs: List[str] = []

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

    advisory = (
        f"{n} design(s) scored. "
        f"Completeness: {completeness:.0%}. "
        f"HS code coverage: {_pct(n - field_missing.get('hs_code', 0), n):.0f}%."
        + (f" {len(invalid_hs)} malformed HS code(s)." if invalid_hs else "")
    )

    return DomainScore(
        domain="product", entity_count=n,
        completeness_score=round(completeness, 3),
        confidence=round(confidence, 3),
        field_gaps=gaps,
        duplicate_clusters=[],
        advisory=advisory,
        recommendations=recs,
        details={
            "missing_hs_code_count": field_missing.get("hs_code", 0),
            "invalid_hs_code_count": len(invalid_hs),
            "missing_display_name_count": field_missing.get("display_name", 0),
            "missing_unit_count": field_missing.get("unit", 0),
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

    advisory = (
        f"{n} design(s) scored for finishing completeness. "
        f"Metal coverage: {_pct(n - field_missing.get('metal', 0), n):.0f}%. "
        f"Stone summary coverage: {_pct(n - field_missing.get('stone_summary', 0), n):.0f}%."
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


# ── Entry point ───────────────────────────────────────────────────────────────

def generate_report(domain: Optional[str] = None) -> MasterDataIntelligenceReport:
    """
    Produce a MasterDataIntelligenceReport. Never raises. Never writes.

    domain: None (all) | "customer" | "product" | "finishing" | "supplier" | "readiness"
    """
    customers: List[Any] = []
    designs: List[Any] = []
    suppliers: List[Any] = []

    try:
        cm_init(_CM_DB)
        customers = list_customers(_CM_DB, limit=5000)
    except Exception as exc:
        log.warning("[mdi] customer_master read failed: %s", exc)

    try:
        md_init(_MD_DB)
        designs = list_designs(_MD_DB, limit=5000)
    except Exception as exc:
        log.warning("[mdi] master_data (designs) read failed: %s", exc)

    try:
        supp_init(_SUPP_DB)
        suppliers = list_suppliers(_SUPP_DB, limit=2000)
    except Exception as exc:
        log.warning("[mdi] suppliers read failed: %s", exc)

    customer_score = _score_customers(customers)
    product_score  = _score_products(designs)
    finishing_score = _score_finishing(designs)
    supplier_score = _score_suppliers(suppliers)
    readiness_score = _score_readiness(
        customers, designs, suppliers,
        customer_score, product_score, supplier_score,
    )

    # Platform score: weighted average
    weights = [0.30, 0.25, 0.20, 0.15, 0.10]
    scores  = [
        customer_score.completeness_score,
        product_score.completeness_score,
        finishing_score.completeness_score,
        supplier_score.completeness_score,
        readiness_score.completeness_score,
    ]
    platform_score = sum(w * s for w, s in zip(weights, scores))

    # Top 5 recommendations across domains
    all_recs: List[tuple] = []  # (severity_rank, text)
    for score_obj in (customer_score, product_score, finishing_score, supplier_score, readiness_score):
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
        readiness=readiness_score,
        top_recommendations=top_recs,
    )
