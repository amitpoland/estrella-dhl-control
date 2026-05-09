"""
test_proforma_fullnumber_phase91.py — Phase 9.1:
persist wFirma Proforma fullnumber for the legacy /proforma/create
route via mark_draft_issued.

Coverage:
  1. mark_draft_issued persists fullnumber when provided.
  2. mark_draft_issued is backwards-compatible when omitted (existing
     stored fullnumber, if any, must be preserved untouched).
  3. mark_draft_issued raises KeyError when the draft row is absent.
  4. mark_draft_issued still requires wfirma_proforma_id.
  5. Empty fullnumber argument behaves as "do not write" (no clobber).
  6. Legacy /proforma/create route forwards
     ProformaResult.wfirma_invoice_number into mark_draft_issued.
"""
from __future__ import annotations

import inspect
import sqlite3
from pathlib import Path

import pytest

from app.services import proforma_invoice_link_db as pildb


# ── Helpers ────────────────────────────────────────────────────────────────

@pytest.fixture()
def db_path(tmp_path) -> Path:
    p = tmp_path / "proforma_links.db"
    pildb.init_db(p)
    return p


def _seed_pending_draft(db: Path, *, batch="B1", client_name="ACME"):
    """Create a draft in pending_local state ready to be marked issued."""
    d, _ = pildb.upsert_pending_draft(
        db,
        batch_id          = batch,
        client_name       = client_name,
        currency          = "EUR",
        exchange_rate     = None,
        source_lines_json = "[]",
    )
    return d


# ── 1. mark_draft_issued persists fullnumber when provided ─────────────────

def test_mark_draft_issued_persists_fullnumber(db_path):
    _seed_pending_draft(db_path)
    pildb.mark_draft_issued(
        db_path, "B1", "ACME",
        wfirma_proforma_id         = "WF-9001",
        wfirma_proforma_fullnumber = "PROF 92/2026",
    )
    fresh = pildb.get_draft(db_path, "B1", "ACME")
    assert fresh.status                     == "issued"
    assert fresh.wfirma_proforma_id         == "WF-9001"
    assert fresh.wfirma_proforma_fullnumber == "PROF 92/2026"


def test_mark_draft_issued_strips_whitespace_in_fullnumber(db_path):
    _seed_pending_draft(db_path)
    pildb.mark_draft_issued(
        db_path, "B1", "ACME",
        wfirma_proforma_id         = "WF-9001",
        wfirma_proforma_fullnumber = "  PROF 92/2026  ",
    )
    fresh = pildb.get_draft(db_path, "B1", "ACME")
    assert fresh.wfirma_proforma_fullnumber == "PROF 92/2026"


# ── 2. backwards-compatible when omitted ──────────────────────────────────

def test_mark_draft_issued_omitted_arg_does_not_clobber(db_path):
    """A previously-stored fullnumber must NOT be wiped when a later
    caller marks issued without supplying the kwarg. This protects
    legacy callers that never set it from accidentally clearing a
    Phase-9 / Phase-9.1-set value."""
    _seed_pending_draft(db_path)
    # First call sets fullnumber.
    pildb.mark_draft_issued(
        db_path, "B1", "ACME",
        wfirma_proforma_id         = "WF-9001",
        wfirma_proforma_fullnumber = "PROF 92/2026",
    )
    # Reset status back so the second mark-issued call has work to do.
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            "UPDATE proforma_drafts SET status='pending_local' "
            "WHERE batch_id='B1' AND client_name='ACME'"
        )
        conn.commit()
    # Second call omits the kwarg — fullnumber must survive.
    pildb.mark_draft_issued(
        db_path, "B1", "ACME",
        wfirma_proforma_id = "WF-9002",
    )
    fresh = pildb.get_draft(db_path, "B1", "ACME")
    assert fresh.wfirma_proforma_id         == "WF-9002"
    assert fresh.wfirma_proforma_fullnumber == "PROF 92/2026"


def test_mark_draft_issued_signature_kwarg_default(db_path):
    """Pin the kwarg + default. Any future change must be intentional."""
    sig = inspect.signature(pildb.mark_draft_issued)
    p = sig.parameters
    assert "wfirma_proforma_fullnumber" in p
    assert p["wfirma_proforma_fullnumber"].default == ""


def test_mark_draft_issued_legacy_caller_still_works(db_path):
    """A pre-Phase-9.1 caller that supplied only wfirma_proforma_id
    keeps working — fullnumber stays empty."""
    _seed_pending_draft(db_path)
    pildb.mark_draft_issued(
        db_path, "B1", "ACME",
        wfirma_proforma_id = "WF-OLD",
    )
    fresh = pildb.get_draft(db_path, "B1", "ACME")
    assert fresh.status                     == "issued"
    assert fresh.wfirma_proforma_id         == "WF-OLD"
    assert fresh.wfirma_proforma_fullnumber == ""


