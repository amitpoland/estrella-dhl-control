"""
excel_reader.py — Single Excel-reading authority for all shipment parsers.

Public API
----------
``read_excel_rows(path, engine=None) -> List[List[Any]]``
    Read every cell of the active/first sheet.
    Returns a list of rows; each row is a list of cell values.
    Empty cells are normalised to None for all engines.

Supported engines (auto-detected from file suffix when engine=None):
    "openpyxl"  — .xlsx  (requires openpyxl>=3.1)
    "xlrd"      — .xls   (requires xlrd>=1.2,<2.0 — legacy format only)
    "pyxlsb"    — .xlsb  (requires pyxlsb>=1.0.10)

Safety
------
- Never touches DB, wFirma, PZ, or business state.
- Never raises on bad-value cells; bad values are returned as-is.
- Does raise ValueError for unsupported extensions / unknown engine names.
- Does propagate IOError / PermissionError from the underlying library
  so callers can wrap in their own try/except as before.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, List, Optional

__all__ = ["read_excel_rows"]

_ENGINE_BY_SUFFIX: dict[str, str] = {
    ".xlsx": "openpyxl",
    ".xls":  "xlrd",
    ".xlsb": "pyxlsb",
}


def read_excel_rows(
    path: Path,
    engine: Optional[str] = None,
) -> List[List[Any]]:
    """Read all rows from the active/first sheet.

    Parameters
    ----------
    path:
        File system path to the Excel workbook.
    engine:
        One of "openpyxl", "xlrd", "pyxlsb", or None.
        When None the engine is auto-detected from path.suffix.

    Returns
    -------
    List of rows. Each row is a list of cell values.
    Empty cells are None for every engine (openpyxl and pyxlsb return None
    natively; xlrd empty strings are normalised to None for consistency).

    Raises
    ------
    ValueError
        Unknown engine name, or suffix not recognised when engine=None.
    """
    if engine is None:
        suffix = path.suffix.lower()
        engine = _ENGINE_BY_SUFFIX.get(suffix)
        if engine is None:
            raise ValueError(
                f"Cannot auto-detect Excel engine for extension '{suffix}'. "
                f"Supported: {sorted(_ENGINE_BY_SUFFIX)}"
            )

    if engine == "openpyxl":
        return _read_openpyxl(path)
    if engine == "xlrd":
        return _read_xlrd(path)
    if engine == "pyxlsb":
        return _read_pyxlsb(path)

    raise ValueError(
        f"Unknown Excel engine: '{engine}'. "
        f"Supported: 'openpyxl', 'xlrd', 'pyxlsb'."
    )


# ── engine implementations ────────────────────────────────────────────────────

def _read_openpyxl(path: Path) -> List[List[Any]]:
    import openpyxl  # type: ignore
    wb = openpyxl.load_workbook(str(path), data_only=True)
    ws = wb.active
    return [list(row) for row in ws.iter_rows(values_only=True)]


def _read_xlrd(path: Path) -> List[List[Any]]:
    import xlrd  # type: ignore
    wb = xlrd.open_workbook(str(path))
    sh = wb.sheet_by_index(0)
    out: List[List[Any]] = []
    for r in range(sh.nrows):
        row: List[Any] = []
        for c in range(sh.ncols):
            v = sh.cell_value(r, c)
            # Normalise xlrd's empty-string representation to None so callers
            # receive a consistent type regardless of engine.
            row.append(None if v == "" else v)
        out.append(row)
    return out


def _read_pyxlsb(path: Path) -> List[List[Any]]:
    import pyxlsb  # type: ignore
    with pyxlsb.open_workbook(str(path)) as wb:
        with wb.get_sheet(1) as ws:
            return [[cell.v for cell in row] for row in ws.rows()]
