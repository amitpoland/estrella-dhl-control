"""
AWB save-confirmation gate — fail-open defect fix (2026-07-06 incident).

Live AWB 1129315655 was booked uncompared because (1) the drafts API never
serialized client_contractor_id, so the modal had no Customer Master
baseline, and (2) the gate treated a missing baseline as "nothing to do"
and silently proceeded to booking.

Pins:
  - backend: _draft_to_summary / _draft_to_full serialize the canonical
    client_contractor_id field (additive; existing shape untouched)
  - frontend: baseline state machine (missing-id / loading / loaded /
    failed); the submit gate blocks with a FAIL-VISIBLE panel whenever the
    baseline is not loaded — the exact texts for the missing-id and
    fetch-failed variants; Continue books once, Cancel books nothing
  - NO silent fail-open path remains: doBooking is reachable from submit
    only after the baseline gate passes; computeMasterDiffs' null return
    can no longer route to booking
  - verification guard: the drafts payload proof lives here — browser AWB
    verification must first assert client_contractor_id in the live draft
    payload OR that the fail-visible panel appears
  - DHL adapter untouched; no live DHL calls (zero HTTP in this suite)
"""
from __future__ import annotations

import dataclasses
from pathlib import Path

from app.api.routes_proforma import _draft_to_full, _draft_to_summary
from app.services import proforma_invoice_link_db as pildb


_V2 = Path(__file__).resolve().parents[1] / "app" / "static" / "v2"
JSX = (_V2 / "proforma-detail.jsx").read_text(encoding="utf-8")

MISSING_ID_TEXT = ("No Customer Master baseline is available, "
                   "so shipping details cannot be compared.")
FETCH_FAILED_TEXT = ("Customer Master could not be loaded, "
                     "so shipping details cannot be compared.")


def _draft(**overrides) -> "pildb.ProformaDraft":
    """Minimal ProformaDraft: required fields dummy-filled, defaults kept."""
    kwargs = {}
    for f in dataclasses.fields(pildb.ProformaDraft):
        if (f.default is dataclasses.MISSING
                and f.default_factory is dataclasses.MISSING):
            if f.type in ("int", int):
                kwargs[f.name] = 1
            else:
                kwargs[f.name] = ""
    kwargs.update(overrides)
    return pildb.ProformaDraft(**kwargs)


def _modal_src() -> str:
    start = JSX.index("function AwbGenerateModal")
    end = JSX.index("function ProformaActionBar")
    return JSX[start:end]


# ── Backend: canonical identity serialized ────────────────────────────────────


class TestDraftSerializer:
    def test_summary_includes_client_contractor_id(self):
        d = _draft(client_contractor_id="58541318")
        out = _draft_to_summary(d)
        assert out["client_contractor_id"] == "58541318"

    def test_full_includes_client_contractor_id(self):
        d = _draft(client_contractor_id="58541318")
        out = _draft_to_full(d)
        assert out["client_contractor_id"] == "58541318"

    def test_empty_id_serializes_as_empty_string(self):
        out = _draft_to_summary(_draft(client_contractor_id=""))
        assert out["client_contractor_id"] == ""

    def test_shape_is_additive(self):
        """Existing summary keys are all still present."""
        out = _draft_to_summary(_draft())
        for key in ("id", "batch_id", "client_name", "draft_state", "currency",
                    "wfirma_proforma_id", "wfirma_proforma_fullnumber",
                    "line_count", "created_at", "updated_at"):
            assert key in out, key

    def test_canonical_field_reused_not_invented(self):
        """The serializer reads the existing dataclass field — no new
        identity field was created anywhere."""
        assert any(f.name == "client_contractor_id"
                   for f in dataclasses.fields(pildb.ProformaDraft))


# ── Frontend: baseline state machine ──────────────────────────────────────────


