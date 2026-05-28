"""
test_closure_eval_pz_authority.py — Regression tests for the Closure Evaluation
pzGenerated authority fix (2026-05-29).

Fix: pzGenerated in the Closure Evaluation gate now checks wfirma_pz_doc_id as
     ground truth (Layer 0), in addition to pz_pdf_filename and pz_generated_at.

Before the fix: batches with a real wFirma PZ document (doc ID set) but no
  local pz_pdf_filename / pz_generated_at in the audit showed:
  "⚠ PZ document must be generated first (PZ / Accounting tab)"
  ...blocking the operator from running Evaluate Closure Readiness.

After the fix: wfirma_pz_doc_id is treated as authoritative PZ existence proof —
  same authority rule as _derive_pz_status Layer 0 (Python side).

Real-world cases: AWB 4183498255, AWB 9198333502, AWB 6049349806.
"""
from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
_SHIPMENT_DETAIL = _ROOT / "service" / "app" / "static" / "shipment-detail.html"


def _src() -> str:
    return _SHIPMENT_DETAIL.read_text(encoding="utf-8")


def _closure_eval_block(src: str) -> str:
    """Return the ~2000-char section starting at the Closure Evaluation guard.

    Anchored to 'closure-eval-card' testid to avoid matching the earlier
    pzGenerated definition at a different position in the file.
    """
    anchor = src.find("closure-eval-card")
    assert anchor != -1, "closure-eval-card testid not found in shipment-detail.html"
    # Walk back to the pzGenerated computation (it appears ~200 chars before the card)
    region_start = max(0, anchor - 800)
    region_end = anchor + 2000
    return src[region_start:region_end]


# ---------------------------------------------------------------------------
# Authority alignment tests
# ---------------------------------------------------------------------------

class TestClosureEvalPzGeneratedAuthority:
    """pzGenerated in the Closure Evaluation block must use wfirma_pz_doc_id
    as ground truth — same rule as _derive_pz_status Layer 0 on the Python side."""

    def test_pz_generated_checks_wfirma_doc_id(self):
        """pzGenerated must include wfirma_pz_doc_id in its truth check.

        A batch with wfirma_pz_doc_id set is PZ-complete regardless of whether
        pz_pdf_filename or pz_generated_at are present in the audit.
        This mirrors the Python _derive_pz_status Layer 0 rule.
        """
        block = _closure_eval_block(_src())
        assert "wfirma_pz_doc_id" in block, (
            "Closure eval pzGenerated must check wfirma_pz_doc_id — wFirma doc ID "
            "is the ground-truth proof of PZ completion (same as _derive_pz_status "
            "Layer 0). Fix: include (audit.wfirma_export || {}).wfirma_pz_doc_id "
            "in the pzGenerated expression."
        )

    def test_pz_generated_still_checks_pz_pdf_filename(self):
        """pzGenerated must still check pz_pdf_filename (backward compat)."""
        block = _closure_eval_block(_src())
        assert "pz_pdf_filename" in block, (
            "pzGenerated must still check pz_pdf_filename for backward compatibility"
        )

    def test_pz_generated_still_checks_pz_generated_at(self):
        """pzGenerated must still check pz_generated_at (backward compat)."""
        block = _closure_eval_block(_src())
        assert "pz_generated_at" in block, (
            "pzGenerated must still check pz_generated_at for backward compatibility"
        )

    def test_wfirma_export_accessed_safely(self):
        """wfirma_export must be accessed with a null-guard in the pzGenerated block.

        Pattern: (_wfExport.wfirma_pz_doc_id || ...) where _wfExport = (audit.wfirma_export || {})
        This prevents TypeError when wfirma_export is absent from the audit.
        """
        block = _closure_eval_block(_src())
        assert "wfirma_export" in block, (
            "Closure eval block must read audit.wfirma_export (with null-guard) "
            "to safely access wfirma_pz_doc_id"
        )

    def test_disabled_reason_text_present(self):
        """The 'PZ document must be generated first' reason text must still exist."""
        src = _src()
        assert "PZ document must be generated first" in src, (
            "Disabled reason text for missing PZ must remain present — "
            "used when pzGenerated is false (no PDF, no generated_at, no doc ID)"
        )

    def test_closure_eval_gate_uses_pz_generated(self):
        """closureEvalDisabled must reference pzGenerated."""
        block = _closure_eval_block(_src())
        assert "pzGenerated" in block, (
            "closureEvalDisabled must reference pzGenerated — "
            "so batches with no PZ at all still block the eval button"
        )

    def test_closure_eval_card_testid_present(self):
        """closure-eval-card data-testid must exist (structural integrity check)."""
        src = _src()
        assert "closure-eval-card" in src, (
            "closure-eval-card testid missing from shipment-detail.html"
        )
