"""test_auto_discover_on_intake.py

Auto-discover products at intake (safe, dry-run, non-blocking).

After invoice_lines are stored, intake runs ensure_products_for_batch(dry_run=True)
so products already in wFirma are staged as pending_adoption for one-click Adopt.
Governance: product.auto_register_dry_run is a SAFE_AUTONOMOUS_ACTION — read-only
+ idempotent local mirror, never creates a wFirma good, never auto-adopts.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

_SVC = Path(__file__).resolve().parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.api import routes_intake as ri   # noqa: E402

_SRC = (_SVC / "app" / "api" / "routes_intake.py").read_text(encoding="utf-8")


def test_flag_off_skips_discovery(monkeypatch):
    monkeypatch.setattr(ri.settings, "wfirma_auto_discover_on_intake", False, raising=False)
    with patch("app.services.wfirma_product_auto_register.ensure_products_for_batch") as m:
        ri._auto_discover_products_on_intake("BATCH_X")
    m.assert_not_called()


def test_flag_on_runs_dry_run_only(monkeypatch):
    monkeypatch.setattr(ri.settings, "wfirma_auto_discover_on_intake", True, raising=False)
    with patch(
        "app.services.wfirma_product_auto_register.ensure_products_for_batch",
        return_value={"scanned": 31, "existing_mapped": 0, "pending_adoption": 31,
                      "missing": 0, "failed": 0},
    ) as m:
        ri._auto_discover_products_on_intake("BATCH_X")
    m.assert_called_once()
    args, kwargs = m.call_args
    assert (args and args[0] == "BATCH_X") or kwargs.get("batch_id") == "BATCH_X"
    assert kwargs.get("dry_run") is True          # never a write-mode create
    assert kwargs.get("operator") == "intake_auto_discover"


def test_non_blocking_on_wfirma_failure(monkeypatch):
    monkeypatch.setattr(ri.settings, "wfirma_auto_discover_on_intake", True, raising=False)
    with patch(
        "app.services.wfirma_product_auto_register.ensure_products_for_batch",
        side_effect=RuntimeError("wFirma unreachable"),
    ):
        # Must NOT raise — intake must never fail because discovery failed.
        ri._auto_discover_products_on_intake("BATCH_X")


# ── Source guards: wired at both intake paths; dry-run only ─────────────────

def test_helper_defined_and_dry_run_only():
    assert "def _auto_discover_products_on_intake(" in _SRC
    # The helper must call ensure_products_for_batch in DRY-RUN mode only.
    assert "dry_run=True" in _SRC and 'operator="intake_auto_discover"' in _SRC
    # It must never trigger a write-mode create from intake.
    assert "ensure_products_for_batch(\n            batch_id, dry_run=False" not in _SRC


def test_wired_at_both_intake_call_sites():
    # shipment_intake (after invoice loop) + add_document_to_batch (invoice branch)
    assert _SRC.count("_auto_discover_products_on_intake(batch_id)") >= 2


def test_flag_gated_and_non_blocking_in_source():
    idx = _SRC.index("def _auto_discover_products_on_intake(")
    body = _SRC[idx:idx + 1400]
    assert "wfirma_auto_discover_on_intake" in body      # flag gate
    assert "except Exception" in body                    # non-blocking guard
