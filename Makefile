# PZ Import Processor — task runner
# ===================================
# Prerequisites: python3, pdfplumber, requests (pip3 install pdfplumber requests)

PYTHON  := python3
TEST    := test_pz_regression.py
PROC    := pz_import_processor.py

.PHONY: help verify verify-full reference install-hooks

# ── Default target ────────────────────────────────────────────────────────────
help:
	@echo ""
	@echo "  PZ Import Processor"
	@echo "  ─────────────────────────────────────────────────────────"
	@echo ""
	@echo "  make verify        Fast regression (unit + format, no PDFs, ~2 s)"
	@echo "  make verify-full   Full regression (+ golden PDF pipeline, ~30 s)"
	@echo "  make reference     Regenerate reference_batch/ expected outputs"
	@echo "  make install-hooks Install pre-commit hook (blocks commits if golden tests fail)"
	@echo ""
	@echo "  To generate a PZ for a new batch:"
	@echo "    $(PYTHON) $(PROC) \\"
	@echo "        --invoices ./batch/ \\"
	@echo "        --zc429    ZC429_xxx_PL.pdf \\"
	@echo "        --clipboard \\"
	@echo "        --pdf      PZ_output.pdf \\"
	@echo "        --xlsx     PZ_calc.xlsx \\"
	@echo "        --doc-no   \"PZ NN/N/YYYY\""
	@echo ""
	@echo "  RULE: make verify must pass before any live batch is processed."
	@echo "  ─────────────────────────────────────────────────────────"
	@echo ""

# ── Fast gate (no PDFs) ───────────────────────────────────────────────────────
verify:
	@echo ""
	@echo "  ── Fast regression (unit + format) ──"
	@$(PYTHON) $(TEST)

# ── Full golden pipeline (requires real PDFs from shipment 039–044) ───────────
verify-full:
	@echo ""
	@echo "  ── Full golden regression (unit + format + PDF pipeline) ──"
	@$(PYTHON) $(TEST) --e2e

# ── Regenerate reference_batch/ expected outputs (pinned rate, deterministic) ──
_REF_DIR    := reference_batch
_REF_INV    := $(_REF_DIR)/invoices
_REF_ZC429  := $(_REF_DIR)/ZC429_26PL44302D008N8OR0_1_PL.pdf
_REF_RATE   := 3.6506
_REF_DOC_NO := PZ — Shipment 039–044 (reference)

# ── Install git hooks ─────────────────────────────────────────────────────────
install-hooks:
	@cp hooks/pre-commit .git/hooks/pre-commit
	@chmod +x .git/hooks/pre-commit
	@echo "  ✅ pre-commit hook installed (.git/hooks/pre-commit)"
	@echo "     golden_constants.py changes will now require passing tests."

reference:
	@echo ""
	@echo "  ── Regenerating reference_batch/ expected outputs ──"
	@echo "     Rate pinned to $(_REF_RATE) (NBP Table 069/A/NBP/2026)"
	@$(PYTHON) $(PROC) \
		--invoices $(_REF_INV)/ \
		--zc429    $(_REF_ZC429) \
		--rate     $(_REF_RATE) \
		--pdf      $(_REF_DIR)/expected_PZ.pdf \
		--xlsx     $(_REF_DIR)/expected_calc.xlsx \
		--doc-no   "$(_REF_DOC_NO)"
	@echo "  ✅ Reference outputs updated."
