"""
test_proforma_name_pl_provenance.py — machine_birth provenance campaign.

The defect being pinned: birth stamped ``name_pl_source='operator'`` on ANY
inherited non-blank name, and ``update_draft_line`` — the only human authoring
path — stamped nothing at all. The provenance was therefore *inverted*:

  * machine text inherited through reset  → labelled ``operator`` → frozen
    forever behind ``operator_kept`` in the enrichment helper;
  * a genuine human edit                  → kept whatever stale label it found
    → NOT protected.

The fix gives machine-generated birth/reset text the ``machine_birth``
provenance, makes ``update_draft_line`` the sole minter of ``operator``, and
reclassifies legacy false-``operator`` rows on evidence alone — never on a
draft id, a product code, or a document number.

The nine contract proofs (campaign step 7):
  1. fresh machine birth is stamped ``machine_birth``
  2. reset lets a stronger canonical source replace ``machine_birth``
  3. a UI edit through ``update_draft_line`` mints ``operator``
  4. reset preserves a genuine operator edit (canonical PD does NOT win)
  5. a legacy false-``operator`` row with no human-edit evidence converges
  6. a legacy ``operator`` row a human really submitted is preserved
  7. posted / converted drafts are untouchable
  8. repeated reset is idempotent
  9. birth and reset agree on the canonical description

plus the fail-closed unit contracts of the classifier itself, because the
campaign's HOLD gate is "a genuine operator edit can be overwritten" and the
classifier is the only place that decision is made.

The DB layer is exercised directly with a dict-backed lookup_fn, so no real
document_db / product_descriptions table is required.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from app.services import proforma_invoice_link_db as pildb


# ── fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def db_path(tmp_path) -> Path:
    p = tmp_path / "proforma_links.db"
    pildb.init_db(p)
    return p


# Canonical (product_descriptions) authority, dict-backed. RNG-100 has an
# authority value; UNKNOWN-999 deliberately does not.
_PD_AUTHORITY = {
    "RNG-100": {"name_pl": "Pierścionek złoty", "item_type": "ring",
                "description_pl": "Pierścionek złoty",
                "description_en": "Gold ring with diamonds"},
}


def _lookup(product_code):
    return _PD_AUTHORITY.get(str(product_code or "").strip())


def _line(product_code, *, name_pl="", unit_price=10.0):
    return {
        "product_code": product_code,
        "design_no":    "D1",
        "quantity":     2,
        "unit_price":   unit_price,
        "currency":     "EUR",
        "price_source": "excel_symbol",
        "client_ref":   "REF1",
        "name_pl":      name_pl,
    }


def _editable(draft) -> list:
    return json.loads(draft.editable_lines_json or "[]")


def _first(draft) -> dict:
    return _editable(draft)[0]


def _birth(db_path, *, batch_id, lines, lookup=_lookup):
    draft, _ = pildb.auto_create_draft_from_sales_packing(
        db_path, batch_id=batch_id, client_name="ACME", currency="EUR",
        lines=lines, name_pl_lookup=lookup,
    )
    return draft


def _reset(db_path, draft_id, sales_lines, lookup=_lookup):
    fresh = pildb.get_draft_by_id(db_path, draft_id)
    return pildb.reset_draft_from_sales_packing(
        db_path, draft_id, operator="tester",
        expected_updated_at=fresh.updated_at,
        sales_lines=sales_lines, name_pl_lookup=lookup,
    )


def _line_id(draft) -> int:
    """Birth writes lines without ids; ``update_draft_line`` assigns them
    1-based in array order (``_ensure_line_ids``), so the first line is 1
    whether or not it has been patched before."""
    return int(_first(draft).get("line_id") or 1)


def _edit_name(db_path, draft, new_name, *, operator="anna"):
    """A genuine UI edit — the real ``update_draft_line`` path, which is what
    writes the ``draft_line_edited`` evidence the classifier reads."""
    return pildb.update_draft_line(
        db_path, draft.id, _line_id(draft),
        {"name_pl": new_name}, operator, draft.updated_at,
    )


def _force_legacy_row(db_path, draft_id, *, name_pl, name_pl_source):
    """Materialise a PRE-FIX row shape.

    Legacy rows cannot be produced by the fixed code — that is the whole point
    of the fix — so the only honest way to test convergence is to write the old
    shape directly into the draft's editable_lines_json. This is a TEST fixture
    standing in for existing production data; it is never a repair path, and no
    production code writes rows this way.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT editable_lines_json FROM proforma_drafts WHERE id=?",
            (int(draft_id),),
        ).fetchone()
        lines = json.loads(row[0] or "[]")
        lines[0]["name_pl"] = name_pl
        lines[0]["name_pl_source"] = name_pl_source
        conn.execute(
            "UPDATE proforma_drafts SET editable_lines_json=? WHERE id=?",
            (json.dumps(lines, ensure_ascii=False), int(draft_id)),
        )
        conn.commit()
    finally:
        conn.close()


