"""Permanent workflow rule — every wFirma PZ ships with compact audit
notes in its <description> field (2026-05-22).

Codifies the rule first surfaced by the Global AWB 4789974092 incident.
The implementation lives in PR #277 (`wfirma_pz_notes.py` +
`build_pz_request_from_batch(description_override=...)` + three call
sites in `routes_wfirma.py`). PR #278 added goods-authority hardening.

This file adds **architectural regression tests** that fail loudly when
a future change attempts to bypass the helper. They are pure source-
grep and behavioural tests — no live wFirma calls, no audit mutation.

If any test here fails, the rule has been broken:
- a new PZ-create code path forgot the helper, OR
- the helper signature changed, OR
- the wFirma XML field changed, OR
- a hardcoded description string was reintroduced.

NEVER mutate existing wFirma PZ documents from any test in this file.
"""
from __future__ import annotations

import re
from pathlib import Path

from service.app.services.import_pz_builder import (
    BatchRow,
    build_pz_request_from_batch,
)
from service.app.services.wfirma_pz_notes import (
    MAX_NOTE_LEN,
    build_wfirma_pz_notes,
)


ROUTES = (
    Path(__file__).resolve().parent.parent
    / "app" / "api" / "routes_wfirma.py"
)
WFIRMA_CLIENT = (
    Path(__file__).resolve().parent.parent
    / "app" / "services" / "wfirma_client.py"
)
IMPORT_PZ_BUILDER = (
    Path(__file__).resolve().parent.parent
    / "app" / "services" / "import_pz_builder.py"
)


def _routes() -> str:
    return ROUTES.read_text(encoding="utf-8")


def _wfirma_client() -> str:
    return WFIRMA_CLIENT.read_text(encoding="utf-8")


def _import_pz_builder() -> str:
    return IMPORT_PZ_BUILDER.read_text(encoding="utf-8")


# ── 1. Every create_warehouse_pz call shares its function with the helper ──

def test_every_create_warehouse_pz_call_in_routes_uses_compact_notes():
    """Architectural pin: in `routes_wfirma.py`, every function that
    calls `wfirma_client.create_warehouse_pz(...)` MUST also contain
    a `description_override = build_wfirma_pz_notes(...)` (or a
    helper-local variable assigned from `build_wfirma_pz_notes`)
    inside the same function body.

    If a future PR adds a fourth PZ-create code path, this test
    flags it — that path must be wired to the helper or the rule
    is broken.
    """
    body = _routes()
    # Find every function definition + its body span.
    func_starts = [
        (m.start(), m.group(1))
        for m in re.finditer(
            r"^\s*async\s+def\s+(\w+)\s*\(|^\s*def\s+(\w+)\s*\(",
            body, re.MULTILINE,
        )
    ]
    # Append a synthetic end-of-file marker so the last function
    # gets a span.
    func_starts.append((len(body), "<eof>"))
    # Walk function boundaries: each function's body is from its
    # `def` line up to the next function's `def`.
    create_call_pattern = re.compile(r"wfirma_client\.create_warehouse_pz\s*\(")
    helper_pattern = re.compile(
        r"description_override\s*=\s*build_wfirma_pz_notes\s*\(",
    )
    helper_var_pattern = re.compile(
        r"pz_notes\s*=\s*build_wfirma_pz_notes\s*\(",
    )
    for i in range(len(func_starts) - 1):
        span_start, _ = func_starts[i]
        span_end, _ = func_starts[i + 1]
        chunk = body[span_start:span_end]
        if create_call_pattern.search(chunk):
            assert helper_pattern.search(chunk) or helper_var_pattern.search(chunk), (
                f"create_warehouse_pz called in function starting at byte "
                f"{span_start} (~line {body[:span_start].count(chr(10))+1}) "
                f"WITHOUT description_override = build_wfirma_pz_notes — "
                f"compact-notes rule violated"
            )


# ── 2. build_pz_request_from_batch honors non-empty override ─────────

def _row():
    return BatchRow(
        product_code="X-1", quantity=1.0, unit_netto_pln=100.0,
        invoice_no="INV-1", description_en="t", pl_desc="t PL",
        item_type="RING",
    )


def test_builder_honors_non_empty_override():
    r = build_pz_request_from_batch(
        rows=[_row()], contractor_id="ctr", warehouse_id="wh",
        product_map={"X-1": "gid-1"}, batch_id="B", clearance_date="2026-05-22",
        mrn="M", description_override="INV:foo\nAWB:bar",
    )
    assert r.ready
    assert r.pz_request.description == "INV:foo\nAWB:bar"


# ── 3. Empty/whitespace override → legacy fallback ───────────────────

def test_builder_falls_back_to_legacy_on_empty_override():
    r = build_pz_request_from_batch(
        rows=[_row()], contractor_id="ctr", warehouse_id="wh",
        product_map={"X-1": "gid-1"}, batch_id="B", clearance_date="2026-05-22",
        mrn="M", description_override="",
    )
    assert r.pz_request.description == "batch=B | MRN M"


