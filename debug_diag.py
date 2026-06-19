"""
Diagnostic probe: run extract_packing on the production xlsx file and
trace whether column_mapping_audit gets set at each stage.
"""
import sys
sys.path.insert(0, r"C:\Users\Super Fashion\PZ APP\service")

import json
from pathlib import Path

# Patch logging to INFO so we see relevant messages
import logging
logging.basicConfig(level=logging.INFO, format="%(name)s %(levelname)s %(message)s")

# Import after path setup
from app.services.invoice_packing_extractor import (
    extract_packing,
    _extract_packing_excel,
    _collect_excel_diagnostic,
    _new_diagnostic,
    _find_header_row,
    _map_headers,
    _map_headers_with_audit,
    _read_excel_rows,
)

xlsx_path = Path(r"C:\PZ\storage\outputs\SHIPMENT_8400636576_2026-06_f82f6527\source\packing\EJL-26-27-233-Shipment packing list of 1pc-01.06.26-Client.xlsx")
xls_path  = Path(r"C:\PZ\storage\outputs\SHIPMENT_8400636576_2026-06_f82f6527\source\packing\EJL-26-27-233-Shipment packing list of 1pc-01.06.26-Poland.xls")

print("=" * 60)
print("TEST 1: xlsx via extract_packing (full path)")
print("=" * 60)
rows, pname, pver, diag = extract_packing(xlsx_path)
print(f"rows extracted: {len(rows)}")
print(f"row_count in diag: {diag.get('row_count')}")
print(f"column_mapping_audit entries: {len(diag.get('column_mapping_audit', []))}")
print(f"alias_hits: {diag.get('alias_hits')}")
print(f"mapped_columns count: {len(diag.get('mapped_columns', []))}")
if diag.get('column_mapping_audit'):
    methods = {}
    for e in diag['column_mapping_audit']:
        m = e.get('method', '?')
        methods[m] = methods.get(m, 0) + 1
    print(f"  audit methods: {methods}")
else:
    print("  column_mapping_audit is EMPTY!")

print()
print("=" * 60)
print("TEST 2: xlsx via _extract_packing_excel directly (audit_dict=diag)")
print("=" * 60)
diag2 = _new_diagnostic(".xlsx")
extracted = _extract_packing_excel(xlsx_path, engine="openpyxl", _audit_dict=diag2)
print(f"rows extracted: {len(extracted)}")
print(f"column_mapping_audit after _extract_packing_excel: {len(diag2.get('column_mapping_audit', []))}")
if diag2.get('column_mapping_audit'):
    methods2 = {}
    for e in diag2['column_mapping_audit']:
        m = e.get('method', '?')
        methods2[m] = methods2.get(m, 0) + 1
    print(f"  audit methods: {methods2}")
else:
    print("  still EMPTY after _extract_packing_excel!")

print()
print("=" * 60)
print("TEST 3: _collect_excel_diagnostic on xlsx")
print("=" * 60)
_collect_excel_diagnostic(xlsx_path, "openpyxl", diag2)
print(f"column_mapping_audit after _collect_excel_diagnostic: {len(diag2.get('column_mapping_audit', []))}")
print(f"alias_hits after: {diag2.get('alias_hits')}")
print(f"mapped_columns after: {len(diag2.get('mapped_columns', []))}")

print()
print("=" * 60)
print("TEST 4: XLS via extract_packing (should have audit)")
print("=" * 60)
rows_xls, _, _, diag_xls = extract_packing(xls_path)
print(f"rows extracted: {len(rows_xls)}")
print(f"column_mapping_audit entries: {len(diag_xls.get('column_mapping_audit', []))}")
if diag_xls.get('column_mapping_audit'):
    methods_xls = {}
    for e in diag_xls['column_mapping_audit']:
        m = e.get('method', '?')
        methods_xls[m] = methods_xls.get(m, 0) + 1
    print(f"  audit methods: {methods_xls}")

print()
print("=" * 60)
print("TEST 5: _find_header_row for xlsx")
print("=" * 60)
rows_raw = _read_excel_rows(xlsx_path, "openpyxl")
hdr_idx = _find_header_row(rows_raw)
print(f"hdr_idx: {hdr_idx}")
if hdr_idx >= 0:
    hdr_cells = [str(c) if c is not None else "" for c in rows_raw[hdr_idx]]
    print(f"header row: {hdr_cells[:15]}")
    col_map_simple = _map_headers(hdr_cells)
    print(f"_map_headers result: {len(col_map_simple)} mappings")
    col_map_audit, audit = _map_headers_with_audit(hdr_cells)
    print(f"_map_headers_with_audit: {len(col_map_audit)} mappings, {len(audit)} audit entries")
    if audit:
        import dataclasses
        sample = dataclasses.asdict(audit[0])
        print(f"  first audit entry: {sample}")