def _post(db_path, draft):
    """Drive a draft through the real transition chain to ``posted``."""
    d = pildb.approve_draft(
        db_path, draft.id, operator="tester",
        expected_updated_at=draft.updated_at,
        confirm_token=pildb.APPROVE_CONFIRM_TOKEN,
    )
    d = pildb.start_post(
        db_path, d.id, operator="tester",
        expected_updated_at=d.updated_at,
        confirm_token=pildb.POST_CONFIRM_TOKEN,
    )
    return pildb.mark_post_succeeded(
        db_path, d.id, wfirma_proforma_id="99001", operator="tester",
    )


# ── 1. fresh machine birth → machine_birth ───────────────────────────────────

def test_fresh_machine_birth_is_machine_birth(db_path):
    draft = _birth(db_path, batch_id="P1",
                   lines=[_line("UNKNOWN-999", name_pl="Machine Text")])
    ln = _first(draft)
    assert ln["name_pl"] == "Machine Text", "birth blanked a usable name"
    assert ln["name_pl_source"] == pildb.NAME_PL_SOURCE_MACHINE_BIRTH
    assert ln["name_pl_source"] != pildb.NAME_PL_SOURCE_OPERATOR


# ── 2. reset regenerates machine_birth from the stronger canonical source ────

def test_reset_replaces_machine_birth_with_canonical(db_path):
    # Born before the canonical authority knew this code: machine text only.
    draft = _birth(db_path, batch_id="P2",
                   lines=[_line("RNG-100", name_pl="Stale Machine Text")],
                   lookup=lambda _code: None)
    assert _first(draft)["name_pl_source"] == pildb.NAME_PL_SOURCE_MACHINE_BIRTH

    # Reset once the canonical authority CAN answer. Reset feeds the lossy
    # sales shape (no name_pl), so convergence must come from provenance.
    refreshed = _reset(db_path, draft.id, [_line("RNG-100", name_pl="")])
    ln = _first(refreshed)
    assert ln["name_pl"] == "Pierścionek złoty", "stale machine text survived reset"
    assert ln["name_pl_source"] == pildb.NAME_PL_SOURCE_PD


# ── 3. a UI edit mints operator ──────────────────────────────────────────────

def test_ui_edit_mints_operator(db_path):
    draft = _birth(db_path, batch_id="P3",
                   lines=[_line("RNG-100", name_pl="")])
    assert _first(draft)["name_pl_source"] == pildb.NAME_PL_SOURCE_PD

    edited = _edit_name(db_path, draft, "Pierścionek — nazwa handlowa")
    ln = _first(edited)
    assert ln["name_pl"] == "Pierścionek — nazwa handlowa"
    assert ln["name_pl_source"] == pildb.NAME_PL_SOURCE_OPERATOR


def test_ui_edit_to_blank_is_not_operator(db_path):
    draft = _birth(db_path, batch_id="P3b",
                   lines=[_line("RNG-100", name_pl="")])
    edited = _edit_name(db_path, draft, "")
    ln = _first(edited)
    assert ln["name_pl"] == ""
    assert ln["name_pl_source"] == pildb.NAME_PL_SOURCE_BLANK


# ── 4. reset preserves a genuine operator edit ───────────────────────────────

def test_reset_preserves_genuine_operator_edit(db_path):
    # RNG-100 HAS a canonical value, so this also proves the canonical source
    # does not outrank a human.
    draft = _birth(db_path, batch_id="P4", lines=[_line("RNG-100", name_pl="")])
    edited = _edit_name(db_path, draft, "Nazwa ustalona z klientem")
    assert _first(edited)["name_pl_source"] == pildb.NAME_PL_SOURCE_OPERATOR

    refreshed = _reset(db_path, draft.id, [_line("RNG-100", name_pl="")])
    ln = _first(refreshed)
    assert ln["name_pl"] == "Nazwa ustalona z klientem", \
        "reset overwrote a genuine operator edit"
    assert ln["name_pl_source"] == pildb.NAME_PL_SOURCE_OPERATOR


