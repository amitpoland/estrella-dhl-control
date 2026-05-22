"""sad_invoice_authority.py — derive SAD invoice-reference authority from audit.

Single authority for classifying the SAD/ZC429 invoice-reference state.
Consumed by the batch detail API to expose a stable, frontend-readable
``sad_invoice_authority`` dict. The frontend must render from this object
only — never from raw zc429.inferred_refs or corrections_log entries.

status values
-------------
matched_structured_n935          N935 field found; references match parsed invoices.
n935_present_mismatch            N935 field found; references do NOT match invoices.
n935_absent                      N935 field not present in the SAD document.
unverified_no_structured_reference
    ZC429 not yet processed, OR invoice_refs_method is
    "inferred_from_sad_free_text" (free-text tokens are advisory only —
    they never become authority references and are never surfaced to operators
    as invoice identifiers).

Free-text inference NEVER enters this object
--------------------------------------------
Numeric tokens extracted from SAD free text (e.g. 3322, 121, 088, 2026, 2027)
are not invoice references. They must never be shown to operators as if they
were structured identifiers. Only N935-derived references (e.g. "EJL/26-27/039")
are included in the ``references`` list. Invoice IDs such as "088/2026-2027"
are preserved intact — never split into component tokens.

inferred_refs in audit.zc429 is intentionally excluded from the authority
object. It remains in audit.json for the AI customs evidence recovery layer,
which reads it for context. Do not remove it from audit.json.
"""
from __future__ import annotations


def derive_sad_invoice_authority(audit: dict) -> dict:
    """Derive SAD invoice-reference authority from a loaded audit dict.

    Pure function — no I/O, no side effects. Exception handling is the
    caller's responsibility (routes_dashboard.py wraps with try/except).

    Args:
        audit: Full audit.json content (may include derived enrichments).

    Returns:
        Dict with keys: status, source, references, matched_invoice_ids,
        warning, review_reason.
    """
    zc429 = audit.get("zc429") or {}
    ver   = audit.get("verification") or {}

    if not zc429:
        return {
            "status":              "unverified_no_structured_reference",
            "source":              "none",
            "references":          [],
            "matched_invoice_ids": [],
            "warning":             None,
            "review_reason":       "ZC429/SAD not yet processed.",
        }

    method = zc429.get("invoice_refs_method", "not_found")
    # N935-derived references only — never inferred_refs
    refs = [r for r in (zc429.get("invoice_refs") or []) if r]

    # ── N935 structured reference present ─────────────────────────────────────
    if method == "N935":
        match       = ver.get("invoice_refs_match")   # True | False | None
        matched_ids = ver.get("parsed_invoice_nos") or []

        if match is True:
            return {
                "status":              "matched_structured_n935",
                "source":              "n935",
                "references":          refs,
                "matched_invoice_ids": matched_ids,
                "warning":             None,
                "review_reason":       None,
            }

        if match is False:
            return {
                "status":              "n935_present_mismatch",
                "source":              "n935",
                "references":          refs,
                "matched_invoice_ids": matched_ids,
                "warning":             (
                    "N935 invoice references do not match parsed invoice files."
                ),
                "review_reason": (
                    "Verify SAD document against uploaded invoice PDFs."
                ),
            }

        # match is None — N935 present but verification could not be completed
        return {
            "status":              "unverified_no_structured_reference",
            "source":              "n935",
            "references":          refs,
            "matched_invoice_ids": [],
            "warning":             None,
            "review_reason": (
                "N935 references present but invoice match could not be determined. "
                "Re-process invoices to complete verification."
            ),
        }

    # ── N935 absent ───────────────────────────────────────────────────────────
    if method == "not_found":
        return {
            "status":              "n935_absent",
            "source":              "none",
            "references":          [],
            "matched_invoice_ids": [],
            "warning":             None,
            "review_reason": (
                "SAD document contains no N935 invoice reference field."
            ),
        }

    # ── Free-text inference (method == "inferred_from_sad_free_text") ─────────
    # Advisory only — numeric tokens from free text are NOT invoice references.
    # Do not surface inferred_refs to operators.
    return {
        "status":              "unverified_no_structured_reference",
        "source":              "advisory_text",
        "references":          [],    # inferred_refs intentionally excluded
        "matched_invoice_ids": [],
        "warning":             None,
        "review_reason": (
            "Structured N935 reference absent. "
            "Free-text extraction is advisory only — not used for verification."
        ),
    }