def test_builder_falls_back_to_legacy_on_whitespace_override():
    r = build_pz_request_from_batch(
        rows=[_row()], contractor_id="ctr", warehouse_id="wh",
        product_map={"X-1": "gid-1"}, batch_id="B", clearance_date="2026-05-22",
        mrn="", description_override="   \n  \t  ",
    )
    assert r.pz_request.description == "batch=B"


# ── 4. wFirma XML carries the override verbatim ──────────────────────

def test_wfirma_xml_carries_override_verbatim_with_newlines():
    from service.app.services.wfirma_client import _build_pz_xml, PZRequest, PZLine
    note = "INV:X\nAWB:Y\nMRN:Z"
    xml = _build_pz_xml(PZRequest(
        contractor_id="ctr", warehouse_id="wh", date="2026-05-22",
        description=note,
        lines=[PZLine(good_id="gid", count=1.0, price=10.0)],
    ))
    assert f"<description>{note}</description>" in xml


# ── 5. No hardcoded "batch=" or "INV:" description literal in routes ──

def test_no_hardcoded_description_literal_in_routes():
    """The legacy `f"batch={batch_id}{mrn_part}"` literal must NOT
    appear as a direct `description = ...` assignment inside
    `routes_wfirma.py`. The legacy fallback lives ONLY in
    `import_pz_builder.py` — that single location is the only place
    permitted to compose the legacy string.
    """
    body = _routes()
    # Direct assignment `description = "batch=...` (with possible
    # leading f-prefix). Matches "description = f"batch=..." too.
    bad_assignment = re.compile(
        r'^\s*description\s*=\s*f?"batch=', re.MULTILINE,
    )
    # The preview response builds `description = pz_notes or ...` —
    # that's fine; the helper-or-fallback expression is permitted.
    # We grep specifically for the LITERAL form without `pz_notes or`.
    for m in bad_assignment.finditer(body):
        line_start = body.rfind("\n", 0, m.start()) + 1
        line_end = body.find("\n", m.end())
        line = body[line_start:line_end]
        # Allow only the `description = pz_notes or (... batch= ...)`
        # pattern in the preview response.
        assert "pz_notes" in line, (
            f"hardcoded `description = …batch=…` literal in routes_wfirma.py "
            f"(line ~{body[:m.start()].count(chr(10))+1}): {line!r}"
        )


def test_legacy_fallback_lives_only_in_import_pz_builder():
    body = _import_pz_builder()
    # Exactly one legacy fallback site, gated behind the override check.
    assert 'f"batch={batch_id}{mrn_part}"' in body
    # The override gate must be present right before the fallback.
    assert "if override:" in body or "if description_override" in body
    assert "description = override" in body


# ── 6. Operator's exact-spec output (DHL self-clearance) ─────────────

def test_operator_spec_dhl_self_clearance_exact_match():
    audit = {
        "awb": "4789974092",
        "carrier": "DHL",
        "customs_declaration": {
            "mrn":  "26PL44302D00C2M4R4",
            "lrn":  "26S00SV10S",
            "art33a": True,
            "nbp_table": "096/A/NBP/2026",
            "nbp_rate":  3.6709,
        },
        "verification": {"invoice_exporter_name": "Global Jewellery"},
        "clearance_decision": {"clearance_path": "self_clearance"},
        "_pz_engine_authority_rows": [{"invoice_number": "088/2026-2027"}],
    }
    out = build_wfirma_pz_notes(
        audit, "SHIPMENT_4789974092_2026-05_999deef1"
    )
    expected = (
        "INV:088/2026-2027\n"
        "AWB:4789974092\n"
        "MRN:26PL44302D00C2M4R4\n"
        "SAD:26S00SV10S\n"
        "VAT:Art33a\n"
        "NBP:096/A/NBP/2026 USD=3.6709\n"
        "SUP:Global Jewellery\n"
        "CA:DHL Express PL"
    )
    assert out == expected


# ── 7. Agency clearance produces agency CA ───────────────────────────

def test_agency_clearance_returns_agency_short_name():
    audit = {
        "awb": "4789974092",
        "carrier": "DHL",
        "customs_declaration": {
            "mrn":  "26PL44302D00C2M4R4",
            "lrn":  "26S00SV10S",
            "art33a": True,
            "nbp_table": "096/A/NBP/2026",
            "nbp_rate":  3.6709,
            "customs_agent": "AGENCJA CELNA SPEDYCJA KUŹMICZ K.",
        },
        "verification": {"invoice_exporter_name": "Global Jewellery"},
        "clearance_decision": {
            "clearance_path": "agency_clearance",
            "agency": "Agencja Celna Spedycja",
        },
        "_pz_engine_authority_rows": [{"invoice_number": "088/2026-2027"}],
    }
    out = build_wfirma_pz_notes(audit, "BID")
    assert "CA:Agencja Celna Spedycja" in out
    assert "CA:DHL Express PL" not in out


# ── 8. No forbidden tokens in any output ─────────────────────────────