def test_reset_preserves_operator_edit_against_incoming_machine_name(db_path):
    # Same, but the incoming sales line also carries machine text. The human
    # value must still win.
    draft = _birth(db_path, batch_id="P4b", lines=[_line("RNG-100", name_pl="")])
    _edit_name(db_path, draft, "Nazwa ustalona z klientem")

    refreshed = _reset(db_path, draft.id,
                       [_line("RNG-100", name_pl="Incoming Machine Text")])
    ln = _first(refreshed)
    assert ln["name_pl"] == "Nazwa ustalona z klientem"
    assert ln["name_pl_source"] == pildb.NAME_PL_SOURCE_OPERATOR


# ── 5. legacy false-operator converges ───────────────────────────────────────

def test_legacy_false_operator_converges_on_reset(db_path):
    # The production shape: text no human ever submitted, wearing an
    # ``operator`` label minted by the old birth path.
    draft = _birth(db_path, batch_id="P5",
                   lines=[_line("RNG-100", name_pl="")], lookup=lambda _c: None)
    _force_legacy_row(db_path, draft.id,
                      name_pl="Stara nazwa maszynowa",
                      name_pl_source=pildb.NAME_PL_SOURCE_OPERATOR)

    refreshed = _reset(db_path, draft.id, [_line("RNG-100", name_pl="")])
    ln = _first(refreshed)
    assert ln["name_pl"] == "Pierścionek złoty", \
        "a false-operator row stayed frozen"
    assert ln["name_pl_source"] == pildb.NAME_PL_SOURCE_PD


def test_legacy_false_operator_is_never_blanked(db_path):
    # Same false-operator row, but nothing stronger exists. Demotion must
    # never destroy text — only unlock it.
    draft = _birth(db_path, batch_id="P5b",
                   lines=[_line("UNKNOWN-999", name_pl="")])
    _force_legacy_row(db_path, draft.id,
                      name_pl="Stara nazwa maszynowa",
                      name_pl_source=pildb.NAME_PL_SOURCE_OPERATOR)

    refreshed = _reset(db_path, draft.id, [_line("UNKNOWN-999", name_pl="")])
    ln = _first(refreshed)
    assert ln["name_pl"] == "Stara nazwa maszynowa"
    assert ln["name_pl_source"] == pildb.NAME_PL_SOURCE_MACHINE_BIRTH


# ── 6. a real human edit under a legacy label is preserved ───────────────────

def test_legacy_operator_backed_by_human_edit_is_preserved(db_path):
    # The text WAS submitted by a human through update_draft_line, so the
    # append-only event log proves authorship. Even though the canonical
    # authority has a different value, the human value survives.
    draft = _birth(db_path, batch_id="P6", lines=[_line("RNG-100", name_pl="")])
    _edit_name(db_path, draft, "Nazwa wpisana ręcznie")

    refreshed = _reset(db_path, draft.id, [_line("RNG-100", name_pl="")])
    ln = _first(refreshed)
    assert ln["name_pl"] == "Nazwa wpisana ręcznie"
    assert ln["name_pl_source"] == pildb.NAME_PL_SOURCE_OPERATOR

    # …and it survives a SECOND reset — demotion is not merely deferred.
    again = _reset(db_path, draft.id, [_line("RNG-100", name_pl="")])
    assert _first(again)["name_pl"] == "Nazwa wpisana ręcznie"
    assert _first(again)["name_pl_source"] == pildb.NAME_PL_SOURCE_OPERATOR


