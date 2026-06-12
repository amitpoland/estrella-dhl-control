"""Regression: clipboard/JSON generation must NEVER drop the wFirma PZ link.

Root cause (2026-06-12, ff1f4b5): _patch_audit_wfirma rebuilt audit.wfirma_export
from scratch on every clipboard/JSON generation, keeping only the 5 generation
flags and DROPPING the PZ-creation authority fields (wfirma_pz_doc_id,
wfirma_pz_fullnumber, pz_source, pz_created_at). GET /wfirma/json and
POST /wfirma/clipboard both call it, so generating an export for an
already-created PZ silently wiped the link.

Proof from production: SHIPMENT_9938632830 had doc_id 188300707 ("PZ 2/6/2026");
after a JSON generation its wfirma_export held only
{clipboard_generated, json_generated, last_generated_at, row_count, mode}.

Fix A: spread **existing (merge, additive flags). Fix B: fail-closed guard that
aborts the write if it would drop a non-empty wfirma_pz_doc_id.

These tests fail pre-fix, pass post-fix.
"""
from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

import pytest

_SVC = Path(__file__).resolve().parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.api.routes_wfirma import _patch_audit_wfirma


def _seed_created_pz(tmp_path: Path) -> Path:
    """Write an audit.json representing a batch with a created wFirma PZ."""
    out = tmp_path / "outputs" / "BATCH"
    out.mkdir(parents=True)
    audit = {
        "status": "partial",
        "wfirma_export": {
            "wfirma_pz_doc_id":     "188300707",
            "wfirma_pz_fullnumber": "PZ 2/6/2026",
            "pz_source":            "created_via_app",
            "pz_created_at":        "2026-06-10T12:00:57",
        },
    }
    (out / "audit.json").write_text(json.dumps(audit), encoding="utf-8")
    return out


def _link(out: Path) -> dict:
    we = json.loads((out / "audit.json").read_text(encoding="utf-8"))["wfirma_export"]
    return we


@pytest.mark.parametrize("mode", ["json", "clipboard"])
def test_generation_preserves_pz_link(tmp_path, mode):
    out = _seed_created_pz(tmp_path)
    _patch_audit_wfirma(out, mode, row_count=18)
    we = _link(out)
    # PZ authority fields preserved
    assert we["wfirma_pz_doc_id"]     == "188300707", we
    assert we["wfirma_pz_fullnumber"] == "PZ 2/6/2026", we
    assert we["pz_source"]            == "created_via_app", we
    assert we["pz_created_at"]        == "2026-06-10T12:00:57", we
    # Generation flag added (additive)
    assert we[f"{mode}_generated"] is True, we
    assert we["row_count"] == 18
    assert we["mode"] == mode


def test_repeated_generation_does_not_remove_link(tmp_path):
    """Operator-specified: create PZ -> json -> clipboard -> json -> clipboard.
    The PZ link and its companion fields must be unchanged after every cycle."""
    out = _seed_created_pz(tmp_path)
    before = _link(out)
    for mode in ("json", "clipboard", "json", "clipboard"):
        _patch_audit_wfirma(out, mode, row_count=18)
        we = _link(out)
        assert we["wfirma_pz_doc_id"]     == before["wfirma_pz_doc_id"], (mode, we)
        assert we["wfirma_pz_fullnumber"] == before["wfirma_pz_fullnumber"], (mode, we)
        assert we["pz_source"]            == before["pz_source"], (mode, we)
        assert we["pz_created_at"]        == before["pz_created_at"], (mode, we)
    # Both generation flags are now set, link intact.
    final = _link(out)
    assert final["clipboard_generated"] is True
    assert final["json_generated"] is True
    assert final["wfirma_pz_doc_id"] == "188300707"


def test_generation_on_batch_without_link_still_writes_flags(tmp_path):
    """No regression for the normal pre-create case: a batch with no PZ link
    still gets its generation flags written."""
    out = tmp_path / "outputs" / "B2"
    out.mkdir(parents=True)
    (out / "audit.json").write_text(json.dumps({"status": "partial"}), encoding="utf-8")
    _patch_audit_wfirma(out, "json", row_count=3)
    we = _link(out)
    assert we["json_generated"] is True
    assert we["row_count"] == 3
    assert "wfirma_pz_doc_id" not in we or not we.get("wfirma_pz_doc_id")


# ── Source-grep pins (workflow-class guard against future regression) ────────

def test_patch_audit_wfirma_spreads_existing_and_has_failclosed_guard():
    src = inspect.getsource(_patch_audit_wfirma)
    assert "**existing" in src, (
        "_patch_audit_wfirma must spread **existing (Fix A) so generation "
        "writes never drop wfirma_pz_doc_id."
    )
    assert "wfirma_pz_doc_id" in src and "ABORT" in src, (
        "_patch_audit_wfirma must keep the fail-closed guard (Fix B) that "
        "aborts rather than persist a link-dropping write."
    )
