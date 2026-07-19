"""
test_dashboard_pz_generated_date.py — PZ Generated date on the Shipments page.

Pins the canonical PZ-generation date authority end to end:

    export_service._build_pz_output()  →  audit.pz_output.generated_at
        →  _batch_summary()["pz_generated_at"]
        →  GET /api/v1/dashboard/batches
        →  DashboardPage "PZ Generated" column

Backend (unit, real helpers — no stubs of the functions under test):
  1.  Completed PZ batch returns the canonical pz_generated_at
  2.  Missing PZ-generation evidence returns None
  3.  Top-level `timestamp` is NOT misrepresented as the PZ-generation date
  4.  Re-run returns the latest successful generation timestamp
  5.  Deduplicated row and its date belong to the same retained run
  6.  Endpoint order is newest canonical PZ generation first
  7.  Rows with no date sort last
  8.  Pre-existing summary fields and the read-only contract are intact

Frontend (source-grep):
  9.  The column exists and consumes pz_generated_at
 10.  The date is not derived from timestamp / directory metadata / status text
      / the browser clock
 11.  Date sorting uses datetime semantics, not lexicographic display strings
 12.  The no-write-action contract still holds

Authority notes:
  - `pz_output` is absent from audit_merge.PRESERVED_KEYS, so each engine
    re-run overwrites `generated_at`. Test 4 pins that dependency.
  - The stored string is passed through verbatim (operator ruling 2026-07-19);
    the API must not re-zone or reformat it. Test 1 pins the exact string.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

_SVC = Path(__file__).resolve().parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

os.environ.setdefault("API_KEY", "test-key")

from app.api import routes_dashboard as rd  # noqa: E402

_V2        = _SVC / "app" / "static" / "v2"
_DASH_PAGE = _V2 / "dashboard-page.jsx"


def _audit(batch_id="SHIPMENT_1234567890_2026-05_abc", generated_at=None, **extra):
    """Minimal audit dict. `generated_at=None` means the engine never ran."""
    a = {
        "batch_id":  batch_id,
        "status":    "success",
        "doc_no":    "PZ/001/2026",
        "totals":    {"net": 100.0, "gross": 123.0, "duty": 5.0},
        "inputs":    {},
    }
    if generated_at is not None:
        a["pz_output"] = {"pdf": "pz.pdf", "xlsx": "pz.xlsx", "generated_at": generated_at}
    a.update(extra)
    return a


# ═══════════════════════════════════════════════════════════════════════════
# 1–4. Canonical field derivation
# ═══════════════════════════════════════════════════════════════════════════

class TestCanonicalField:

    def test_completed_batch_returns_canonical_generated_at(self):
        a = _audit(generated_at="2026-05-08T11:49:28Z")
        assert rd._pz_generated_at(a) == "2026-05-08T11:49:28Z"

    def test_value_is_passed_through_verbatim(self):
        """Operator ruling 2026-07-19: pass through as stored. The API must not
        re-zone, truncate, or reformat the engine's stamp."""
        raw = "2026-05-08T23:59:59Z"
        assert rd._batch_summary(_audit(generated_at=raw), "d")["pz_generated_at"] == raw

    def test_missing_pz_output_returns_none(self):
        assert rd._pz_generated_at(_audit(generated_at=None)) is None

    def test_empty_or_blank_generated_at_returns_none(self):
        assert rd._pz_generated_at({"pz_output": {"generated_at": ""}}) is None
        assert rd._pz_generated_at({"pz_output": {"generated_at": "   "}}) is None
        assert rd._pz_generated_at({"pz_output": {}}) is None
        assert rd._pz_generated_at({}) is None

    def test_non_string_generated_at_is_treated_as_absent(self):
        """A malformed audit.json must not 500 the whole Shipments list —
        this file's status hints follow the same 'never break the list' rule."""
        for bad in (20260508, 3.14, True, [], {}, ["2026-05-08T11:49:28Z"]):
            assert rd._pz_generated_at({"pz_output": {"generated_at": bad}}) is None

    def test_malformed_audit_still_yields_a_usable_summary(self):
        s = rd._batch_summary(_audit(generated_at=None, pz_output={"generated_at": 123}), "d")
        assert s["pz_generated_at"] is None
        assert s["net"] == 100.0

    def test_timestamp_is_not_used_as_pz_generation_date(self):
        """`timestamp` is overloaded — routes_intake writes it at DRAFT creation.
        A batch with a timestamp but no PZ output must report no date."""
        a = _audit(generated_at=None, timestamp="2026-01-01T09:00:00", status="ready")
        summary = rd._batch_summary(a, "d")
        assert summary["pz_generated_at"] is None
        assert summary["timestamp"] == "2026-01-01T09:00:00"

    def test_timestamp_and_generated_at_are_independent_fields(self):
        a = _audit(generated_at="2026-05-08T11:49:28Z", timestamp="2026-01-01T09:00:00")
        s = rd._batch_summary(a, "d")
        assert s["pz_generated_at"] == "2026-05-08T11:49:28Z"
        assert s["timestamp"] == "2026-01-01T09:00:00"
        assert s["pz_generated_at"] != s["timestamp"]

    def test_rerun_reports_latest_generation(self):
        """`pz_output` is not in audit_merge.PRESERVED_KEYS, so a re-run
        overwrites generated_at. The projection must report the newer value."""
        from app.services.audit_merge import PRESERVED_KEYS
        assert "pz_output" not in PRESERVED_KEYS, \
            "pz_output became a preserved key — re-runs would freeze the PZ date"

        first  = _audit(generated_at="2026-05-08T11:49:28Z")
        second = _audit(generated_at="2026-06-02T08:15:00Z")
        assert rd._pz_generated_at(second) == "2026-06-02T08:15:00Z"
        assert rd._pz_generated_at(second) != rd._pz_generated_at(first)