def test_qty_only_edit_does_not_confer_human_authorship(db_path):
    # An edit that does NOT patch name_pl must not launder the machine text
    # in that line's ``before`` snapshot into human-authored evidence.
    draft = _birth(db_path, batch_id="P6b",
                   lines=[_line("RNG-100", name_pl="")], lookup=lambda _c: None)
    _force_legacy_row(db_path, draft.id,
                      name_pl="Stara nazwa maszynowa",
                      name_pl_source=pildb.NAME_PL_SOURCE_OPERATOR)
    fresh = pildb.get_draft_by_id(db_path, draft.id)
    pildb.update_draft_line(db_path, draft.id, _line_id(fresh),
                            {"qty": 5}, "anna", fresh.updated_at)

    refreshed = _reset(db_path, draft.id, [_line("RNG-100", name_pl="")])
    out = _first(refreshed)
    assert out["name_pl"] == "Pierścionek złoty", \
        "a qty-only edit laundered machine text into operator authority"
    assert out["name_pl_source"] == pildb.NAME_PL_SOURCE_PD


# ── 7. posted / converted drafts are untouchable ─────────────────────────────

def test_posted_draft_cannot_be_reset(db_path):
    draft = _birth(db_path, batch_id="P7", lines=[_line("RNG-100", name_pl="")])
    posted = _post(db_path, draft)
    assert posted.draft_state == "posted"
    before = _editable(posted)

    with pytest.raises(pildb.DraftNotEditable):
        pildb.reset_draft_from_sales_packing(
            db_path, draft.id, operator="tester",
            expected_updated_at=posted.updated_at,
            sales_lines=[_line("RNG-100", name_pl="")], name_pl_lookup=_lookup,
        )

    after = _editable(pildb.get_draft_by_id(db_path, draft.id))
    assert after == before, "a posted document's lines changed"


def test_classifier_never_demotes_a_non_editable_draft():
    # The unit-level half of the same gate: even with zero human evidence, a
    # non-editable draft keeps its stamp.
    got = pildb.classify_legacy_name_pl_source(
        name_pl="Stara nazwa maszynowa",
        name_pl_source=pildb.NAME_PL_SOURCE_OPERATOR,
        draft_is_editable=False,
        human_edited_values=set(),
    )
    assert got == pildb.NAME_PL_SOURCE_OPERATOR


def test_classifier_fails_closed_without_a_verdict():
    # ``None`` means the evidence could not be read. Protect everything.
    got = pildb.classify_legacy_name_pl_source(
        name_pl="Stara nazwa maszynowa",
        name_pl_source=pildb.NAME_PL_SOURCE_OPERATOR,
        draft_is_editable=True,
        human_edited_values=None,
    )
    assert got == pildb.NAME_PL_SOURCE_OPERATOR


def test_classifier_requires_positive_machine_match_when_supplied():
    # With a machine set in hand, a text that is NOT machine output is kept —
    # the corroborating leg can only ever protect, never demote.
    kwargs = dict(
        name_pl="Nazwa wpisana ręcznie",
        name_pl_source=pildb.NAME_PL_SOURCE_OPERATOR,
        draft_is_editable=True,
        human_edited_values=set(),
    )
    assert pildb.classify_legacy_name_pl_source(
        machine_values={"Coś innego"}, **kwargs
    ) == pildb.NAME_PL_SOURCE_OPERATOR
    assert pildb.classify_legacy_name_pl_source(
        machine_values={"Nazwa wpisana ręcznie"}, **kwargs
    ) == pildb.NAME_PL_SOURCE_MACHINE_BIRTH


# ── 8. repeated reset is idempotent ──────────────────────────────────────────

def test_repeated_reset_is_idempotent(db_path):
    draft = _birth(db_path, batch_id="P8",
                   lines=[_line("RNG-100", name_pl="Stale Machine Text")],
                   lookup=lambda _c: None)
    sales = [_line("RNG-100", name_pl="")]
    first = _first(_reset(db_path, draft.id, sales))
    second = _first(_reset(db_path, draft.id, sales))
    third = _first(_reset(db_path, draft.id, sales))
    for got in (first, second, third):
        assert got["name_pl"] == "Pierścionek złoty"
        assert got["name_pl_source"] == pildb.NAME_PL_SOURCE_PD


def test_repeated_reset_is_idempotent_for_operator_rows(db_path):
    draft = _birth(db_path, batch_id="P8b", lines=[_line("RNG-100", name_pl="")])
    _edit_name(db_path, draft, "Nazwa ustalona z klientem")
    sales = [_line("RNG-100", name_pl="")]
    for _ in range(3):
        ln = _first(_reset(db_path, draft.id, sales))
        assert ln["name_pl"] == "Nazwa ustalona z klientem"
        assert ln["name_pl_source"] == pildb.NAME_PL_SOURCE_OPERATOR