class TestBaselineStateMachine:
    def test_state_machine_present(self):
        src = _modal_src()
        assert "useState('missing-id')" in src
        assert "setMasterState('loading')" in src
        assert "setMasterState('loaded')" in src
        assert "setMasterState('failed')" in src

    def test_fetch_failure_arms_failed_state(self):
        src = _modal_src()
        assert ".catch(() => setMasterState('failed'))" in src

    def test_modal_fetches_master_when_id_exists(self):
        src = _modal_src()
        assert "getCustomerMaster(prefill.client_contractor_id)" in src


# ── Frontend: fail-visible gate (no silent fail-open) ─────────────────────────


class TestFailVisibleGate:
    def test_exact_panel_texts(self):
        assert MISSING_ID_TEXT in JSX
        assert FETCH_FAILED_TEXT in JSX

    def test_gate_blocks_before_any_comparison(self):
        """Submit order: baseline gate → diff gate → doBooking. The baseline
        gate returns with the panel armed whenever masterState is not
        'loaded' — the null-baseline path can never reach booking."""
        src = _modal_src()
        submit = src[src.index("const handleSubmit"):src.index("const doBooking")]
        gate_i = submit.index("masterState !== 'loaded' || !master")
        cmp_i = submit.index("computeMasterDiffs()")
        book_i = submit.rindex("doBooking()")
        assert gate_i < cmp_i < book_i
        gate_block = submit[gate_i:cmp_i]
        assert "setSaveConfirm({" in gate_block and "baselineIssue" in gate_block
        assert "return;" in gate_block
        assert "doBooking" not in gate_block          # gate never books

    def test_no_silent_fail_open_remains(self):
        """The pre-fix pattern (diff-gate guards on `cmp &&` with booking as
        the fall-through for a null baseline) is now unreachable: the ONLY
        doBooking() inside handleSubmit sits after BOTH gates."""
        src = _modal_src()
        submit = src[src.index("const handleSubmit"):src.index("const doBooking")]
        assert submit.count("doBooking()") == 1
        assert submit.index("masterState !== 'loaded'") < submit.index("doBooking()")

    def test_baseline_panel_buttons(self):
        src = _modal_src()
        assert "awb-baseline-panel" in src
        assert "Continue without saving" in src
        # Continue books exactly once via the shared doBooking
        assert ("onClick={() => { setSaveConfirm(null); doBooking(); }}\n"
                "                  data-testid=\"awb-baseline-continue\"" in src)
        # Cancel only dismisses — no booking, no save
        assert ("onClick={() => { setSaveConfirm(null); }}\n"
                "                  data-testid=\"awb-baseline-cancel\"" in src)

    def test_baseline_panel_never_saves_master(self):
        """The baseline panel offers Continue/Cancel only — saveCustomerMaster
        is not reachable from it (nothing to compare, nothing to save)."""
        src = _modal_src()
        panel = src[src.index("awb-baseline-panel"):src.index("awb-master-save-confirm\"")]
        assert "saveCustomerMaster" not in panel

    def test_diff_panel_still_intact(self):
        """The #832 diff panel is unchanged — this fix only adds the
        baseline branch in front of it."""
        src = _modal_src()
        assert "These shipping details are different from Customer Master" in src
        assert "awb-master-save-yes" in src and "awb-master-save-no" in src


# ── Safety ─────────────────────────────────────────────────────────────────────


class TestSafety:
    def test_dhl_adapter_untouched(self):
        live = (Path(__file__).resolve().parents[1]
                / "app" / "services" / "carrier" / "adapters" / "live.py")
        src = live.read_text(encoding="utf-8")
        assert "customer_master" not in src
        assert "masterState" not in src

    def test_verification_guard_documented(self):
        """Process pin: browser AWB verification must first prove the live
        draft payload carries client_contractor_id (this suite's serializer
        tests are that proof for the code; the live payload check is in the
        deploy checklist) or prove the fail-visible panel appears."""
        assert "client_contractor_id" in JSX
        assert MISSING_ID_TEXT in JSX
