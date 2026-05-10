"""
Pure data models for the PLT (Paperless Trade) subsystem.

No business logic. No HTTP. No DB. No file I/O.
File bytes are never embedded in these models — only metadata references.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class PltEligibilityRequest:
    """Input to the PLT eligibility check."""

    batch_id: str
    destination_country: str        # ISO 3166-1 alpha-2 (e.g. "DE", "US")
    invoice_paths: List[Path]       # must be non-empty for eligibility
    customs_doc_path: Optional[Path] = None  # SAD / ZC429 document


@dataclass
class PltEligibilityResult:
    """Result of a PLT eligibility check."""

    eligible: bool
    batch_id: str
    reason: str = ""  # non-empty only when eligible=False


@dataclass
class PltDocumentRef:
    """
    Metadata reference to a PLT document file.

    Deliberately excludes file content — no bytes field.
    Callers that need bytes must open path themselves.
    """

    path: Path
    filename: str
    size_bytes: int
    checksum_sha256: str  # hex digest, not raw bytes


@dataclass
class PltPackage:
    """
    Assembled set of PLT document references for a batch.

    Contains only metadata — no file bytes are embedded.
    """

    batch_id: str
    invoice_refs: List[PltDocumentRef] = field(default_factory=list)
    customs_doc_ref: Optional[PltDocumentRef] = None
    created_at: str = ""  # ISO 8601 UTC timestamp