def test_no_forbidden_tokens_for_partial_audits():
    """Property-style — assemble an audit with random subsets of fields
    missing. The output must NEVER contain UNKNOWN / None / null /
    n/a / undefined / <…> regardless of which fields were absent.
    """
    base_audit = {
        "awb": "1234567890",
        "carrier": "DHL",
        "customs_declaration": {
            "mrn":  "MRN-X",
            "lrn":  "LRN-X",
            "art33a": True,
            "nbp_table": "001/A/NBP/2026",
            "nbp_rate":  3.5,
        },
        "verification": {"invoice_exporter_name": "Sample Supplier"},
        "clearance_decision": {"clearance_path": "self_clearance"},
        "_pz_engine_authority_rows": [{"invoice_number": "INV-X"}],
    }
    forbidden = ("UNKNOWN", "None", "null", "Null", "NULL",
                 "n/a", "N/A", "undefined", "Undefined", "<")
    # Iterate subsets — remove one field at a time
    keys_to_strip = [
        ("awb",),
        ("customs_declaration", "mrn"),
        ("customs_declaration", "lrn"),
        ("customs_declaration", "art33a"),
        ("customs_declaration", "nbp_table"),
        ("customs_declaration", "nbp_rate"),
        ("verification", "invoice_exporter_name"),
        ("clearance_decision", "clearance_path"),
        ("_pz_engine_authority_rows",),
    ]
    for path in keys_to_strip:
        a = {
            k: (dict(v) if isinstance(v, dict) else v)
            for k, v in base_audit.items()
        }
        if len(path) == 1:
            a.pop(path[0], None)
        else:
            a[path[0]].pop(path[1], None)
        out = build_wfirma_pz_notes(a, "SHIPMENT_1234567890_2026-05_x")
        for tok in forbidden:
            assert tok not in out, (
                f"forbidden token {tok!r} appeared in output when "
                f"stripping field {'.'.join(path)}: {out!r}"
            )


# ── 9. Length cap ─────────────────────────────────────────────────────

def test_notes_under_max_note_len_for_any_input():
    huge = {
        "awb": "A" * 200,
        "verification": {"invoice_exporter_name": "B" * 300},
        "customs_declaration": {
            "mrn":  "C" * 200,
            "lrn":  "D" * 200,
            "nbp_table": "E" * 200,
            "nbp_rate":  1.0,
            "customs_agent": "F" * 400,
        },
        "_pz_engine_authority_rows": [{"invoice_number": "G" * 200}],
        "carrier": "DHL",
        "clearance_decision": {"clearance_path": "self_clearance"},
    }
    out = build_wfirma_pz_notes(huge, "BID")
    assert len(out) <= MAX_NOTE_LEN


# ── 10. Existing PZ documents cannot be modified by the notes flow ───

def test_no_pz_document_mutation_path_in_wfirma_client():
    """`wfirma_client.py` MUST NOT expose any function that edits or
    deletes an existing wFirma warehouse document. Notes are a one-way
    construction artifact applied at creation time only. Existing PZ
    documents (e.g. 185704611) can only be corrected by operator-typed
    delete in the wFirma UI followed by `/wfirma/pz/clear-mapping`
    (PR #276) + recreate via `/wfirma/pz_create`.
    """
    client_body = _wfirma_client()
    forbidden_callsigs = [
        r"def\s+edit_warehouse_pz",
        r"def\s+update_warehouse_pz",
        r"def\s+delete_warehouse_pz",
        r"def\s+cancel_warehouse_pz",
        r'"warehouse_documents/edit"',
        r'"warehouse_documents/delete"',
        r'"warehouse_document_p_z",\s*"edit"',
        r'"warehouse_document_p_z",\s*"delete"',
    ]
    for pat in forbidden_callsigs:
        assert re.search(pat, client_body) is None, (
            f"forbidden PZ-mutation callsite present in wfirma_client.py: {pat}"
        )


def test_no_pz_document_mutation_path_in_routes():
    """The same applies to the route handler — there must be no
    endpoint that edits or deletes an issued wFirma PZ document.
    `/wfirma/pz/clear-mapping` only clears the LOCAL audit linkage; it
    never touches wFirma."""
    body = _routes()
    forbidden_routes = [
        r'@router\.[a-z]+\("[^"]*pz[^"]*edit"',
        r'@router\.[a-z]+\("[^"]*pz[^"]*delete"',
        r'@router\.[a-z]+\("[^"]*pz[^"]*update"',
        r'@router\.[a-z]+\("[^"]*pz[^"]*cancel"',
    ]
    for pat in forbidden_routes:
        assert re.search(pat, body) is None, (
            f"forbidden PZ-mutation route present in routes_wfirma.py: {pat}"
        )
    # clear-mapping endpoint is operator-explicit and audit-only; it
    # MUST NOT contain any wfirma_client call inside its handler body.
    chunk_start = body.find("wfirma_pz_clear_mapping")
    if chunk_start > 0:
        end = body.find("@router", chunk_start + 1)
        chunk = body[chunk_start:end] if end > 0 else body[chunk_start:]
        assert "wfirma_client" not in chunk