# ═══════════════════════════════════════════════════════════════════════════
# 5–7. Ordering
# ═══════════════════════════════════════════════════════════════════════════

class TestOrdering:

    def test_newest_generation_first(self):
        rows = [
            {"batch_id": "old", "pz_generated_at": "2026-01-05T10:00:00Z"},
            {"batch_id": "new", "pz_generated_at": "2026-06-05T10:00:00Z"},
            {"batch_id": "mid", "pz_generated_at": "2026-03-05T10:00:00Z"},
        ]
        assert [r["batch_id"] for r in rd._order_by_pz_generated_desc(rows)] \
            == ["new", "mid", "old"]

    def test_missing_dates_sort_last(self):
        rows = [
            {"batch_id": "none1", "pz_generated_at": None},
            {"batch_id": "dated", "pz_generated_at": "2026-01-05T10:00:00Z"},
            {"batch_id": "none2", "pz_generated_at": None},
        ]
        out = [r["batch_id"] for r in rd._order_by_pz_generated_desc(rows)]
        assert out[0] == "dated"
        assert set(out[1:]) == {"none1", "none2"}

    def test_unparseable_date_sorts_last_and_does_not_raise(self):
        rows = [
            {"batch_id": "junk",  "pz_generated_at": "not-a-date"},
            {"batch_id": "dated", "pz_generated_at": "2026-01-05T10:00:00Z"},
        ]
        assert [r["batch_id"] for r in rd._order_by_pz_generated_desc(rows)] \
            == ["dated", "junk"]

    def test_ordering_is_chronological_not_lexicographic(self):
        """Offset-bearing stamps must order by instant. Lexicographically
        '2026-01-05T23:00:00+02:00' > '2026-01-05T22:30:00Z', but the former is
        the EARLIER instant (21:00Z)."""
        rows = [
            {"batch_id": "earlier_instant", "pz_generated_at": "2026-01-05T23:00:00+02:00"},
            {"batch_id": "later_instant",   "pz_generated_at": "2026-01-05T22:30:00Z"},
        ]
        assert [r["batch_id"] for r in rd._order_by_pz_generated_desc(rows)] \
            == ["later_instant", "earlier_instant"]

    def test_naive_and_aware_values_compare_without_raising(self):
        """Mixed legacy shapes must not raise offset-naive/aware TypeError."""
        rows = [
            {"batch_id": "naive", "pz_generated_at": "2026-01-05T10:00:00"},
            {"batch_id": "aware", "pz_generated_at": "2026-02-05T10:00:00Z"},
        ]
        assert [r["batch_id"] for r in rd._order_by_pz_generated_desc(rows)] \
            == ["aware", "naive"]


