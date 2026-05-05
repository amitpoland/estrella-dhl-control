"""
test_regenerate_stale_batches.py — Operator-triggered cache regeneration tool.
Covers --dry-run, --apply, source-doc gating, backup creation, and filter.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from app.services.cache_freshness import CURRENT_ROW_SCHEMA_VERSION
from app.tools import regenerate_stale_batches as rsb


# ── Helpers ───────────────────────────────────────────────────────────────────

def _v2_row(invoice_no: str, line_pos: int) -> dict:
    return {
        "invoice_no":     invoice_no,
        "product_code":   f"{invoice_no}-{line_pos}",
        "line_position":  line_pos,
        "nazwa_pl":       "pierścionek",
        "nazwa_en":       "Plain 9KT Gold Jewellery RING",
        "nazwa":          "pierścionek / Plain 9KT Gold Jewellery RING",
        "quantity":       1,
    }


def _make_batch(
    parent: Path,
    batch_id: str,
    *,
    fresh: bool,
    with_invoices: bool = True,
    with_sad: bool = True,
    with_awb: bool = True,
    awb_in_audit: bool = True,
) -> Path:
    bdir = parent / batch_id
    (bdir / "source" / "invoices").mkdir(parents=True, exist_ok=True)
    (bdir / "source" / "sad").mkdir(parents=True, exist_ok=True)
    (bdir / "source" / "awb").mkdir(parents=True, exist_ok=True)

    if with_invoices:
        (bdir / "source" / "invoices" / "INV1.pdf").write_bytes(b"%PDF-1.4 invoice\n")
    if with_sad:
        (bdir / "source" / "sad" / "ZC429.pdf").write_bytes(b"%PDF-1.4 sad\n")
    if with_awb:
        (bdir / "source" / "awb" / "AWB.pdf").write_bytes(b"%PDF-1.4 awb\n")

    audit = {
        "batch_id": batch_id,
        "tracking_no": "1234567890",
        "doc_no": "PZ TEST",
        "inputs": {
            "invoices": ["INV1.pdf"],
            "zc429":    "ZC429.pdf",
            "awb":      "AWB.pdf" if awb_in_audit else "",
        },
        "rows": [_v2_row("EJL/25-26/1247", 1)],
    }
    if fresh:
        audit["row_schema_version"] = CURRENT_ROW_SCHEMA_VERSION

    (bdir / "audit.json").write_text(json.dumps(audit), encoding="utf-8")
    return bdir


# ── Dry-run ───────────────────────────────────────────────────────────────────

class TestDryRun:
    def test_detects_stale_batch(self, tmp_path):
        outputs = tmp_path / "outputs"; outputs.mkdir()
        _make_batch(outputs, "SHIPMENT_STALE",  fresh=False)
        _make_batch(outputs, "SHIPMENT_FRESH",  fresh=True)

        reports = rsb.scan_outputs(outputs)
        idx = {r.batch_id: r for r in reports}

        assert idx["SHIPMENT_STALE"].stale is True
        assert idx["SHIPMENT_STALE"].source_docs_available is True
        assert idx["SHIPMENT_STALE"].recommended_action == "regenerate"

        assert idx["SHIPMENT_FRESH"].stale is False
        assert idx["SHIPMENT_FRESH"].recommended_action == "skip_fresh"

    def test_dry_run_does_not_mutate(self, tmp_path):
        outputs = tmp_path / "outputs"; outputs.mkdir()
        bdir = _make_batch(outputs, "SHIPMENT_X", fresh=False)
        before = sorted(p.relative_to(bdir).as_posix() for p in bdir.rglob("*"))
        rsb.scan_outputs(outputs)
        after  = sorted(p.relative_to(bdir).as_posix() for p in bdir.rglob("*"))
        assert before == after

    def test_flags_missing_sources(self, tmp_path):
        outputs = tmp_path / "outputs"; outputs.mkdir()
        _make_batch(outputs, "SHIPMENT_NO_SAD", fresh=False, with_sad=False)
        reports = rsb.scan_outputs(outputs)
        r = reports[0]
        assert r.stale is True
        assert r.source_docs_available is False
        assert "sad" in r.missing_source_kinds
        assert r.recommended_action == "manual_review_missing_sources"

    def test_batch_filter_limits_scope(self, tmp_path):
        outputs = tmp_path / "outputs"; outputs.mkdir()
        _make_batch(outputs, "SHIPMENT_A", fresh=False)
        _make_batch(outputs, "SHIPMENT_B", fresh=False)
        reports = rsb.scan_outputs(outputs, batch_filter="SHIPMENT_B")
        assert [r.batch_id for r in reports] == ["SHIPMENT_B"]


# ── Apply ─────────────────────────────────────────────────────────────────────

class TestApply:
    def _fake_engine(self, batch_dir: Path):
        """Stand-in for app.services.export_service.process_shipment.

        Writes a v2-compatible audit.json and dummy PDF/XLSX; never touches
        the real engine (so tests stay fast and offline).
        """
        def _process(invoice_dir, zc429_path, output_dir, **_kwargs):
            audit = {
                "batch_id":           output_dir.name,
                "row_schema_version": CURRENT_ROW_SCHEMA_VERSION,
                "rows":               [_v2_row("EJL/25-26/1247", 1)],
                "inputs": {
                    "invoices": [Path(zc429_path).parent.parent.name],
                    "zc429":    Path(zc429_path).name,
                    "awb":      "AWB.pdf",
                },
            }
            (output_dir / "audit.json").write_text(
                json.dumps(audit), encoding="utf-8")
            pdf  = output_dir / "PZ_regen.pdf";  pdf.write_bytes(b"%PDF-1.4\n")
            xlsx = output_dir / "PZ_regen.xlsx"; xlsx.write_bytes(b"PK\x03\x04xlsx")
            return {"pdf_path": pdf, "xlsx_path": xlsx}
        return _process

    def test_refuses_when_sources_missing(self, tmp_path):
        outputs = tmp_path / "outputs"; outputs.mkdir()
        _make_batch(outputs, "SHIPMENT_NO_INV", fresh=False, with_invoices=False)
        reports = rsb.apply_outputs(outputs, process_shipment_fn=self._fake_engine(None))
        r = reports[0]
        assert r.regenerated is False
        assert "manual_review_missing_sources" in r.reason

    def test_skips_fresh_batch(self, tmp_path):
        outputs = tmp_path / "outputs"; outputs.mkdir()
        _make_batch(outputs, "SHIPMENT_FRESH", fresh=True)
        reports = rsb.apply_outputs(outputs, process_shipment_fn=self._fake_engine(None))
        assert reports[0].regenerated is False
        assert "skip_fresh" in reports[0].reason

    def test_creates_backup_and_regenerates(self, tmp_path):
        outputs = tmp_path / "outputs"; outputs.mkdir()
        bdir = _make_batch(outputs, "SHIPMENT_RG", fresh=False)
        reports = rsb.apply_outputs(outputs, process_shipment_fn=self._fake_engine(None))
        r = reports[0]
        assert r.regenerated is True
        assert r.backup_dir is not None
        assert Path(r.backup_dir).is_dir()
        # Backup must contain the original audit.json
        assert (Path(r.backup_dir) / "audit.json").is_file()
        # Original audit.json now stamped v2
        new_audit = json.loads((bdir / "audit.json").read_text())
        assert new_audit["row_schema_version"] == CURRENT_ROW_SCHEMA_VERSION

    def test_apply_filter_to_single_batch(self, tmp_path):
        outputs = tmp_path / "outputs"; outputs.mkdir()
        _make_batch(outputs, "SHIPMENT_A", fresh=False)
        _make_batch(outputs, "SHIPMENT_B", fresh=False)
        reports = rsb.apply_outputs(
            outputs, batch_filter="SHIPMENT_A",
            process_shipment_fn=self._fake_engine(None),
        )
        assert [r.batch_id for r in reports] == ["SHIPMENT_A"]
        assert reports[0].regenerated is True

    def test_apply_does_not_delete_existing_files(self, tmp_path):
        outputs = tmp_path / "outputs"; outputs.mkdir()
        bdir = _make_batch(outputs, "SHIPMENT_KEEP", fresh=False)
        # Create an extra historical artifact that must survive regeneration
        (bdir / "audit_report_pl.pdf").write_bytes(b"%PDF-1.4 historical")

        reports = rsb.apply_outputs(outputs, process_shipment_fn=self._fake_engine(None))
        assert reports[0].regenerated is True
        # Original file still present (engine fake doesn't touch it)
        assert (bdir / "audit_report_pl.pdf").is_file()
        # Backup contains the historical file too
        assert (Path(reports[0].backup_dir) / "audit_report_pl.pdf").is_file()


# ── CLI smoke ─────────────────────────────────────────────────────────────────

class TestCLI:
    def test_cli_dry_run_returns_zero(self, tmp_path, capsys, monkeypatch):
        outputs = tmp_path / "outputs"; outputs.mkdir()
        _make_batch(outputs, "SHIPMENT_X", fresh=False)
        rc = rsb.main(["--dry-run", "--outputs-dir", str(outputs)])
        captured = capsys.readouterr().out
        assert rc == 0
        assert "SHIPMENT_X" in captured
        assert "regenerate" in captured

    def test_cli_dry_run_json(self, tmp_path, capsys):
        outputs = tmp_path / "outputs"; outputs.mkdir()
        _make_batch(outputs, "SHIPMENT_X", fresh=False)
        rc = rsb.main(["--dry-run", "--outputs-dir", str(outputs), "--json"])
        out = capsys.readouterr().out
        assert rc == 0
        data = json.loads(out)
        assert data[0]["batch_id"] == "SHIPMENT_X"
        assert data[0]["stale"] is True

    def test_cli_requires_dry_run_or_apply(self, capsys):
        with pytest.raises(SystemExit):
            rsb.main([])
