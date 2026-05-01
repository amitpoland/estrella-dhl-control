from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel


class BatchSummary(BaseModel):
    lines:       int
    total_net:   float
    total_gross: float
    duty_pln:    float


class VerificationSummary(BaseModel):
    invoice_refs_match:   Optional[bool]
    cif_match:            Optional[bool]
    qty_match_by_type:    Optional[bool]
    importer_match:       Optional[bool]
    exporter_match:       Optional[bool]
    blocked_phrases_clean: Optional[bool]
    duty_rate_ok:         Optional[bool]
    amendment_flags:      List[str]


class OutputFiles(BaseModel):
    pdf_url:  str   # e.g. /api/v1/files/{batch_id}/PZ_xxx.pdf
    xlsx_url: str


class CorrectionSummary(BaseModel):
    """Compact correction summary included in ProcessResponse."""
    has_critical:  bool
    has_warning:   bool
    total_items:   int
    critical_keys: List[str] = []
    warning_keys:  List[str] = []


class ProcessResponse(BaseModel):
    status:          Literal["success", "partial", "failed", "blocked"]
    batch_id:        str
    document_no:     str
    summary:         Optional[BatchSummary]      = None
    verification:    Optional[VerificationSummary] = None
    files:           Optional[OutputFiles]       = None
    corrections_log: List[str]                   = []
    errors:          List[str]                   = []
    cliq_posted:     bool                        = False
    audit_score:     Optional[int]               = None   # 0–100
    audit_risk_level: Optional[str]              = None   # LOW / MEDIUM / HIGH RISK
    correction_summary: Optional[CorrectionSummary] = None  # auto-correction engine output


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    engine: str
    environment: str
    detail: Dict[str, Any] = {}
