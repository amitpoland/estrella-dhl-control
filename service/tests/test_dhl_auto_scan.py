"""
test_dhl_auto_scan.py
======================
Source-grep + structural tests for the DHL automated inbox-check endpoint
and the Task Scheduler PowerShell script.

Coverage:
  A. /scheduled-inbox-check endpoint (routes_dhl_clearance.py)
     - endpoint registered
     - calls run_ingestion_cycle (one Zoho scan per call)
     - checks _is_active before processing each batch
     - calls _apply_cache_to_audit
     - calls _ensure_dhl_reply (triggers B2 if conditions met)
     - returns structured summary
  B. PowerShell automation script (scripts/dhl-email-auto-scan.ps1)
     - script exists
     - calls the correct endpoint
     - reads API key from C:\\PZ\\.env
     - logs output
  C. Safety properties
     - inactive batches skipped (skipped_inactive counter)
     - no financial writes in endpoint
     - no wFirma imports in endpoint
"""
from __future__ import annotations

import re
from pathlib import Path

# ── File paths ────────────────────────────────────────────────────────────────
_ROUTE  = Path(__file__).parent.parent / "app" / "api" / "routes_dhl_clearance.py"
_SCRIPT = Path(__file__).parent.parent / "scripts" / "dhl-email-auto-scan.ps1"


# ══════════════════════════════════════════════════════════════════════════════
# A. Endpoint structural tests
# ══════════════════════════════════════════════════════════════════════════════

def _sched_block(src: str) -> str:
    """Extract the scheduled-inbox-check function body."""
    idx = src.index("scheduled-inbox-check")
    end = src.find("\n@router.", idx)
    return src[idx: end] if end > idx else src[idx:]


def test_scheduled_inbox_check_endpoint_registered():
    """POST /api/v1/dhl/scheduled-inbox-check must be registered in the router."""
    src = _ROUTE.read_text(encoding="utf-8", errors="replace")
    assert "scheduled-inbox-check" in src, (
        "POST /api/v1/dhl/scheduled-inbox-check endpoint must be present in "
        "routes_dhl_clearance.py"
    )


def test_endpoint_calls_run_ingestion_cycle():
    """Endpoint must call run_ingestion_cycle for the Zoho inbox scan."""
    src = _ROUTE.read_text(encoding="utf-8", errors="replace")
    block = _sched_block(src)
    assert "run_ingestion_cycle" in block, (
        "scheduled-inbox-check must call run_ingestion_cycle() "
        "to perform the Zoho inbox scan"
    )
    assert "_run_ing" in block or "run_ingestion_cycle" in block


def test_endpoint_checks_is_active_per_batch():
    """Endpoint must call _is_active per batch to skip terminal/delivered ones."""
    src = _ROUTE.read_text(encoding="utf-8", errors="replace")
    block = _sched_block(src)
    assert "_batch_active" in block or "_is_active" in block, (
        "scheduled-inbox-check must check _is_active per batch — "
        "terminal/delivered batches must be skipped"
    )


def test_endpoint_applies_cache():
    """Endpoint must call _apply_cache_to_audit to write dhl_email.received."""
    src = _ROUTE.read_text(encoding="utf-8", errors="replace")
    block = _sched_block(src)
    assert "_apply_cache_to_audit" in block, (
        "scheduled-inbox-check must call _apply_cache_to_audit to write "
        "dhl_email.received from the Zoho scan cache"
    )


def test_endpoint_triggers_b2():
    """Endpoint must call _ensure_dhl_reply to trigger B2 DSK reply."""
    src = _ROUTE.read_text(encoding="utf-8", errors="replace")
    block = _sched_block(src)
    assert "_ensure_dhl_reply" in block, (
        "scheduled-inbox-check must call _ensure_dhl_reply to trigger B2 "
        "DSK reply when dhl_email.received is set"
    )


def test_endpoint_counts_inactive_skips():
    """Endpoint must count inactive batch skips (skipped_inactive counter)."""
    src = _ROUTE.read_text(encoding="utf-8", errors="replace")
    block = _sched_block(src)
    assert "skipped_inactive" in block, (
        "scheduled-inbox-check must track skipped_inactive count so operators "
        "can verify old/closed batches are being excluded"
    )


def test_endpoint_returns_b2_sent_count():
    """Endpoint must track and return b2_sent for observability."""
    src = _ROUTE.read_text(encoding="utf-8", errors="replace")
    block = _sched_block(src)
    assert "b2_sent" in block, (
        "scheduled-inbox-check must return b2_sent count — "
        "operators need to verify DSK emails were actually sent"
    )


# ══════════════════════════════════════════════════════════════════════════════
# B. PowerShell automation script
# ══════════════════════════════════════════════════════════════════════════════

def test_auto_scan_script_exists():
    """scripts/dhl-email-auto-scan.ps1 must exist."""
    assert _SCRIPT.exists(), (
        f"DHL auto-scan script missing at {_SCRIPT} — "
        "create it so Windows Task Scheduler can call the endpoint"
    )


def test_script_calls_correct_endpoint():
    """Script must call /api/v1/dhl/scheduled-inbox-check."""
    src = _SCRIPT.read_text(encoding="utf-8", errors="replace")
    assert "scheduled-inbox-check" in src, (
        "dhl-email-auto-scan.ps1 must call /api/v1/dhl/scheduled-inbox-check"
    )


def test_script_reads_api_key_from_env():
    """Script must read API key from C:\\PZ\\.env, not hardcode it."""
    src = _SCRIPT.read_text(encoding="utf-8", errors="replace")
    assert ".env" in src, (
        "dhl-email-auto-scan.ps1 must read API_KEY from C:\\PZ\\.env — "
        "never hardcode credentials in the script"
    )
    assert "API_KEY" in src, (
        "dhl-email-auto-scan.ps1 must extract API_KEY from the .env file"
    )
    # Ensure no raw key literal (simple heuristic — no long alphanumeric strings)
    long_literals = re.findall(r'"[A-Za-z0-9_\-]{40,}"', src)
    assert len(long_literals) == 0, (
        f"dhl-email-auto-scan.ps1 must not contain hardcoded credentials. "
        f"Found long literals: {long_literals}"
    )


def test_script_logs_output():
    """Script must write to a log file for operational visibility."""
    src = _SCRIPT.read_text(encoding="utf-8", errors="replace")
    assert "log" in src.lower() and (".log" in src or "Write-Log" in src), (
        "dhl-email-auto-scan.ps1 must write to a log file — "
        "silent scripts make incidents invisible"
    )


# ══════════════════════════════════════════════════════════════════════════════
# C. Safety properties
# ══════════════════════════════════════════════════════════════════════════════

def test_endpoint_no_financial_writes():
    """scheduled-inbox-check must not touch any financial fields."""
    src = _ROUTE.read_text(encoding="utf-8", errors="replace")
    block = _sched_block(src)
    forbidden_financial = [
        "total_value", "cif_", "duty_", "freight_", "invoice_total",
        "proforma", "landed_cost",
    ]
    for term in forbidden_financial:
        assert term not in block.lower(), (
            f"scheduled-inbox-check must not write financial field '{term}'"
        )


def test_endpoint_no_wfirma_imports():
    """scheduled-inbox-check must not import or call wFirma."""
    src = _ROUTE.read_text(encoding="utf-8", errors="replace")
    block = _sched_block(src)
    assert "wfirma" not in block.lower(), (
        "scheduled-inbox-check must not call wFirma APIs — "
        "DHL email scanning is pre-accounting"
    )