class TestEndpointOrdering:
    """Integration over the real list_batches() against a temp storage root."""

    @staticmethod
    def _write(outputs: Path, name: str, audit: dict):
        d = outputs / name
        d.mkdir(parents=True)
        (d / "audit.json").write_text(json.dumps(audit), encoding="utf-8")

    @pytest.fixture
    def outputs(self, tmp_path, monkeypatch):
        out = tmp_path / "outputs"
        out.mkdir()
        monkeypatch.setattr(rd, "_OUTPUTS", out)
        return out

    def test_endpoint_returns_newest_pz_generation_first(self, outputs):
        self._write(outputs, "b_old", _audit(
            batch_id="b_old", generated_at="2026-01-05T10:00:00Z", doc_no="PZ/1/2026"))
        self._write(outputs, "b_new", _audit(
            batch_id="b_new", generated_at="2026-06-05T10:00:00Z", doc_no="PZ/2/2026"))
        self._write(outputs, "b_mid", _audit(
            batch_id="b_mid", generated_at="2026-03-05T10:00:00Z", doc_no="PZ/3/2026"))

        got = [r["batch_id"] for r in rd.list_batches(all_runs=False)]
        assert got == ["b_new", "b_mid", "b_old"]

    def test_endpoint_places_undated_batches_last(self, outputs):
        self._write(outputs, "b_draft", _audit(
            batch_id="b_draft", generated_at=None, doc_no="PZ/9/2026",
            timestamp="2099-01-01T00:00:00", status="ready"))
        self._write(outputs, "b_done", _audit(
            batch_id="b_done", generated_at="2026-01-05T10:00:00Z", doc_no="PZ/8/2026"))

        got = [r["batch_id"] for r in rd.list_batches(all_runs=False)]
        assert got == ["b_done", "b_draft"], \
            "a draft with a far-future creation timestamp must not lead the list"

    def test_deduplicated_row_and_its_date_describe_the_same_run(self, outputs):
        """Two runs of the same (mrn, doc_no). Whichever row survives dedup must
        carry ITS OWN generated_at — never the other run's."""
        self._write(outputs, "run_a", _audit(
            batch_id="run_a", generated_at="2026-05-01T10:00:00Z",
            doc_no="PZ/7/2026", mrn="MRN123", status="blocked"))
        self._write(outputs, "run_b", _audit(
            batch_id="run_b", generated_at="2026-05-09T16:30:00Z",
            doc_no="PZ/7/2026", mrn="MRN123", status="success"))

        rows = rd.list_batches(all_runs=False)
        assert len(rows) == 1, "same (mrn, doc_no) must collapse to one row"
        row = rows[0]
        assert row["run_count"] == 2
        # The success run is preferred over the blocked one; its date must follow it.
        assert row["batch_id"] == "run_b"
        assert row["pz_generated_at"] == "2026-05-09T16:30:00Z"

    def test_all_runs_view_still_exposes_the_field(self, outputs):
        self._write(outputs, "b1", _audit(batch_id="b1", generated_at="2026-01-05T10:00:00Z"))
        rows = rd.list_batches(all_runs=True)
        assert rows and rows[0]["pz_generated_at"] == "2026-01-05T10:00:00Z"


# ═══════════════════════════════════════════════════════════════════════════
# 8. Existing projection contract intact
# ═══════════════════════════════════════════════════════════════════════════

class TestExistingFieldsIntact:

    def test_pre_existing_summary_fields_unchanged(self):
        s = rd._batch_summary(_audit(generated_at="2026-05-08T11:49:28Z"), "d")
        for field in ("batch_id", "tracking_no", "doc_no", "timestamp", "status",
                      "net", "gross", "duty", "mrn", "sad_status", "pz_status",
                      "carrier", "tracking_url", "tracking_label", "run_count"):
            assert field in s, f"pre-existing field {field} disappeared"

    def test_monetary_values_unchanged(self):
        s = rd._batch_summary(_audit(generated_at="2026-05-08T11:49:28Z"), "d")
        assert (s["net"], s["gross"], s["duty"]) == (100.0, 123.0, 5.0)

    def test_field_addition_is_purely_additive(self):
        """The new key is the ONLY difference between a batch with and without
        PZ-generation evidence, given identical input otherwise."""
        with_pz    = rd._batch_summary(_audit(generated_at="2026-05-08T11:49:28Z"), "d")
        without_pz = rd._batch_summary(_audit(generated_at=None), "d")
        assert set(with_pz) == set(without_pz)
        differing = {k for k in with_pz if with_pz[k] != without_pz[k]}
        assert differing == {"pz_generated_at"}, f"unexpected drift: {differing}"