# ── 9. birth and reset agree on the canonical description ────────────────────

def test_birth_and_reset_agree_on_canonical_description(db_path):
    sales = [_line("RNG-100", name_pl="Machine Text")]

    born = _first(_birth(db_path, batch_id="P9a", lines=sales))

    stale = _birth(db_path, batch_id="P9b", lines=sales, lookup=lambda _c: None)
    reset = _first(_reset(db_path, stale.id, sales))

    assert born["name_pl"] == reset["name_pl"] == "Pierścionek złoty"
    assert born["name_pl_source"] == reset["name_pl_source"] == \
        pildb.NAME_PL_SOURCE_PD


def test_birth_and_reset_agree_when_no_canonical_authority(db_path):
    sales = [_line("UNKNOWN-999", name_pl="Machine Text")]
    born = _first(_birth(db_path, batch_id="P9c", lines=sales))
    stale = _birth(db_path, batch_id="P9d", lines=sales)
    reset = _first(_reset(db_path, stale.id, sales))

    assert born["name_pl"] == reset["name_pl"] == "Machine Text"
    assert born["name_pl_source"] == reset["name_pl_source"] == \
        pildb.NAME_PL_SOURCE_MACHINE_BIRTH


# ── 10. the evidence itself: fail-closed completeness ────────────────────────
#
# Demotion rests on an argument from silence — "no draft_line_edited event
# names this text, therefore no human wrote it". That argument is only valid
# when the log is demonstrably readable AND spans the draft's whole life.
# These pins prove every other case resolves to ``unknown`` → preserve.

def _events_sql(db_path, sql, params=()):
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


def _legacy_draft(db_path, batch_id, *, product_code="RNG-100"):
    """An editable draft carrying one PRE-FIX false-``operator`` row."""
    draft = _birth(db_path, batch_id=batch_id,
                   lines=[_line(product_code, name_pl="")],
                   lookup=lambda _c: None)
    _force_legacy_row(db_path, draft.id,
                      name_pl="Stara nazwa maszynowa",
                      name_pl_source=pildb.NAME_PL_SOURCE_OPERATOR)
    return draft


def _reset_source(db_path, draft_id, product_code="RNG-100"):
    return _first(_reset(db_path, draft_id, [_line(product_code, name_pl="")]))[
        "name_pl_source"]


def test_healthy_history_is_readable_and_complete(db_path):
    # The positive control: a draft born normally has a birth anchor as its
    # oldest event and nothing has mutated it since.
    draft = _birth(db_path, batch_id="E0", lines=[_line("RNG-100", name_pl="")])
    hist = pildb.read_name_pl_edit_history(db_path, draft.id)
    assert hist.readable is True
    assert hist.complete is True
    assert hist.reason == "complete"


def test_unreadable_history_preserves_operator(db_path):
    # The events table itself is gone — the classifier can prove nothing.
    draft = _legacy_draft(db_path, "E1")
    _events_sql(db_path, "DROP TABLE proforma_draft_events")

    hist = pildb.read_name_pl_edit_history(db_path, draft.id)
    assert (hist.readable, hist.reason) == (False, "events_unreadable")
    assert _reset_source(db_path, draft.id) == pildb.NAME_PL_SOURCE_OPERATOR


def test_malformed_event_detail_preserves_operator(db_path):
    # One unparseable detail_json poisons the whole verdict: we cannot know
    # whether the row we could not read was the human edit.
    draft = _legacy_draft(db_path, "E2")
    _events_sql(
        db_path,
        "INSERT INTO proforma_draft_events "
        "(draft_id, event, detail_json, operator, occurred_at) "
        "VALUES (?, 'draft_line_edited', '{not json', 'anna', '2026-08-04T10:00:00Z')",
        (draft.id,),
    )

    hist = pildb.read_name_pl_edit_history(db_path, draft.id)
    assert (hist.readable, hist.reason) == (False, "event_detail_unparseable")
    assert _reset_source(db_path, draft.id) == pildb.NAME_PL_SOURCE_OPERATOR


