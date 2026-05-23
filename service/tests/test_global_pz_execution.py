"""
test_global_pz_execution.py
Unit tests for global_pz_execution.py service.

Coverage:
  - No wFirma imports (AST check)
  - KEEP_CURRENT / NO_ACTION: acknowledgement only, no file changes
  - ALIGN_TO_AUTHORITY: product codes renamed to INV-NN format
  - SPLIT_TO_STYLE_LEVEL: pz_rows rebuilt proportionally
  - Idempotency: second call returns existing record
  - Unknown option_id: error result
  - Missing operator_reason: error result
  - Missing pz_rows.json for write options: error result
  - Backup file created for write options
  - rollback_command references backup path
  - correction_execution_record.json written
  - post_line_count reflects actual changes
"""
from __future__ import annotations

import ast
import json
import textwrap
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

# ---------------------------------------------------------------------------
# Locate service file (AST import check)
# ---------------------------------------------------------------------------

_SVC = (
    Path(__file__).resolve().parent.parent
    / "app" / "services" / "global_pz_execution.py"
)

# ---------------------------------------------------------------------------
# AST: no wFirma imports
# ---------------------------------------------------------------------------

def test_no_wfirma_imports():
    """global_pz_execution.py must not import from any wfirma_* module."""
    tree = ast.parse(_SVC.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            module = ""
            if isinstance(node, ast.Import):
                module = " ".join(a.name for a in node.names)
            elif node.module:
                module = node.module
            assert "wfirma" not in module.lower(), (
                f"Forbidden wfirma import found: {module!r}"
            )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_proposed_line(
    pos: int,
    item_type: str,
    packing_qty: float,
    suggested_code: str,
    confidence: float = 0.9,
) -> SimpleNamespace:
    return SimpleNamespace(
        invoice_position_no=pos,
        item_type=item_type,
        packing_qty=packing_qty,
        suggested_product_code=suggested_code,
        allocation_confidence=confidence,
        allocation_reason_codes=["qty_match"],
    )


def _make_pz_rows() -> List[Dict[str, Any]]:
    """Three PZ rows: positions 1, 2, 3."""
    return [
        {
            "line_position": 1,
            "product_code":  "088/2026-2027-N",
            "invoice_no":    "088/2026-2027",
            "quantity":      12.0,
            "unit_netto_pln": 100.0,
            "line_netto_pln": 1200.0,
            "line_brutto_pln": 1320.0,
            "allocated_duty_pln": 60.0,
        },
        {
            "line_position": 2,
            "product_code":  "088/2026-2027-N",
            "invoice_no":    "088/2026-2027",
            "quantity":      8.0,
            "unit_netto_pln": 200.0,
            "line_netto_pln": 1600.0,
            "line_brutto_pln": 1760.0,
            "allocated_duty_pln": 80.0,
        },
        {
            "line_position": 3,
            "product_code":  "088/2026-2027-N",
            "invoice_no":    "088/2026-2027",
            "quantity":      5.0,
            "unit_netto_pln": 150.0,
            "line_netto_pln": 750.0,
            "line_brutto_pln": 825.0,
            "allocated_duty_pln": 37.5,
        },
    ]


@pytest.fixture()
def storage(tmp_path: Path) -> Path:
    """Create a minimal batch storage directory with pz_rows.json."""
    root  = tmp_path / "storage"
    bdir  = root / "outputs" / "BATCH_TEST_001"
    bdir.mkdir(parents=True)
    (bdir / "pz_rows.json").write_text(
        json.dumps(_make_pz_rows(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return root


@pytest.fixture()
def svc():
    from service.app.services import global_pz_execution as _mod  # noqa
    return _mod


BATCH = "BATCH_TEST_001"
REASON = "Unit test operator reason"

# ---------------------------------------------------------------------------
# Gate: validate inputs
# ---------------------------------------------------------------------------

def test_unknown_option_id_returns_error(svc, storage):
    result = svc.execute_correction_option(
        batch_id=BATCH,
        option_id="INVALID_OPTION",
        operator_reason=REASON,
        proposed_lines=[],
        storage_root=storage,
    )
    assert not result.ok
    assert "Unknown option_id" in (result.error or "")


def test_empty_operator_reason_returns_error(svc, storage):
    result = svc.execute_correction_option(
        batch_id=BATCH,
        option_id="KEEP_CURRENT",
        operator_reason="   ",
        proposed_lines=[],
        storage_root=storage,
    )
    assert not result.ok
    assert "operator_reason" in (result.error or "").lower()


def test_missing_batch_dir_returns_error(svc, tmp_path):
    root = tmp_path / "empty_storage"
    root.mkdir()
    result = svc.execute_correction_option(
        batch_id="NONEXISTENT_BATCH",
        option_id="KEEP_CURRENT",
        operator_reason=REASON,
        proposed_lines=[],
        storage_root=root,
    )
    assert not result.ok
    assert "not found" in (result.error or "").lower()


# ---------------------------------------------------------------------------
# KEEP_CURRENT / NO_ACTION — no file changes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("opt_id", ["KEEP_CURRENT", "NO_ACTION"])
def test_keep_current_no_action_does_not_modify_file(svc, storage, opt_id):
    bdir = storage / "outputs" / BATCH
    original = (bdir / "pz_rows.json").read_bytes()

    result = svc.execute_correction_option(
        batch_id=BATCH,
        option_id=opt_id,
        operator_reason=REASON,
        proposed_lines=[],
        storage_root=storage,
    )

    assert result.ok
    assert result.backup_path == "", "KEEP_CURRENT must not create a backup"
    assert (bdir / "pz_rows.json").read_bytes() == original, (
        "pz_rows.json must be unchanged for KEEP_CURRENT / NO_ACTION"
    )


@pytest.mark.parametrize("opt_id", ["KEEP_CURRENT", "NO_ACTION"])
def test_keep_current_writes_audit_record(svc, storage, opt_id):
    bdir = storage / "outputs" / BATCH
    result = svc.execute_correction_option(
        batch_id=BATCH,
        option_id=opt_id,
        operator_reason=REASON,
        proposed_lines=[],
        storage_root=storage,
    )
    assert result.ok
    record_path = bdir / "correction_execution_record.json"
    assert record_path.exists(), "correction_execution_record.json must be written"
    rec = json.loads(record_path.read_text(encoding="utf-8"))
    assert rec["option_id"] == opt_id
    assert rec["operator_reason"] == REASON


# ---------------------------------------------------------------------------
# ALIGN_TO_AUTHORITY
# ---------------------------------------------------------------------------

def test_align_to_authority_renames_product_codes(svc, storage):
    proposed = [
        _make_proposed_line(1, "necklace", 12.0, "INV-01"),
        _make_proposed_line(2, "earrings", 8.0,  "INV-02"),
        _make_proposed_line(3, "bracelet", 5.0,  "INV-03"),
    ]

    result = svc.execute_correction_option(
        batch_id=BATCH,
        option_id="ALIGN_TO_AUTHORITY",
        operator_reason=REASON,
        proposed_lines=proposed,
        storage_root=storage,
    )

    assert result.ok
    bdir = storage / "outputs" / BATCH
    rows = json.loads((bdir / "pz_rows.json").read_text(encoding="utf-8"))
    codes = {r["line_position"]: r["product_code"] for r in rows}
    assert codes[1] == "INV-01"
    assert codes[2] == "INV-02"
    assert codes[3] == "INV-03"


def test_align_to_authority_preserves_original_code(svc, storage):
    proposed = [_make_proposed_line(1, "necklace", 12.0, "INV-01")]

    svc.execute_correction_option(
        batch_id=BATCH,
        option_id="ALIGN_TO_AUTHORITY",
        operator_reason=REASON,
        proposed_lines=proposed,
        storage_root=storage,
    )

    bdir = storage / "outputs" / BATCH
    rows = json.loads((bdir / "pz_rows.json").read_text(encoding="utf-8"))
    row1 = next(r for r in rows if r["line_position"] == 1)
    assert row1["_original_product_code"] == "088/2026-2027-N", (
        "_original_product_code must be saved before rename"
    )


def test_align_to_authority_creates_backup(svc, storage):
    proposed = [_make_proposed_line(1, "necklace", 12.0, "INV-01")]

    result = svc.execute_correction_option(
        batch_id=BATCH,
        option_id="ALIGN_TO_AUTHORITY",
        operator_reason=REASON,
        proposed_lines=proposed,
        storage_root=storage,
    )

    assert result.ok
    assert result.backup_path, "ALIGN_TO_AUTHORITY must create a backup"
    assert Path(result.backup_path).exists(), "Backup file must exist on disk"


def test_align_to_authority_rollback_command_references_backup(svc, storage):
    proposed = [_make_proposed_line(1, "necklace", 12.0, "INV-01")]

    result = svc.execute_correction_option(
        batch_id=BATCH,
        option_id="ALIGN_TO_AUTHORITY",
        operator_reason=REASON,
        proposed_lines=proposed,
        storage_root=storage,
    )

    # rollback_command uses !r quoting (doubles backslashes on Windows) — check the filename
    backup_name = Path(result.backup_path).name
    assert backup_name in result.rollback_command, (
        "rollback_command must reference the backup file name"
    )


def test_align_to_authority_line_count_unchanged(svc, storage):
    proposed = [
        _make_proposed_line(1, "necklace", 12.0, "INV-01"),
        _make_proposed_line(2, "earrings", 8.0,  "INV-02"),
    ]
    result = svc.execute_correction_option(
        batch_id=BATCH,
        option_id="ALIGN_TO_AUTHORITY",
        operator_reason=REASON,
        proposed_lines=proposed,
        storage_root=storage,
    )
    assert result.ok
    assert result.pre_line_count == 3
    assert result.post_line_count == 3, (
        "ALIGN_TO_AUTHORITY must not change the number of rows"
    )


def test_align_to_authority_missing_pz_rows_returns_error(svc, tmp_path):
    root = tmp_path / "storage"
    bdir = root / "outputs" / BATCH
    bdir.mkdir(parents=True)
    # No pz_rows.json

    result = svc.execute_correction_option(
        batch_id=BATCH,
        option_id="ALIGN_TO_AUTHORITY",
        operator_reason=REASON,
        proposed_lines=[_make_proposed_line(1, "x", 1.0, "INV-01")],
        storage_root=root,
    )
    assert not result.ok
    assert "pz_rows" in (result.error or "").lower()


# ---------------------------------------------------------------------------
# SPLIT_TO_STYLE_LEVEL
# ---------------------------------------------------------------------------

def test_split_to_style_level_expands_rows(svc, storage):
    """Position 1 has 1 original row; proposed has 2 item types → 2 rows."""
    proposed = [
        _make_proposed_line(1, "necklace", 7.0,  "INV-01-N"),
        _make_proposed_line(1, "earrings", 5.0,  "INV-01-E"),
        _make_proposed_line(2, "bracelet", 8.0,  "INV-02"),
    ]

    result = svc.execute_correction_option(
        batch_id=BATCH,
        option_id="SPLIT_TO_STYLE_LEVEL",
        operator_reason=REASON,
        proposed_lines=proposed,
        storage_root=storage,
    )

    assert result.ok
    bdir = storage / "outputs" / BATCH
    rows = json.loads((bdir / "pz_rows.json").read_text(encoding="utf-8"))
    # Position 1 → 2 rows, position 2 → 1 row, position 3 → carried unchanged
    pos1_rows = [r for r in rows if r["line_position"] == 1]
    assert len(pos1_rows) == 2, "Position 1 must be split into 2 rows"


def test_split_to_style_level_proportional_value_allocation(svc, storage):
    """Proportional allocation by packing_qty."""
    proposed = [
        _make_proposed_line(1, "necklace", 7.0, "INV-01-N"),
        _make_proposed_line(1, "earrings", 5.0, "INV-01-E"),
    ]

    svc.execute_correction_option(
        batch_id=BATCH,
        option_id="SPLIT_TO_STYLE_LEVEL",
        operator_reason=REASON,
        proposed_lines=proposed,
        storage_root=storage,
    )

    bdir = storage / "outputs" / BATCH
    rows = json.loads((bdir / "pz_rows.json").read_text(encoding="utf-8"))
    pos1_rows = sorted(
        [r for r in rows if r["line_position"] == 1],
        key=lambda r: r["item_type"],
    )
    # earrings: 5/(7+5) = 5/12; necklace: 7/12
    earrings = next(r for r in pos1_rows if r["item_type"] == "earrings")
    necklace = next(r for r in pos1_rows if r["item_type"] == "necklace")
    parent_netto = 1200.0
    assert abs(earrings["line_netto_pln"] - parent_netto * 5/12) < 0.001
    assert abs(necklace["line_netto_pln"] - parent_netto * 7/12) < 0.001


def test_split_to_style_level_total_netto_conserved(svc, storage):
    """Sum of split line_netto must equal parent line_netto (within rounding)."""
    proposed = [
        _make_proposed_line(1, "necklace", 7.0, "INV-01-N"),
        _make_proposed_line(1, "earrings", 5.0, "INV-01-E"),
    ]

    svc.execute_correction_option(
        batch_id=BATCH,
        option_id="SPLIT_TO_STYLE_LEVEL",
        operator_reason=REASON,
        proposed_lines=proposed,
        storage_root=storage,
    )

    bdir = storage / "outputs" / BATCH
    rows = json.loads((bdir / "pz_rows.json").read_text(encoding="utf-8"))
    pos1_total = sum(r["line_netto_pln"] for r in rows if r["line_position"] == 1)
    assert abs(pos1_total - 1200.0) < 0.01, (
        f"Total netto for position 1 must be conserved; got {pos1_total}"
    )


def test_split_to_style_level_creates_backup(svc, storage):
    proposed = [
        _make_proposed_line(1, "necklace", 7.0, "INV-01-N"),
        _make_proposed_line(1, "earrings", 5.0, "INV-01-E"),
    ]

    result = svc.execute_correction_option(
        batch_id=BATCH,
        option_id="SPLIT_TO_STYLE_LEVEL",
        operator_reason=REASON,
        proposed_lines=proposed,
        storage_root=storage,
    )

    assert result.ok
    assert result.backup_path, "SPLIT_TO_STYLE_LEVEL must create a backup"
    assert Path(result.backup_path).exists()


def test_split_carries_unhandled_positions(svc, storage):
    """Rows whose position is not in proposed_lines must be carried unchanged."""
    proposed = [
        _make_proposed_line(1, "necklace", 12.0, "INV-01"),
    ]

    svc.execute_correction_option(
        batch_id=BATCH,
        option_id="SPLIT_TO_STYLE_LEVEL",
        operator_reason=REASON,
        proposed_lines=proposed,
        storage_root=storage,
    )

    bdir = storage / "outputs" / BATCH
    rows = json.loads((bdir / "pz_rows.json").read_text(encoding="utf-8"))
    pos2 = [r for r in rows if r["line_position"] == 2]
    pos3 = [r for r in rows if r["line_position"] == 3]
    assert len(pos2) == 1, "Position 2 must be carried unchanged"
    assert len(pos3) == 1, "Position 3 must be carried unchanged"
    assert pos2[0]["product_code"] == "088/2026-2027-N"


def test_split_records_split_metadata(svc, storage):
    """Each split row must carry _split_from_code and _split_proportion."""
    proposed = [
        _make_proposed_line(1, "necklace", 7.0, "INV-01-N"),
        _make_proposed_line(1, "earrings", 5.0, "INV-01-E"),
    ]

    svc.execute_correction_option(
        batch_id=BATCH,
        option_id="SPLIT_TO_STYLE_LEVEL",
        operator_reason=REASON,
        proposed_lines=proposed,
        storage_root=storage,
    )

    bdir = storage / "outputs" / BATCH
    rows = json.loads((bdir / "pz_rows.json").read_text(encoding="utf-8"))
    for r in [x for x in rows if x["line_position"] == 1]:
        assert "_split_from_code" in r
        assert "_split_proportion" in r
        assert "_allocation_confidence" in r


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

def test_idempotency_second_call_returns_existing(svc, storage):
    """A second call with the same option_id must return already_executed=True."""
    proposed = [_make_proposed_line(1, "necklace", 12.0, "INV-01")]

    r1 = svc.execute_correction_option(
        batch_id=BATCH,
        option_id="ALIGN_TO_AUTHORITY",
        operator_reason=REASON,
        proposed_lines=proposed,
        storage_root=storage,
    )
    assert r1.ok
    assert not r1.already_executed

    r2 = svc.execute_correction_option(
        batch_id=BATCH,
        option_id="ALIGN_TO_AUTHORITY",
        operator_reason=REASON,
        proposed_lines=proposed,
        storage_root=storage,
    )
    assert r2.ok
    assert r2.already_executed, "Second call must return already_executed=True"


def test_idempotency_different_option_not_blocked(svc, storage):
    """If a different option_id is executed, it should not be blocked by prior record."""
    proposed = [_make_proposed_line(1, "necklace", 12.0, "INV-01")]

    # Execute ALIGN first
    svc.execute_correction_option(
        batch_id=BATCH,
        option_id="ALIGN_TO_AUTHORITY",
        operator_reason=REASON,
        proposed_lines=proposed,
        storage_root=storage,
    )

    # Execute KEEP_CURRENT with different option_id — NOT blocked
    r2 = svc.execute_correction_option(
        batch_id=BATCH,
        option_id="KEEP_CURRENT",
        operator_reason=REASON,
        proposed_lines=[],
        storage_root=storage,
    )
    # Different option_id → idempotency check returns None → proceeds fresh
    assert r2.ok
    assert not r2.already_executed, (
        "A different option_id must not be suppressed by the prior execution record"
    )


# ---------------------------------------------------------------------------
# wfirma_action field
# ---------------------------------------------------------------------------

def test_keep_current_wfirma_action_is_none(svc, storage):
    result = svc.execute_correction_option(
        batch_id=BATCH,
        option_id="KEEP_CURRENT",
        operator_reason=REASON,
        proposed_lines=[],
        storage_root=storage,
    )
    assert result.wfirma_action == "none"


def test_align_wfirma_action(svc, storage):
    proposed = [_make_proposed_line(1, "n", 12.0, "INV-01")]
    result = svc.execute_correction_option(
        batch_id=BATCH,
        option_id="ALIGN_TO_AUTHORITY",
        operator_reason=REASON,
        proposed_lines=proposed,
        storage_root=storage,
    )
    assert result.wfirma_action == "product_code_rename_in_staging"


def test_split_wfirma_action(svc, storage):
    proposed = [
        _make_proposed_line(1, "n", 7.0, "INV-01-N"),
        _make_proposed_line(1, "e", 5.0, "INV-01-E"),
    ]
    result = svc.execute_correction_option(
        batch_id=BATCH,
        option_id="SPLIT_TO_STYLE_LEVEL",
        operator_reason=REASON,
        proposed_lines=proposed,
        storage_root=storage,
    )
    assert result.wfirma_action == "pz_rows_rebuilt_split_staging"
