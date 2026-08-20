"""A posted proforma must still accept shipping-preparation facts.

Goods are boxed, weighed and dispatched AFTER the commercial document is posted.
Box selection and operator-confirmed net/gross/tare are dispatch metadata, not
fiscal content — but they were routed through the generic draft-edit preamble,
which accepts only draft/editing/post_failed. So once a proforma was posted the
operator could no longer record the box or the weight the parcel actually needs,
and the UI surfaced it as a 409.

These tests pin the seam by BEHAVIOUR: what the database ends up holding and what
the document's fiscal state is afterwards — never by grepping source.

Nothing here contacts a carrier or creates a shipment.
"""
from __future__ import annotations

import json
import pathlib
import sqlite3
import sys

import pytest

_ROOT = pathlib.Path(__file__).parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

BATCH = "BATCH_TRANSPORT_SEAM"
CLIENT = "DG GmbH"


@pytest.fixture()
def db(tmp_path):
    from app.services import proforma_invoice_link_db as pildb

    path = tmp_path / "proforma_links.db"
    pildb.init_db(path)
    return path


# proforma_drafts still carries the legacy `status` column, and the read shim
# lets a mapped legacy status override the stored draft_state. Seeding a posted
# row with status='draft' therefore silently produced a DRAFT — the fixture has
# to keep both columns consistent or it tests the wrong document.
_LEGACY_STATUS = {"draft": "draft", "post_failed": "failed", "posted": "issued"}


def _seed(db_path, state, *, box=None, gross=None):
    """A draft in a given fiscal state, with a wFirma identity when posted."""
    posted = state == "posted"
    legacy = _LEGACY_STATUS.get(state, "n/a")   # unmapped -> stored state wins
    with sqlite3.connect(str(db_path)) as conn:
        cur = conn.execute(
            """INSERT INTO proforma_drafts
                 (batch_id, client_name, status, currency, draft_state,
                  wfirma_proforma_id, wfirma_proforma_fullnumber,
                  source_lines_json, editable_lines_json, service_charges_json,
                  clone_generation, draft_version, box_type_code,
                  manual_gross_weight, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'),datetime('now'))""",
            (BATCH, CLIENT, legacy, "EUR", state,
             4242 if posted else None, "PROF 190/2026" if posted else "",
             json.dumps([{"line_id": "L1", "product_code": "EJL/1", "qty": 1.0,
                          "unit_price": 100.0, "currency": "EUR"}]),
             json.dumps([{"line_id": "L1", "product_code": "EJL/1", "qty": 1.0,
                          "unit_price": 100.0, "currency": "EUR"}]),
             "[]", 0, 1, box, gross),
        )
        conn.commit()
        return cur.lastrowid


def _row(db_path, did):
    from app.services import proforma_invoice_link_db as pildb
    return pildb.get_draft_by_id(db_path, did)


def _seed_box_master(tmp_path, code="DHL-JEWEL-S"):
    from app.services import master_data_db as mdb
    mp = tmp_path / "master_data.sqlite"
    mdb.init_db(mp)
    mdb.upsert_box_type(mp, {
        "code": code, "name": "DHL jewellery small", "length_cm": 22.0,
        "width_cm": 15.0, "height_cm": 9.0, "tare_weight_kg": 0.2,
    })
    return mp


# ── the reported defect: posted document refused dispatch facts ─────────────


def test_posted_proforma_accepts_a_box_selection(db):
    """The exact reported 409: box change on a posted proforma."""
    from app.services import proforma_invoice_link_db as pildb

    did = _seed(db, "posted")
    before = _row(db, did)
    out = pildb.set_draft_box_type(
        db, did, box_type_code="DHL-JEWEL-S",
        operator="op", expected_updated_at=before.updated_at,
    )
    assert out.box_type_code == "DHL-JEWEL-S"


def test_posted_proforma_accepts_operator_transport_weights(db):
    from app.services import proforma_invoice_link_db as pildb

    did = _seed(db, "posted")
    before = _row(db, did)
    out = pildb.set_draft_weight_override(
        db, did, manual_net_weight=0.25, manual_gross_weight=0.45,
        manual_tare_weight=0.2, reason="weighed at dispatch",
        source_revision=None, operator="op",
        expected_updated_at=before.updated_at,
    )
    assert out.manual_net_weight == 0.25
    assert out.manual_gross_weight == 0.45
    assert out.manual_tare_weight == 0.2


# ── the fiscal document must survive untouched ──────────────────────────────


@pytest.mark.parametrize("state", ["draft", "editing", "post_failed", "posted"])
def test_transport_metadata_never_moves_the_fiscal_state(db, state):
    """Picking a box must not promote, demote or re-open a document.

    Before the seam, a transport write ran _next_state_after_edit and pushed a
    'draft' to 'editing'. Applied to a posted document that would have been a
    fiscal-lifecycle corruption.
    """
    from app.services import proforma_invoice_link_db as pildb

    did = _seed(db, state)
    out = pildb.set_draft_box_type(
        db, did, box_type_code="DHL-JEWEL-S",
        operator="op", expected_updated_at=_row(db, did).updated_at,
    )
    assert out.draft_state == state