def test_event_without_timestamp_preserves_operator(db_path):
    # An untimestamped row cannot be ordered, so neither completeness leg can
    # be evaluated honestly.
    draft = _legacy_draft(db_path, "E3")
    _events_sql(
        db_path,
        "INSERT INTO proforma_draft_events "
        "(draft_id, event, detail_json, operator, occurred_at) "
        "VALUES (?, 'draft_line_edited', '{}', 'anna', '')",
        (draft.id,),
    )

    hist = pildb.read_name_pl_edit_history(db_path, draft.id)
    assert (hist.readable, hist.reason) == (False, "event_without_timestamp")
    assert _reset_source(db_path, draft.id) == pildb.NAME_PL_SOURCE_OPERATOR


def test_history_not_reaching_birth_preserves_operator(db_path):
    # The log is readable but its oldest row is not a birth anchor: something
    # was trimmed off the front, so an absent edit may simply be an absent row.
    draft = _legacy_draft(db_path, "E4")
    fresh = pildb.get_draft_by_id(db_path, draft.id)
    pildb.update_draft_line(db_path, draft.id, _line_id(fresh),
                            {"qty": 5}, "anna", fresh.updated_at)
    _events_sql(
        db_path,
        "DELETE FROM proforma_draft_events "
        "WHERE draft_id = ? AND event = 'created_from_sales_packing'",
        (draft.id,),
    )

    hist = pildb.read_name_pl_edit_history(db_path, draft.id)
    assert hist.readable is True
    assert (hist.complete, hist.reason) == (False, "log_does_not_reach_birth")
    assert _reset_source(db_path, draft.id) == pildb.NAME_PL_SOURCE_OPERATOR


def test_mutation_after_last_event_preserves_operator(db_path):
    # The draft changed more recently than anything the log recorded — the
    # signature of a write that bypassed the canonical edit path entirely.
    # This is the one leg that speaks to the residual risk the event model
    # cannot otherwise see, and it resolves toward preservation.
    draft = _legacy_draft(db_path, "E5")
    _events_sql(
        db_path,
        "UPDATE proforma_drafts SET updated_at='2099-01-01T00:00:00Z' WHERE id=?",
        (draft.id,),
    )

    hist = pildb.read_name_pl_edit_history(db_path, draft.id)
    assert hist.readable is True
    assert (hist.complete, hist.reason) == (False, "mutation_after_last_event")
    assert _reset_source(db_path, draft.id) == pildb.NAME_PL_SOURCE_OPERATOR


def test_missing_draft_is_not_readable(db_path):
    hist = pildb.read_name_pl_edit_history(db_path, 999999)
    assert (hist.readable, hist.complete, hist.reason) == \
        (False, False, "draft_not_found")


def test_verdict_truth_table(db_path):
    # Every branch of the three-state verdict, stated as a table so a reviewer
    # can see at a glance that only ONE row yields confirmed_machine.
    complete   = pildb.NamePlEditHistory(True, True, "complete")
    human      = pildb.NamePlEditHistory(True, True, "complete",
                                         frozenset({"Tekst człowieka"}))
    incomplete = pildb.NamePlEditHistory(True, False, "log_does_not_reach_birth")
    unreadable = pildb.NamePlEditHistory(False, False, "events_unreadable")

    M = pildb.LEGACY_NAME_PL_CONFIRMED_MACHINE
    H = pildb.LEGACY_NAME_PL_CONFIRMED_HUMAN
    U = pildb.LEGACY_NAME_PL_UNKNOWN

    cases = [
        # (name, source, editable, history, machine_values, expected verdict)
        ("Tekst",          pildb.NAME_PL_SOURCE_OPERATOR, True,  complete,   None,             M),
        ("Tekst człowieka", pildb.NAME_PL_SOURCE_OPERATOR, True,  human,      None,             H),
        ("Tekst człowieka", pildb.NAME_PL_SOURCE_OPERATOR, False, human,      None,             U),
        ("Tekst",          pildb.NAME_PL_SOURCE_OPERATOR, False, complete,   None,             U),
        ("Tekst",          pildb.NAME_PL_SOURCE_OPERATOR, True,  incomplete, None,             U),
        ("Tekst",          pildb.NAME_PL_SOURCE_OPERATOR, True,  unreadable, None,             U),
        ("",               pildb.NAME_PL_SOURCE_OPERATOR, True,  complete,   None,             U),
        ("Tekst",          pildb.NAME_PL_SOURCE_PD,       True,  complete,   None,             U),
        ("Tekst",          pildb.NAME_PL_SOURCE_MACHINE_BIRTH, True, complete, None,           U),
        ("Tekst",          pildb.NAME_PL_SOURCE_OPERATOR, True,  complete,   {"Tekst"},        M),
        ("Tekst",          pildb.NAME_PL_SOURCE_OPERATOR, True,  complete,   {"Coś innego"},   U),
        # A human edit outranks even a machine set that also contains the text.
        ("Tekst człowieka", pildb.NAME_PL_SOURCE_OPERATOR, True, human, {"Tekst człowieka"},   H),
    ]
    for name, source, editable, hist, machine, want in cases:
        got, reason = pildb.classify_legacy_name_pl_verdict(
            name_pl=name, name_pl_source=source, draft_is_editable=editable,
            history=hist, machine_values=machine,
        )
        assert got == want, f"{name!r}/{source}/{editable}/{hist.reason} -> {got} ({reason})"
        # The mapper must demote on exactly the confirmed_machine rows.
        mapped = pildb.classify_legacy_name_pl_source(
            name_pl=name, name_pl_source=source, draft_is_editable=editable,
            history=hist, machine_values=machine,
        )
        assert mapped == (pildb.NAME_PL_SOURCE_MACHINE_BIRTH if want == M
                          else source)


