"""
PLT (Paperless Trade) eligibility checker.

Pure function — no I/O, no DB, no HTTP, no file reads.
All inputs are supplied by the caller; no globals are read except the
blocked-status constant.

Eligibility rules (applied in order):
  1. Gate check  — carrier_plt_status must not be "pending".
  2. Invoice     — at least one invoice path must be present.
  3. Customs doc — a customs document path must be present.
  4. Country     — destination country must be in the caller-supplied allowlist.

Default-deny: an empty allowlist makes every country ineligible.
"""
from __future__ import annotations

from typing import Collection

from ..models.plt import PltEligibilityRequest, PltEligibilityResult

# Statuses that block all PLT eligibility evaluation.
_PLT_BLOCKED_STATUSES: frozenset = frozenset({"pending"})


def check_eligibility(
    request: PltEligibilityRequest,
    plt_status: str,
    country_allowlist: Collection[str],
) -> PltEligibilityResult:
    """
    Return an eligibility result for the given PLT request.

    Parameters
    ----------
    request:
        Eligibility request containing batch metadata and document references.
    plt_status:
        Value of carrier_plt_status from settings ("pending" | "shadow" | "live").
    country_allowlist:
        Iterable of ISO alpha-2 country codes that are permitted for PLT.
        Case-insensitive. Empty → all countries ineligible.
    """
    # 1. Gate: reject if PLT is not yet activated.
    if plt_status in _PLT_BLOCKED_STATUSES:
        return PltEligibilityResult(
            eligible=False,
            batch_id=request.batch_id,
            reason=(
                f"PLT gate is not active (carrier_plt_status={plt_status!r}). "
                "Set CARRIER_PLT_STATUS=shadow or live to enable."
            ),
        )

    # 2. Invoice presence.
    if not request.invoice_paths:
        return PltEligibilityResult(
            eligible=False,
            batch_id=request.batch_id,
            reason="No invoice documents provided for PLT.",
        )

    # 3. Customs document presence.
    if request.customs_doc_path is None:
        return PltEligibilityResult(
            eligible=False,
            batch_id=request.batch_id,
            reason="No customs document (SAD/ZC429) provided for PLT.",
        )

    # 4. Destination country allowlist.
    normalised_country = request.destination_country.upper()
    normalised_allowlist = {c.upper() for c in country_allowlist}
    if normalised_country not in normalised_allowlist:
        return PltEligibilityResult(
            eligible=False,
            batch_id=request.batch_id,
            reason=(
                f"Destination country {normalised_country!r} is not in the "
                "PLT country allowlist."
            ),
        )

    return PltEligibilityResult(
        eligible=True,
        batch_id=request.batch_id,
        reason="",
    )