# ── 3. row-not-found / id-required regressions ────────────────────────────

def test_mark_draft_issued_raises_when_no_draft(db_path):
    with pytest.raises(KeyError):
        pildb.mark_draft_issued(
            db_path, "MISSING", "NOBODY",
            wfirma_proforma_id         = "WF-X",
            wfirma_proforma_fullnumber = "PROF 1/2026",
        )


def test_mark_draft_issued_still_requires_id(db_path):
    _seed_pending_draft(db_path)
    with pytest.raises(ValueError) as exc:
        pildb.mark_draft_issued(
            db_path, "B1", "ACME",
            wfirma_proforma_id         = "",
            wfirma_proforma_fullnumber = "PROF 92/2026",
        )
    assert "wfirma_proforma_id is required" in str(exc.value)


# ── 4. empty-string fullnumber: explicit no-op ────────────────────────────

def test_mark_draft_issued_empty_fullnumber_is_noop(db_path):
    """Explicit empty-string is treated the same as omitted — do not
    write the column. This mirrors test_omitted_arg_does_not_clobber
    but pins the explicit-empty case."""
    _seed_pending_draft(db_path)
    # Pre-seed a fullnumber via direct UPDATE so we can verify
    # mark_draft_issued doesn't blank it out.
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            "UPDATE proforma_drafts SET wfirma_proforma_fullnumber='PRESERVED' "
            "WHERE batch_id='B1' AND client_name='ACME'"
        )
        conn.commit()
    pildb.mark_draft_issued(
        db_path, "B1", "ACME",
        wfirma_proforma_id         = "WF-9001",
        wfirma_proforma_fullnumber = "",
    )
    fresh = pildb.get_draft(db_path, "B1", "ACME")
    assert fresh.wfirma_proforma_fullnumber == "PRESERVED"


# ── 5. Legacy /proforma/create route forwards the new field ───────────────

def test_legacy_create_route_forwards_fullnumber_kwarg():
    """Source-grep the legacy route — confirm it threads
    result.wfirma_invoice_number into mark_draft_issued.

    We pin this with a static read because exercising the full create
    route requires mocking ~6 wFirma helpers + the preview builder.
    The Phase 9 file already covers the Phase-5 path end-to-end.
    """
    routes_path = (
        Path(__file__).resolve().parent.parent
        / "app" / "api" / "routes_proforma.py"
    )
    src = routes_path.read_text(encoding="utf-8")
    # Find the mark_draft_issued call inside the legacy /create handler.
    needle = "pildb.mark_draft_issued("
    idx = src.find(needle)
    assert idx > 0, "legacy create route must call pildb.mark_draft_issued"
    # Grab the call block by walking the parenthesis depth from the
    # opening "(" so nested calls like `_proforma_db_path()` don't
    # short-circuit the match on their own close-paren.
    open_paren = idx + len(needle) - 1
    depth = 0
    end = open_paren
    for j in range(open_paren, len(src)):
        c = src[j]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                end = j
                break
    block = src[idx:end + 1]
    # The route must thread BOTH kwargs from the ProformaResult.
    assert "wfirma_proforma_id" in block
    assert "wfirma_proforma_fullnumber" in block, (
        "Legacy create route must forward result.wfirma_invoice_number "
        "into mark_draft_issued via the new wfirma_proforma_fullnumber kwarg"
    )
    assert "result.wfirma_invoice_number" in block


# ── 6. Re-call with same id + new fullnumber updates the column ───────────

def test_mark_draft_issued_reissue_updates_fullnumber(db_path):
    """An adopt-or-reissue scenario: same row, mark_draft_issued called
    twice with different fullnumbers. The second call wins."""
    _seed_pending_draft(db_path)
    pildb.mark_draft_issued(
        db_path, "B1", "ACME",
        wfirma_proforma_id         = "WF-1",
        wfirma_proforma_fullnumber = "PROF 1/2026",
    )
    # Reset to pending so the second mark_issued has a row to write.
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            "UPDATE proforma_drafts SET status='pending_local' "
            "WHERE batch_id='B1' AND client_name='ACME'"
        )
        conn.commit()
    pildb.mark_draft_issued(
        db_path, "B1", "ACME",
        wfirma_proforma_id         = "WF-2",
        wfirma_proforma_fullnumber = "PROF 2/2026",
    )
    fresh = pildb.get_draft(db_path, "B1", "ACME")
    assert fresh.wfirma_proforma_id         == "WF-2"
    assert fresh.wfirma_proforma_fullnumber == "PROF 2/2026"