def test_zero_line_edit_events_alone_never_demotes(db_path):
    # The exact sentence from the governance rule: "zero matching events" is
    # not machine ownership. Same empty human set, two histories — only the
    # demonstrably complete one may demote.
    args = dict(name_pl="Stara nazwa maszynowa",
                name_pl_source=pildb.NAME_PL_SOURCE_OPERATOR,
                draft_is_editable=True)
    assert pildb.classify_legacy_name_pl_source(
        history=pildb.NamePlEditHistory(True, False, "no_event_history"), **args,
    ) == pildb.NAME_PL_SOURCE_OPERATOR
    assert pildb.classify_legacy_name_pl_source(
        history=pildb.NamePlEditHistory(True, True, "complete"), **args,
    ) == pildb.NAME_PL_SOURCE_MACHINE_BIRTH


# ── 11. enrichment and byte-identical reset ──────────────────────────────────

def test_enrichment_never_overwrites_a_human_edit(db_path):
    # The third writer of name_pl. A human edit must survive it untouched even
    # though the canonical authority holds a different value.
    draft = _birth(db_path, batch_id="E6", lines=[_line("RNG-100", name_pl="")])
    edited = _edit_name(db_path, draft, "Nazwa ustalona z klientem")

    out, _hit, _miss = pildb.enrich_lines_from_product_descriptions(
        _editable(edited), _lookup)
    assert out[0]["name_pl"] == "Nazwa ustalona z klientem"
    assert out[0]["name_pl_source"] == pildb.NAME_PL_SOURCE_OPERATOR


def test_enrichment_replaces_machine_birth(db_path):
    # …and the same call DOES correct machine-born text: that asymmetry is the
    # whole point of separating the two provenances.
    draft = _birth(db_path, batch_id="E7",
                   lines=[_line("RNG-100", name_pl="Stale Machine Text")],
                   lookup=lambda _c: None)
    assert _first(draft)["name_pl_source"] == pildb.NAME_PL_SOURCE_MACHINE_BIRTH

    out, _hit, _miss = pildb.enrich_lines_from_product_descriptions(
        _editable(draft), _lookup)
    assert out[0]["name_pl"] == "Pierścionek złoty"
    assert out[0]["name_pl_source"] == pildb.NAME_PL_SOURCE_PD


def test_second_reset_is_byte_identical(db_path):
    # Stronger than field-wise idempotency: the serialised line array must not
    # move at all, so a converged draft cannot drift under repeated resets.
    draft = _birth(db_path, batch_id="E8",
                   lines=[_line("RNG-100", name_pl="Stale Machine Text")],
                   lookup=lambda _c: None)
    sales = [_line("RNG-100", name_pl="")]
    _reset(db_path, draft.id, sales)
    second = _reset(db_path, draft.id, sales)
    third  = _reset(db_path, draft.id, sales)
    assert json.dumps(_editable(third),  sort_keys=True) == \
           json.dumps(_editable(second), sort_keys=True)