def test_posted_identity_and_commercial_content_are_untouched(db):
    """Transport metadata may not reach price, lines, customer or wFirma identity."""
    from app.services import proforma_invoice_link_db as pildb

    did = _seed(db, "posted")
    before = _row(db, did)
    pildb.set_draft_weight_override(
        db, did, manual_net_weight=None, manual_gross_weight=0.45,
        manual_tare_weight=None, reason="weighed", source_revision=None,
        operator="op", expected_updated_at=before.updated_at,
    )
    after = _row(db, did)
    assert after.wfirma_proforma_id == before.wfirma_proforma_id
    assert after.wfirma_proforma_fullnumber == before.wfirma_proforma_fullnumber
    assert after.client_name == before.client_name
    assert after.currency == before.currency
    assert after.editable_lines_json == before.editable_lines_json
    assert after.draft_state == "posted"


def test_extracted_packing_evidence_is_not_overwritten(db):
    """The manual override is an OVERLAY; historical extraction stays intact."""
    from app.services import proforma_invoice_link_db as pildb

    did = _seed(db, "posted")
    lines_before = _row(db, did).editable_lines_json
    pildb.set_draft_weight_override(
        db, did, manual_net_weight=0.25, manual_gross_weight=0.45,
        manual_tare_weight=None, reason="weighed", source_revision=None,
        operator="op", expected_updated_at=_row(db, did).updated_at,
    )
    assert _row(db, did).editable_lines_json == lines_before


# ── concurrency is NOT relaxed to make the 409 go away ──────────────────────


def test_a_stale_token_still_conflicts_on_a_posted_document(db):
    from app.services import proforma_invoice_link_db as pildb

    did = _seed(db, "posted")
    stale = _row(db, did).updated_at
    pildb.set_draft_box_type(db, did, box_type_code="DHL-JEWEL-S",
                             operator="op", expected_updated_at=stale)
    # Second writer still holding the pre-write token.
    with pytest.raises(pildb.DraftConflict):
        pildb.set_draft_box_type(db, did, box_type_code="DHL-JEWEL-S",
                                 operator="op2", expected_updated_at=stale)


def test_refresh_then_retry_succeeds_once(db):
    """The bounded recovery the modal performs: re-read, retry, done."""
    from app.services import proforma_invoice_link_db as pildb

    did = _seed(db, "posted")
    stale = _row(db, did).updated_at
    pildb.set_draft_weight_override(
        db, did, manual_net_weight=None, manual_gross_weight=0.4,
        manual_tare_weight=None, reason="first", source_revision=None,
        operator="op", expected_updated_at=stale)
    with pytest.raises(pildb.DraftConflict):
        pildb.set_draft_box_type(db, did, box_type_code="DHL-JEWEL-S",
                                 operator="op", expected_updated_at=stale)
    canonical = _row(db, did).updated_at
    out = pildb.set_draft_box_type(db, did, box_type_code="DHL-JEWEL-S",
                                   operator="op", expected_updated_at=canonical)
    assert out.box_type_code == "DHL-JEWEL-S"
    assert out.draft_state == "posted"


# ── the seam stays narrow ───────────────────────────────────────────────────


def test_a_posted_document_still_refuses_ordinary_commercial_edits(db):
    """Widening transport metadata must not widen fiscal editing."""
    from app.services import proforma_invoice_link_db as pildb

    did = _seed(db, "posted")
    with pytest.raises(pildb.DraftNotEditable):
        pildb.update_draft_fields(
            db, did, {"remarks": "should not be possible"},
            operator="op", expected_updated_at=_row(db, did).updated_at,
        )


@pytest.mark.parametrize("state", ["cancelled", "converted"])
def test_terminal_states_still_refuse_transport_metadata(db, state):
    """The seam is an explicit allowlist, not 'everything except editing'."""
    from app.services import proforma_invoice_link_db as pildb

    did = _seed(db, state)
    with pytest.raises(pildb.DraftNotEditable):
        pildb.set_draft_box_type(db, did, box_type_code="DHL-JEWEL-S",
                                 operator="op",
                                 expected_updated_at=_row(db, did).updated_at)


# ── box code persists; Box Master keeps the measurements ────────────────────


def test_the_draft_stores_the_code_and_box_master_keeps_the_dimensions(db, tmp_path):
    from app.services import master_data_db as mdb
    from app.services import proforma_invoice_link_db as pildb

    mp = _seed_box_master(tmp_path)
    did = _seed(db, "posted")
    pildb.set_draft_box_type(db, did, box_type_code="DHL-JEWEL-S",
                             operator="op",
                             expected_updated_at=_row(db, did).updated_at)

    assert _row(db, did).box_type_code == "DHL-JEWEL-S"
    with sqlite3.connect(str(db)) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(proforma_drafts)")}
    assert not {"box_length_cm", "box_width_cm", "box_height_cm"} & cols

    box = mdb.get_box_type_by_code(mp, "DHL-JEWEL-S")
    assert (box.length_cm, box.width_cm, box.height_cm) == (22.0, 15.0, 9.0)


def test_the_persisted_code_round_trips_for_a_reopened_modal(db, tmp_path):
    """What the modal needs on reopen: the code, and dimensions resolvable from it."""
    from app.services import master_data_db as mdb
    from app.services import proforma_invoice_link_db as pildb

    mp = _seed_box_master(tmp_path)
    did = _seed(db, "posted")
    pildb.set_draft_box_type(db, did, box_type_code="DHL-JEWEL-S",
                             operator="op",
                             expected_updated_at=_row(db, did).updated_at)

    code = _row(db, did).box_type_code                 # what reopen reads
    box = mdb.get_box_type_by_code(mp, code)           # what it resolves to
    assert box is not None and box.length_cm > 0
