"""Reconciliation plan for re-matching already-persisted packing rows.

Pure by construction: no database handle, no HTTP, no filesystem, no clock, and
no mutation of its inputs.  The caller supplies the four views this needs — what
is currently stored, what the current matcher proposes, what the purchase
invoice authorises, and what sales has allocated — and this module answers one
question: *what would change, and is changing it safe?*

Why a separate module rather than logic inside the route: the answer has to be
computable and reviewable **without writing anything**.  An operator has to be
able to read the proposed diff, disagree with it, and walk away having changed
nothing.  Keeping the decision in a pure function is what makes the dry-run and
the apply path provably the same computation rather than two implementations
that drift.

Modelled on ``invoice_line_diagnostics`` (pure, deterministic, structured codes)
and on the preflight/resolve/apply discipline already proven by
``resolve_price_reprocess_targets``.

Authority note (Lesson R): the purchase invoice line is the authority for how
many pieces exist.  A packing row is a consumer of that identity and can never
create availability.  Accordingly a plan whose write would RAISE any invoice
line above the quantity the invoice authorises is refused outright — that is
the machine-checkable form of "a remediation may remove a blocker only by
restoring correct underlying authority, never by increasing availability
synthetically".

Blocker scope (invoice attribution): every blocker carries ``scope_invoices`` —
the invoice numbers the defect is attributable to.  An EMPTY list means the
blocker could not be safely attributed and is GLOBAL: it must veto any write,
scoped or unscoped.  The attribution exists so a caller may apply the plan for
one invoice while an unrelated invoice in the same batch stays blocked — one
blocked invoice must not hold every other invoice in the batch hostage.
Attribution is deliberately conservative: a blocker spanning two invoices names
both, and anything ambiguous names none (= global).  The scoping DECISION lives
in the route; this module only supplies honest attribution.

A line that is already over authority BEFORE the plan, and to which the plan
adds nothing (it only leaves it alone or drains it), is a different case: the
violation is real, but it is not this write's doing.  Refusing the whole batch
for it would let one bad line — typically wrongly operator-confirmed rows,
which only an operator ruling can release — hold every unrelated invoice's
correction hostage while the write changes nothing on that line.  Such lines
are surfaced as ``advisories`` (code ``line_over_authority_preexisting``)
rather than blockers, per Lesson N: a hard gate must name the fiscal risk the
WRITE creates, and a write that never touches the line creates none.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

# Quantities are piece counts — integer-valued in practice, stored REAL only for
# schema flexibility.  The tolerance absorbs decimal→binary representation error
# (~1e-14 at these magnitudes) and is far too small to mask a one-piece
# discrepancy.  Same constant and same reasoning as the over-bill guard in
# product_authority_resolver.
_QTY_EPSILON = 1e-9

# Value is a SOFT signal, never a gate: per-piece prices on a packing list do not
# sum exactly to the invoice line total when a line was billed as an aggregate.
# A residual under this fraction is reported as reconciled; anything above is
# reported as an advisory, and neither ever blocks.
_VALUE_TOLERANCE = 0.02


def _num(v: Any) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _text(v: Any) -> str:
    return str(v or "").strip()


def _row_identity(row: Dict[str, Any]) -> Optional[Tuple[Any, Any]]:
    """The canonical identity of a packing row: (document, source serial).

    This is the same identity ``resolve_price_reprocess_targets`` resolves on,
    and deliberately not the database row id — the proposed rows come from
    re-parsing a file and have no row id at all.  ``pack_sr`` is the serial
    printed on the source packing list, so it survives re-extraction; a row that
    has none cannot be safely paired and is reported rather than guessed at.
    """
    sr = row.get("pack_sr")
    if sr is None:
        sr = row.get("line_position")
    if sr is None:
        return None
    return (row.get("packing_document_id"), sr)


def _assignment(row: Dict[str, Any]) -> Dict[str, Any]:
    """The part of a packing row that this repair can change."""
    return {
        "product_code":           _text(row.get("product_code")) or None,
        "invoice_line_position":  row.get("invoice_line_position"),
        "invoice_no":             _text(row.get("invoice_no")),
        "match_strategy":         _text(row.get("match_strategy")) or None,
        "extracted_confidence":   round(_num(row.get("extracted_confidence")), 4),
        "requires_manual_review": bool(row.get("requires_manual_review")),
    }


def _line_key(invoice_no: Any, position: Any) -> Tuple[str, Any]:
    return (_text(invoice_no), position)


def _scope(*invoice_nos: Any) -> List[str]:
    """Blocker scope from the involved invoice numbers.

    Non-empty values are deduplicated and sorted; if NONE of them is a real
    invoice number the scope is the empty list — the GLOBAL scope, which a
    scoped apply must treat as blocking everything.  Missing information
    therefore fails closed instead of silently narrowing a veto.
    """
    return sorted({_text(v) for v in invoice_nos if _text(v)})


def _tally(rows: List[Dict[str, Any]]) -> Dict[Tuple[str, Any], Dict[str, Any]]:
    """Assigned quantity / value / row count per invoice line."""
    out: Dict[Tuple[str, Any], Dict[str, Any]] = {}
    for r in rows:
        pos = r.get("invoice_line_position")
        if pos is None:
            continue
        e = out.setdefault(
            _line_key(r.get("invoice_no"), pos),
            {"assigned_qty": 0.0, "assigned_value": 0.0, "row_count": 0},
        )
        qty = _num(r.get("quantity"))
        e["assigned_qty"] += qty
        e["assigned_value"] += _num(r.get("total_value")) or qty * _num(r.get("unit_price"))
        e["row_count"] += 1
    return out


def _line_status(assigned_qty: float, authority_qty: float) -> str:
    if assigned_qty > authority_qty + _QTY_EPSILON:
        return "over"
    if assigned_qty < authority_qty - _QTY_EPSILON:
        return "short"
    return "ok"


def _snapshot(tally: Dict[str, Any], authority_qty: float, authority_value: float) -> Dict[str, Any]:
    assigned_qty = round(tally.get("assigned_qty", 0.0), 4)
    assigned_value = round(tally.get("assigned_value", 0.0), 4)
    value_ok = (
        abs(assigned_value - authority_value) <= _VALUE_TOLERANCE * max(abs(authority_value), 1.0)
        if assigned_value or authority_value
        else True
    )
    return {
        "assigned_qty":   assigned_qty,
        "assigned_value": assigned_value,
        "row_count":      int(tally.get("row_count", 0)),
        "qty_status":     _line_status(assigned_qty, authority_qty),
        "value_reconciled": bool(value_ok),
    }


def build_rematch_plan(
    stored_rows:   List[Dict[str, Any]],
    proposed_rows: List[Dict[str, Any]],
    invoice_lines: List[Dict[str, Any]],
    sales_rows:    Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Compute what a re-extraction would change, without changing anything.

    ``stored_rows``   — packing rows as currently persisted (need ``id``,
                        ``packing_document_id``, ``pack_sr``, the assignment
                        fields, ``quantity``, ``unit_price``/``total_value`` and
                        ``operator_review_status``).
    ``proposed_rows`` — the same rows as the current matcher would assign them,
                        produced by re-running the canonical pipeline over the
                        stored source file.  Carries no row id.
    ``invoice_lines`` — the purchase authority: ``invoice_no``,
                        ``line_position``, ``product_code``, ``quantity``,
                        ``total_value``.
    ``sales_rows``    — sales packing rows (``product_code``, ``quantity``), used
                        only to report downstream impact.  Never consulted for a
                        gating decision on the purchase side.

    Returns a plan.  ``blocking`` is True iff the plan must not be applied; the
    caller is required to check it.  A blocking plan is still fully populated so
    the operator can see *why*.  ``advisories`` carries real conditions the
    write is not responsible for and therefore must not be gated on — today the
    one advisory code is ``line_over_authority_preexisting``: a line already
    over authority that this plan does not add to.
    """
    sales_rows = sales_rows or []

    # ── Index the authority ───────────────────────────────────────────────
    authority: Dict[Tuple[str, Any], Dict[str, Any]] = {}
    authority_by_code: Dict[str, float] = {}
    for il in invoice_lines:
        key = _line_key(il.get("invoice_no"), il.get("line_position"))
        qty = _num(il.get("quantity"))
        authority[key] = {
            "invoice_no":      _text(il.get("invoice_no")),
            "line_position":   il.get("line_position"),
            "product_code":    _text(il.get("product_code")) or None,
            "authority_qty":   round(qty, 4),
            "authority_value": round(_num(il.get("total_value")), 4),
        }
        code = _text(il.get("product_code"))
        if code:
            authority_by_code[code] = authority_by_code.get(code, 0.0) + qty

    blockers: List[Dict[str, Any]] = []
    advisories: List[Dict[str, Any]] = []

    # ── Pair stored rows to proposed rows on the canonical identity ───────
    stored_by_id: Dict[Tuple[Any, Any], Dict[str, Any]] = {}
    for r in stored_rows:
        ident = _row_identity(r)
        if ident is None:
            blockers.append({
                "code": "stored_row_without_identity",
                "row_id": r.get("id"),
                "detail": "row has neither pack_sr nor line_position; cannot be paired",
                "scope_invoices": _scope(r.get("invoice_no")),
            })
            continue
        if ident in stored_by_id:
            # Two stored rows on one (document, serial) means the dedup key is
            # already violated.  Rewriting either one would be a guess, so the
            # whole plan refuses rather than picking.
            blockers.append({
                "code": "duplicate_stored_identity",
                "packing_document_id": ident[0], "pack_sr": ident[1],
                "row_ids": [stored_by_id[ident].get("id"), r.get("id")],
                "scope_invoices": _scope(stored_by_id[ident].get("invoice_no"),
                                         r.get("invoice_no")),
            })
            continue
        stored_by_id[ident] = r

    proposed_by_id: Dict[Tuple[Any, Any], Dict[str, Any]] = {}
    for r in proposed_rows:
        ident = _row_identity(r)
        if ident is None:
            blockers.append({
                "code": "proposed_row_without_identity",
                "design_no": _text(r.get("design_no")),
                "detail": "re-parsed row has no serial; cannot be matched to a stored row",
                "scope_invoices": _scope(r.get("invoice_no")),
            })
            continue
        proposed_by_id[ident] = r

    # A stored row the re-parse does not cover would be left holding a stale
    # assignment while its neighbours moved — a half-applied repair is worse than
    # none, so this blocks.
    for ident, r in stored_by_id.items():
        if ident not in proposed_by_id:
            blockers.append({
                "code": "stored_row_not_reparsed",
                "row_id": r.get("id"),
                "packing_document_id": ident[0], "pack_sr": ident[1],
                "scope_invoices": _scope(r.get("invoice_no")),
            })

    # A row that changed invoice is not a placement correction — it is different
    # document membership, and ``invoice_no`` is part of the dedup key the write
    # resolves on.  Rewriting it would either miss the row the plan described or
    # silently move a piece between invoices, so this repair refuses it outright.
    for ident, r in stored_by_id.items():
        p = proposed_by_id.get(ident)
        if p is None:
            continue
        p_inv = _text(p.get("invoice_no"))
        if p_inv and p_inv != _text(r.get("invoice_no")):
            blockers.append({
                "code": "row_changed_invoice",
                "row_id": r.get("id"),
                "packing_document_id": ident[0], "pack_sr": ident[1],
                "stored_invoice_no": _text(r.get("invoice_no")),
                "proposed_invoice_no": p_inv,
                # Both invoices are implicated: selecting EITHER for a scoped
                # apply must keep this veto.
                "scope_invoices": _scope(r.get("invoice_no"), p_inv),
            })

    # A proposed row with no stored counterpart is a new row, which is an upload
    # concern, not a rematch concern.  Report it; do not invent a write for it.
    unresolved_proposed = [
        {"packing_document_id": i[0], "pack_sr": i[1],
         "design_no": _text(proposed_by_id[i].get("design_no"))}
        for i in proposed_by_id if i not in stored_by_id
    ]

    # ── Per-row diff ──────────────────────────────────────────────────────
    row_changes: List[Dict[str, Any]] = []
    unchanged = 0
    operator_confirmed_preserved: List[Dict[str, Any]] = []

    for ident in sorted(stored_by_id, key=lambda k: (str(k[0]), str(k[1]))):
        stored = stored_by_id[ident]
        proposed = proposed_by_id.get(ident)
        if proposed is None:
            continue  # already recorded as a blocker above
        old = _assignment(stored)
        new = _assignment(proposed)
        if old["product_code"] == new["product_code"] and \
           old["invoice_line_position"] == new["invoice_line_position"] and \
           old["match_strategy"] == new["match_strategy"] and \
           abs(old["extracted_confidence"] - new["extracted_confidence"]) < 1e-9:
            unchanged += 1
            continue

        confirmed = _text(stored.get("operator_review_status")).lower() == "confirmed"
        entry = {
            "row_id":              stored.get("id"),
            "packing_document_id": ident[0],
            "pack_sr":             ident[1],
            # The STORED invoice: it is what the write keeps (a proposal that
            # changed invoice is refused, never rewritten), so it is the honest
            # key for scoping which changes belong to which invoice.
            "invoice_no":          _text(stored.get("invoice_no")),
            "design_no":           _text(stored.get("design_no")),
            "quantity":            round(_num(stored.get("quantity")), 4),
            "unit_price":          round(_num(stored.get("unit_price")), 4),
            "operator_review_status": _text(stored.get("operator_review_status")) or None,
            "old": old,
            "new": new,
        }
        if confirmed:
            # An operator-confirmed mapping is a human decision.  The machine may
            # propose a different one and must show it, but must never overwrite
            # it silently — the same guard the force_reextract path already
            # applies at write time, surfaced here so the operator sees it BEFORE
            # approving rather than discovering it afterwards.
            #
            # It is deliberately NOT in row_changes: that list is what the write
            # will actually do, and this row will not move.  Conflating the two
            # would make rows_changed overstate the write and would let the
            # caller hand a preserved row to the writer for no reason.
            entry["preserved"] = True
            operator_confirmed_preserved.append(entry)
            continue
        row_changes.append(entry)

    # ── Per-line reconciliation, before and after ─────────────────────────
    # "After" is computed from the proposed assignment of rows that would
    # actually be written: an operator-confirmed row keeps its stored assignment,
    # so it must be tallied as stored, or the projection would promise a
    # reconciliation the write will not deliver.
    preserved_ids = {e["row_id"] for e in operator_confirmed_preserved}
    effective_after: List[Dict[str, Any]] = []
    for ident, stored in stored_by_id.items():
        proposed = proposed_by_id.get(ident)
        if proposed is None:
            continue
        source = stored if stored.get("id") in preserved_ids else proposed
        effective_after.append({
            "invoice_no":            source.get("invoice_no"),
            "invoice_line_position": source.get("invoice_line_position"),
            "product_code":          source.get("product_code"),
            # Quantity and price are properties of the physical row, not of the
            # assignment, so they always come from the stored row.
            "quantity":              stored.get("quantity"),
            "unit_price":            stored.get("unit_price"),
            "total_value":           stored.get("total_value"),
        })

    before_tally = _tally(list(stored_by_id.values()))
    after_tally = _tally(effective_after)

    line_reconciliation: List[Dict[str, Any]] = []
    for key in sorted(authority, key=lambda k: (k[0], str(k[1]))):
        a = authority[key]
        before = _snapshot(before_tally.get(key, {}), a["authority_qty"], a["authority_value"])
        after = _snapshot(after_tally.get(key, {}), a["authority_qty"], a["authority_value"])
        if after["qty_status"] == "over":
            if after["assigned_qty"] > before["assigned_qty"] + _QTY_EPSILON:
                # The write RAISES this line while it ends over authority — the
                # matcher is wrong and the plan is refused.  This is the
                # machine-checkable form of "never increase availability
                # synthetically", and it covers both creating an over line
                # (before ok) and worsening one (before already over).
                blockers.append({
                    "code": "line_over_authority_after",
                    "invoice_no": a["invoice_no"], "line_position": a["line_position"],
                    "product_code": a["product_code"],
                    "authority_qty": a["authority_qty"],
                    "proposed_qty": after["assigned_qty"],
                    "before_qty": before["assigned_qty"],
                    "scope_invoices": _scope(a["invoice_no"]),
                })
            else:
                # Over before, and the plan adds not one piece to it (equal or
                # drained).  The violation predates this write and only an
                # operator ruling (e.g. un-confirming the rows that pin it) can
                # resolve it — so it must not veto the unrelated corrections in
                # this plan.  Advisory, never a gate (Lesson N).
                advisories.append({
                    "code": "line_over_authority_preexisting",
                    "invoice_no": a["invoice_no"], "line_position": a["line_position"],
                    "product_code": a["product_code"],
                    "authority_qty": a["authority_qty"],
                    "assigned_qty_before": before["assigned_qty"],
                    "assigned_qty_after": after["assigned_qty"],
                })
        line_reconciliation.append({**a, "before": before, "after": after})

    # A line the authority does not know about receiving rows is a defect in the
    # proposal, not a reconciliation result.
    for key in sorted(set(after_tally) - set(authority), key=lambda k: (k[0], str(k[1]))):
        blockers.append({
            "code": "assignment_to_unknown_line",
            "invoice_no": key[0], "line_position": key[1],
            "proposed_qty": round(after_tally[key]["assigned_qty"], 4),
            "scope_invoices": _scope(key[0]),
        })

    # ── Downstream sales impact (advisory — never gates the purchase side) ─
    sales_by_code: Dict[str, float] = {}
    for s in sales_rows:
        code = _text(s.get("product_code"))
        if code:
            sales_by_code[code] = sales_by_code.get(code, 0.0) + _num(s.get("quantity"))

    packing_before_by_code: Dict[str, float] = {}
    packing_after_by_code: Dict[str, float] = {}
    for rows, sink in ((list(stored_by_id.values()), packing_before_by_code),
                       (effective_after, packing_after_by_code)):
        for r in rows:
            code = _text(r.get("product_code"))
            if code:
                sink[code] = sink.get(code, 0.0) + _num(r.get("quantity"))

    sales_impact: List[Dict[str, Any]] = []
    for code in sorted(set(sales_by_code) | (set(packing_after_by_code) ^ set(packing_before_by_code))):
        sales_qty = round(sales_by_code.get(code, 0.0), 4)
        auth_qty = round(authority_by_code.get(code, 0.0), 4)
        before_qty = round(packing_before_by_code.get(code, 0.0), 4)
        after_qty = round(packing_after_by_code.get(code, 0.0), 4)
        if sales_qty <= 0 and before_qty == after_qty:
            continue
        # Availability is bounded by the invoice authority, never by how many
        # packing rows happen to carry the code — that is precisely the
        # circularity this repair exists to remove.
        avail_before = min(before_qty, auth_qty) if auth_qty else before_qty
        avail_after = min(after_qty, auth_qty) if auth_qty else after_qty
        over_before = sales_qty > avail_before + _QTY_EPSILON
        over_after = sales_qty > avail_after + _QTY_EPSILON
        if over_before and not over_after:
            verdict = "over_bill_resolved"
        elif over_after and not over_before:
            # Not a blocker.  A wrong assignment can conceal a real over-bill by
            # crediting pieces that do not exist; correcting it makes the true
            # position visible and the fiscal gate fires as designed.  Hiding
            # that would be the actual failure.
            verdict = "over_bill_revealed"
        elif over_after and over_before:
            verdict = "over_bill_persists"
        else:
            verdict = "ok"
        sales_impact.append({
            "product_code":    code,
            "sales_qty":       sales_qty,
            "authority_qty":   auth_qty,
            "packing_qty_before": before_qty,
            "packing_qty_after":  after_qty,
            "available_before": round(avail_before, 4),
            "available_after":  round(avail_after, 4),
            "over_billed_before": over_before,
            "over_billed_after":  over_after,
            "verdict":         verdict,
        })

    return {
        "row_changes":                  row_changes,
        "unchanged_rows":               unchanged,
        "operator_confirmed_preserved": operator_confirmed_preserved,
        "unresolved_proposed_rows":     unresolved_proposed,
        "line_reconciliation":          line_reconciliation,
        "sales_impact":                 sales_impact,
        "blockers":                     blockers,
        "advisories":                   advisories,
        "blocking":                     bool(blockers),
        "counts": {
            "stored_rows":        len(stored_rows),
            "proposed_rows":      len(proposed_rows),
            "rows_changed":       len(row_changes),
            "rows_unchanged":     unchanged,
            "rows_preserved":     len(operator_confirmed_preserved),
            "lines_over_before":  sum(1 for l in line_reconciliation if l["before"]["qty_status"] == "over"),
            "lines_over_after":   sum(1 for l in line_reconciliation if l["after"]["qty_status"] == "over"),
            "lines_short_before": sum(1 for l in line_reconciliation if l["before"]["qty_status"] == "short"),
            "lines_short_after":  sum(1 for l in line_reconciliation if l["after"]["qty_status"] == "short"),
            "over_bills_resolved": sum(1 for s in sales_impact if s["verdict"] == "over_bill_resolved"),
            "over_bills_revealed": sum(1 for s in sales_impact if s["verdict"] == "over_bill_revealed"),
            "advisories":          len(advisories),
        },
    }