# ═══════════════════════════════════════════════════════════════════════════
# 9–12. Frontend contract
# ═══════════════════════════════════════════════════════════════════════════

def _src() -> str:
    return _DASH_PAGE.read_text(encoding="utf-8")


def _code_only(src: str) -> str:
    """Strip `//` comments so prose never satisfies or trips a token scan."""
    return "\n".join(
        line for line in src.splitlines()
        if not line.lstrip().startswith("//")
    )


class TestFrontendColumn:

    def test_column_header_present(self):
        assert "PZ Generated" in _src()

    def test_header_is_sortable_on_the_canonical_field(self):
        assert '<TH col="pz_generated_at">PZ Generated</TH>' in _code_only(_src())

    def test_column_sits_immediately_after_pz_status(self):
        code = _code_only(_src())
        assert code.index('<TH col="pz_status">') < code.index('<TH col="pz_generated_at">')
        assert code.index('<TH col="pz_generated_at">') < code.index('<TH col="net">')

    def test_cell_renders_the_canonical_field(self):
        assert "_pzDate(row.pz_generated_at)" in _code_only(_src())

    def test_formatter_renders_ddmmyyyy(self):
        code = _code_only(_src())
        assert "${m[3]}.${m[2]}.${m[1]}" in code

    def test_formatter_falls_back_to_em_dash(self):
        assert "return '—'" in _code_only(_src())

    def test_default_sort_is_newest_pz_generation_first(self):
        code = _code_only(_src())
        assert "React.useState('pz_generated_at')" in code
        assert "React.useState('desc')" in code


class TestFrontendDoesNotInventDates:

    def test_no_browser_clock_used_for_the_date(self):
        code = _code_only(_src())
        assert "new Date()" not in code, "browser clock must never fill a missing date"
        assert "Date.now()" not in code

    def test_date_not_derived_from_timestamp_or_status_text(self):
        code = _code_only(_src())
        assert "row.timestamp" not in code
        assert "_pzDate(row.timestamp)" not in code
        assert "_pzDate(row.status" not in code

    def test_no_directory_or_filesystem_metadata_consumed(self):
        code = _code_only(_src())
        for token in ("mtime", "st_mtime", "modified_at", "dir_mtime"):
            assert token not in code

    def test_display_does_not_expose_raw_iso_text(self):
        """The cell must go through the formatter, not print the field raw."""
        code = _code_only(_src())
        assert "{row.pz_generated_at}" not in code
        assert "{_fmt(row.pz_generated_at)}" not in code


class TestFrontendSortSemantics:

    def test_date_column_sorts_on_parsed_timestamps(self):
        code = _code_only(_src())
        assert "_pzDateValue" in code
        assert "Date.parse" in code

    def test_date_column_does_not_use_localecompare(self):
        """localeCompare must remain reachable only for non-date columns."""
        code = _code_only(_src())
        assert "isDateCol" in code
        assert "isDateCol" in code[:code.index("localeCompare")], \
            "the date branch must guard the string comparison"

    def test_missing_values_resolve_before_direction_flip(self):
        """Null-last must hold in BOTH directions — the null checks must come
        before the `sortDir === 'asc'` flip."""
        code = _code_only(_src())
        null_check = code.index("if (av === null")
        dir_flip   = code.index("sortDir === 'asc' ? r : -r")
        assert null_check < dir_flip


class TestReadOnlyContractIntact:

    def test_no_write_http_methods(self):
        code = _code_only(_src())
        for verb in ("method: 'POST'", "method: 'PUT'", "method: 'DELETE'",
                     "method: 'PATCH'"):
            assert verb not in code

    def test_still_consumes_only_the_batches_endpoint(self):
        code = _code_only(_src())
        assert "const SHIPMENTS_ENDPOINT = '/api/v1/dashboard/batches'" in code
        assert code.count("apiFetch(") == 1

    def test_read_only_disclaimer_retained(self):
        assert "Observer only." in _src()

    def test_no_action_affordances_added(self):
        code = _code_only(_src())
        for forbidden in ("Reprocess", "Regenerate", "Recheck", "Archive",
                          "Delete", "Resend", "Edit Draft"):
            assert forbidden not in code
