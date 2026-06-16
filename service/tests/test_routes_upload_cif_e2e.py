"""
test_routes_upload_cif_e2e.py — end-to-end regression for the routes_upload AWB
customs-value ingest → ``awb_customs`` persistence → ``cif_resolver`` tri-state →
clearance decision chain.

Why this module exists (Issue #629)
-----------------------------------
PR #627 (``e4d96b5``) introduced the tri-state CIF authority resolver so a
missing customs value resolves to UNKNOWN rather than a fabricated ``0.00``.
The resolver (``test_cif_resolver``) and the clearance mapping
(``test_clearance_cif_tristate``) are each unit-tested on hand-crafted audits.
The AWB-text extractor (``test_awb_customs_value``) is unit-tested in isolation.

What was NOT covered: the ROUTE-LEVEL seam — that the ``awb_customs`` block
``routes_upload._run_dhl_precheck`` actually *persists* is shaped to feed
``resolve_cif`` correctly across all three tri-state outcomes, including the
merge-not-downgrade guard that protects a previously-captured good value from a
later gap read. A future ``routes_upload`` change could silently regress that
contract while every isolated unit test stays green.

These tests exercise the REAL persistence function (no stub of the route logic).
Only the PDF *text extractor* (``parse_awb_pdf``) is patched — its own parsing
is covered by ``test_awb_customs_value`` and is not the subject here; the subject
is what the route does with the extractor's output.

Three tri-state outcomes asserted end-to-end:
  1. positive Custom Val      → persisted value → RESOLVED  (USD value, no gap)
  2. explicit declared zero   → persisted 0.0   → DECLARED_ZERO (distinct path)
  3. extraction failure / gap → persisted None  → UNKNOWN (never a fake 0.00)

Plus the merge-not-downgrade guard: a later gap read must NOT downgrade a
previously-persisted good value to None.

Proof point: AWB 2315714531 / CIF USD 732 — the shipment whose only customs
authority was the carrier-declared AWB Custom Val.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

_SVC = Path(__file__).parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.api.routes_upload import _run_dhl_precheck
from app.services import awb_parser as _awb_parser_mod
from app.services.cif_resolver import (
    CIF_DECLARED_ZERO,
    CIF_RESOLVED,
    CIF_UNKNOWN,
    resolve_cif,
)
from app.services.clearance_decision import THRESHOLD_USD, build_clearance_decision
from app.services.clearance_path_alias import (
    PATH_DHL_SELF_CLEARANCE,
    PATH_ROUTING_PENDING,
    is_dhl_self_clearance,
    is_routing_pending,
)


# ── Harness ───────────────────────────────────────────────────────────────────

def _seed_batch(tmp_path: Path, *, seed_audit: dict | None = None) -> tuple[Path, Path, Path]:
    """Build a throwaway batch tree under tmp_path.

    Returns (output_dir, inv_dir, audit_path). ``inv_dir`` is created EMPTY so
    the invoice-CIF branch yields nothing and the AWB Custom Val fallback path
    runs (the branch under test). A dummy ``awb.pdf`` is placed under
    ``source/awb/`` so the route's ``glob("*.pdf")`` finds a file to parse — its
    bytes are irrelevant because ``parse_awb_pdf`` is patched.
    """
    output_dir = tmp_path / "outputs" / "BATCH_629"
    inv_dir = output_dir / "source" / "invoices"
    awb_dir = output_dir / "source" / "awb"
    inv_dir.mkdir(parents=True, exist_ok=True)
    awb_dir.mkdir(parents=True, exist_ok=True)
    (awb_dir / "awb.pdf").write_bytes(b"%PDF-1.4 dummy")  # patched parser ignores content

    audit_path = output_dir / "audit.json"
    audit = {"awb": "2315714531", "carrier": "DHL"}
    if seed_audit:
        audit.update(seed_audit)
    audit_path.write_text(json.dumps(audit), encoding="utf-8")
    return output_dir, inv_dir, audit_path


def _patch_awb(monkeypatch, return_value: dict) -> None:
    """Patch the AWB text extractor the route lazily imports.

    The route does ``from ..services.awb_parser import parse_awb_pdf`` at call
    time, so patching the attribute on the module object is honoured.
    """
    monkeypatch.setattr(_awb_parser_mod, "parse_awb_pdf", lambda _p: dict(return_value))


def _run_precheck(output_dir: Path, inv_dir: Path) -> dict:
    """Invoke the real async persistence function and return the persisted audit."""
    asyncio.run(_run_dhl_precheck("BATCH_629", output_dir, inv_dir, "DHL"))
    return json.loads((output_dir / "audit.json").read_text(encoding="utf-8"))


# ── Case 1: positive Custom Val → RESOLVED ────────────────────────────────────

def test_positive_awb_custom_val_persists_and_resolves(tmp_path, monkeypatch):
    """A real positive AWB Custom Val (USD 732) is persisted as a usable
    ``awb_customs`` block and resolves to RESOLVED → DHL self-clearance."""
    output_dir, inv_dir, _ = _seed_batch(tmp_path)
    _patch_awb(monkeypatch, {"customs_value": 732.0, "currency": "USD"})

    audit = _run_precheck(output_dir, inv_dir)

    # Persistence shape
    awb = audit["awb_customs"]
    assert awb["value_usd"] == pytest.approx(732.0)
    assert awb["currency"] == "USD"
    assert awb["gap"] is None

    # Resolver reads the persisted block
    res = resolve_cif(audit)
    assert res["cif_state"] == CIF_RESOLVED
    assert res["cif_usd"] == pytest.approx(732.0)
    assert res["cif_source"] == "awb_customs.value_usd"
    assert res["extraction_gap"] is None

    # Clearance projection (732 < 2500 → carrier self-clearance, no DSK)
    dec = build_clearance_decision(audit)
    assert dec["cif_state"] == CIF_RESOLVED
    assert is_dhl_self_clearance(dec["clearance_path"])
    assert dec["clearance_path"] == PATH_DHL_SELF_CLEARANCE
    assert dec["total_value_usd"] == pytest.approx(732.0)
    assert dec["require_dsk"] is False
    assert dec["cif_extraction_gap"] is None


# ── Case 2: explicit declared zero → DECLARED_ZERO ────────────────────────────

def test_declared_zero_awb_persists_and_is_declared_zero(tmp_path, monkeypatch):
    """An explicit 0.00 USD Custom Val with no gap is a genuine declared zero —
    persisted as value_usd 0.0 and resolved DECLARED_ZERO, kept distinct from an
    extraction failure."""
    output_dir, inv_dir, _ = _seed_batch(tmp_path)
    _patch_awb(monkeypatch, {"customs_value": 0.0, "currency": "USD"})

    audit = _run_precheck(output_dir, inv_dir)

    awb = audit["awb_customs"]
    assert awb["value_usd"] == 0.0           # explicit zero persisted, not None
    assert awb["currency"] == "USD"
    assert awb["gap"] is None

    res = resolve_cif(audit)
    assert res["cif_state"] == CIF_DECLARED_ZERO
    assert res["cif_usd"] == 0.0
    assert res["cif_source"] == "awb_customs.value_usd"
    assert res["extraction_gap"] is None

    dec = build_clearance_decision(audit)
    assert dec["cif_state"] == CIF_DECLARED_ZERO
    assert dec["clearance_path"] == PATH_DHL_SELF_CLEARANCE
    assert dec["total_value_usd"] == 0.0
    assert dec["require_dsk"] is False
    assert dec["decision_reason"] == "cif_declared_zero"


# ── Case 3: extraction failure / missing → UNKNOWN, never 0.00 ────────────────

def test_extraction_gap_persists_none_and_resolves_unknown(tmp_path, monkeypatch):
    """The core no-fake-zero guard: a parser miss (label present, no value) must
    persist value_usd=None — NOT 0.0 — and resolve to UNKNOWN with an
    operator-actionable extraction gap and routing_pending clearance.

    An invoice IS recorded as uploaded (``invoice_names``) so the resolver's gap
    diagnosis (``cif_resolver._diagnose_gap``) walks past the invoice-upload and
    invoice-parse steps and lands on the AWB Custom Val as the terminal failed
    layer — the proximate cause here. Without an uploaded invoice the resolver
    would (correctly) name ``invoice_upload`` as the first gap instead, which is
    a different scenario than the AWB-extraction-failure one under test.
    """
    output_dir, inv_dir, _ = _seed_batch(
        tmp_path, seed_audit={"invoice_names": ["inv_629.pdf"]}
    )
    _patch_awb(
        monkeypatch,
        {"customs_value": None, "currency": "", "customs_value_gap": "label_no_value"},
    )

    audit = _run_precheck(output_dir, inv_dir)

    awb = audit["awb_customs"]
    assert awb["value_usd"] is None           # the whole point: NOT a fabricated 0.0
    assert awb["value_usd"] != 0.0
    assert awb["gap"] == "label_no_value"

    res = resolve_cif(audit)
    assert res["cif_state"] == CIF_UNKNOWN
    assert res["cif_usd"] is None             # never 0.0
    assert res["cif_source"] == "unavailable"
    assert res["extraction_gap"] is not None
    assert res["extraction_gap"]["first_failed_layer"] == "awb_customs.value_usd"

    dec = build_clearance_decision(audit)
    assert dec["cif_state"] == CIF_UNKNOWN
    assert is_routing_pending(dec["clearance_path"])
    assert dec["clearance_path"] == PATH_ROUTING_PENDING
    assert dec["total_value_usd"] == 0.0      # presented as 0.0 but cif_state is UNKNOWN
    assert dec["require_dsk"] is None
    assert dec["cif_extraction_gap"] is not None
    assert dec["decision_reason"] == "cif_zero_routing_pending"


# ── Merge-not-downgrade guard ─────────────────────────────────────────────────

def test_later_gap_read_does_not_downgrade_prior_good_value(tmp_path, monkeypatch):
    """A previously-persisted good value (USD 732) must survive a subsequent run
    whose AWB parse came back as a gap. The route's merge-not-replace logic
    preserves the prior value AND its usable state — a gap read must NEVER null
    out a real captured value, and must NEVER poison the gating ``gap`` field.

    This is the regression that exposed a real defect (Issue #629): the prior
    merge code overwrote ``gap`` with the failed re-read's value. Because
    ``cif_resolver`` treats ANY truthy ``gap`` as an unusable layer
    (``cif_resolver.py`` ~L156), that overwrite silently downgraded the
    preserved good value to UNKNOWN at resolution time — defeating the very
    merge-not-downgrade guard the branch exists to provide. The fix records the
    failed re-read under the non-gating ``last_reread_gap`` diagnostic key and
    leaves ``gap`` as the preserved value's (None).
    """
    output_dir, inv_dir, _ = _seed_batch(
        tmp_path,
        seed_audit={
            "awb_customs": {"value_usd": 732.0, "currency": "USD", "gap": None}
        },
    )
    # This run's AWB parse fails to read a value.
    _patch_awb(
        monkeypatch,
        {"customs_value": None, "currency": "", "customs_value_gap": "label_no_value"},
    )

    audit = _run_precheck(output_dir, inv_dir)

    awb = audit["awb_customs"]
    assert awb["value_usd"] == pytest.approx(732.0)   # prior good value preserved
    assert awb["currency"] == "USD"
    assert awb["gap"] is None                         # gating field NOT poisoned
    assert awb["last_reread_gap"] == "label_no_value"  # failed re-read recorded non-gatingly

    # The chain still resolves from the preserved value — the whole point.
    res = resolve_cif(audit)
    assert res["cif_state"] == CIF_RESOLVED
    assert res["cif_usd"] == pytest.approx(732.0)
    assert res["cif_source"] == "awb_customs.value_usd"


def test_positive_read_upgrades_prior_gap(tmp_path, monkeypatch):
    """The complement: when a prior run only captured a gap (value None) and a
    later run reads a real value, the good value must replace the gap."""
    output_dir, inv_dir, _ = _seed_batch(
        tmp_path,
        seed_audit={
            "awb_customs": {"value_usd": None, "currency": "", "gap": "label_no_value"}
        },
    )
    _patch_awb(monkeypatch, {"customs_value": 732.0, "currency": "USD"})

    audit = _run_precheck(output_dir, inv_dir)

    awb = audit["awb_customs"]
    assert awb["value_usd"] == pytest.approx(732.0)
    assert awb["gap"] is None

    res = resolve_cif(audit)
    assert res["cif_state"] == CIF_RESOLVED
    assert res["cif_usd"] == pytest.approx(732.0)
