"""
test_b2_clearance_path_gate.py — Phase 0.5 gate test.

Spec rule: when a DHL customs email arrives, the same-thread reply fires
only when clearance_decision.clearance_path is explicitly set to the
agency value (B2 → external_agency_clearance) or the self-clearance
value (carrier-self → carrier_self_clearance). Missing /
"routing_pending" / unknown values must default-block both branches.

Phase 1.1 will rename to spec names (agency_clearance / dhl_self_
clearance); this test pins behaviour against the current code names.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

_SVC = Path(__file__).parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))


def _audit(path_value):
    return {
        "dhl_email": {"received": True},
        "clearance_decision": (
            {"clearance_path": path_value, "total_value_usd": 9999.0}
            if path_value is not None
            else {"total_value_usd": 9999.0}
        ),
    }


def _patched_ensure(audit_dict):
    """Call _ensure_dhl_reply with both branch helpers stubbed.
    Returns ('agency', 'self_clear', or 'noop') indicating which branch fired."""
    from app.services import active_shipment_monitor as asm

    calls = {"agency": 0, "self_clear": 0}

    def _fake_agency(audit_path, audit):
        calls["agency"] += 1
        return {"built": True, "branch": "agency"}

    def _fake_self(audit_path, audit):
        calls["self_clear"] += 1
        return {"built": True, "branch": "self_clear"}

    with patch.object(asm, "_ensure_dhl_dsk_transfer_reply", side_effect=_fake_agency), \
         patch.object(asm, "_ensure_dhl_self_clearance_reply", side_effect=_fake_self):
        result = asm._ensure_dhl_reply(Path("/tmp/fake/audit.json"), audit_dict)

    if calls["agency"]:
        return "agency", result
    if calls["self_clear"]:
        return "self_clear", result
    return "noop", result


# ── B2 fires for explicit Path B ───────────────────────────────────────────

def test_path_b_fires_dsk_transfer_reply():
    """external_agency_clearance + DHL email received → B2 (DSK transfer) fires."""
    branch, _ = _patched_ensure(_audit("external_agency_clearance"))
    assert branch == "agency"


# ── Path A does NOT fire B2 ────────────────────────────────────────────────

def test_path_a_does_not_fire_b2_high_cif_irrelevant():
    """carrier_self_clearance + high CIF → self-clearance reply, NOT B2.
    Even if CIF appears > 2500 (data inconsistency), the explicit path wins."""
    branch, _ = _patched_ensure(_audit("carrier_self_clearance"))
    assert branch == "self_clear"


# ── Default-block on missing / routing_pending / unknown path ─────────────

def test_unset_clearance_path_blocks_b2():
    """Missing clearance_decision → no branch fires (safe default)."""
    branch, _ = _patched_ensure(_audit(None))
    assert branch == "noop"


def test_routing_pending_blocks_b2():
    """routing_pending → no branch fires even with high CIF in audit."""
    branch, _ = _patched_ensure(_audit("routing_pending"))
    assert branch == "noop"


def test_unknown_clearance_path_blocks_b2():
    """Unknown path values default-block. Defends against typos."""
    branch, _ = _patched_ensure(_audit("totally_unknown_value"))
    assert branch == "noop"


def test_spec_name_agency_clearance_fires_b2():
    """Phase 1.1: spec name 'agency_clearance' now flows through
    normalize_path and fires B2 (DSK transfer reply)."""
    branch, _ = _patched_ensure(_audit("agency_clearance"))
    assert branch == "agency"


def test_spec_name_dhl_self_clearance_fires_self_clear():
    """Phase 1.1: spec name 'dhl_self_clearance' fires the self-
    clearance branch (counterpart to B2 for low-value path)."""
    branch, _ = _patched_ensure(_audit("dhl_self_clearance"))
    assert branch == "self_clear"


# ── DHL email gate is preserved ────────────────────────────────────────────

def test_no_dhl_email_blocks_both_branches():
    audit = {
        "dhl_email": {"received": False},
        "clearance_decision": {"clearance_path": "external_agency_clearance"},
    }
    branch, _ = _patched_ensure(audit)
    assert branch == "noop"
