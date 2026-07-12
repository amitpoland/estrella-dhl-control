"""
test_v2_money_format.py — Wave-1 contract for the shared V2 money formatter.

Campaign: EJ Dashboard Stabilization Sprint 1, Wave 1 (quick production defects).

Pins two defects fixed in Wave 1:

  A. Shipment-list monetary columns rendered raw engine floats (long decimal
     tails). Fix: a single shared formatter `fmtMoney2` in components.jsx
     (exactly two decimals, locale-grouped, null → em-dash), consumed by the
     net/gross/duty columns in dashboard-page.jsx and by the detail page's
     _fmtPln / _fmtUsd helpers.

  B. pz-api.js had a duplicate `applyServiceCharges` object key. The later
     (Wave-3) definition silently won and used `_post` with a bare-array body,
     dropping the required X-Operator header and the {expected_updated_at,
     apply:[...]} contract → 400. Fix: single definition on `_postM` with the
     3-arg (draftId, applyList, updatedAt) contract the caller uses.

Static assertions run everywhere (CI has no Node). An optional logic regression
shells out to Node with the vendored Babel when available, and skips otherwise.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

V2 = Path(__file__).parents[1] / "app" / "static" / "v2"
COMPONENTS = V2 / "components.jsx"
DASHBOARD = V2 / "dashboard-page.jsx"
DETAIL = V2 / "shipment-detail-page.jsx"
PZ_API = V2 / "pz-api.js"


def _read(p: Path) -> str:
    if not p.exists():
        pytest.skip(f"{p} not found")
    return p.read_text(encoding="utf-8")


# ── A. Shared formatter exists and is exported ───────────────────────────────

def test_fmtmoney2_defined_and_exported():
    src = _read(COMPONENTS)
    assert "function fmtMoney2(" in src, "fmtMoney2 must be defined in components.jsx"
    # exported on the window global bag alongside the other primitives
    export_block = re.search(r"Object\.assign\(window,\s*\{(.+?)\}\)", src, re.DOTALL)
    assert export_block, "components.jsx Object.assign(window, {...}) export block not found"
    assert "fmtMoney2" in export_block.group(1), "fmtMoney2 must be exported on window"


def test_fmtmoney2_two_decimal_intent():
    src = _read(COMPONENTS)
    block = src[src.index("function fmtMoney2"):]
    block = block[: block.index("Object.assign(window")]
    assert "minimumFractionDigits: 2" in block and "maximumFractionDigits: 2" in block, (
        "fmtMoney2 must pin exactly two fraction digits"
    )


# ── A. Shipment list consumes the formatter for money columns ────────────────

def test_dashboard_money_columns_use_formatter():
    src = _read(DASHBOARD)
    # net/gross/duty must render through the money formatter, not raw _fmt
    for field in ("row.net", "row.gross", "row.duty"):
        assert re.search(rf"_money\(\s*{re.escape(field)}\s*\)", src), (
            f"{field} must render via _money(...) (2-dp formatter), not raw _fmt"
        )
    assert "window.fmtMoney2" in src, "dashboard-page.jsx must delegate to window.fmtMoney2"
    # pl-PL is the established V2 money convention (kanban + detail) — the list
    # must match it so the same PLN value reads identically across surfaces.
    assert "pl-PL" in src, "dashboard-page.jsx _money must use the pl-PL house locale"


def test_detail_pln_no_longer_depends_on_dead_shared():
    src = _read(DETAIL)
    # dashboard-shared.js is intentionally not loaded in v2, so the old
    # EstrellaShared.fmtPLN branch was dead. It must be gone; helper must
    # route through the shared window.fmtMoney2 authority.
    assert "EstrellaShared && window.EstrellaShared.fmtPLN" not in src, (
        "detail page must not depend on the dead EstrellaShared.fmtPLN path"
    )
    assert "window.fmtMoney2" in src, "detail page _fmtPln/_fmtUsd must use window.fmtMoney2"


# ── B. applyServiceCharges duplicate-key contract ────────────────────────────

def test_apply_service_charges_single_definition():
    src = _read(PZ_API)
    assert src.count("applyServiceCharges:") == 1, (
        "applyServiceCharges must be defined exactly once (duplicate object keys "
        "let the wrong definition silently win)"
    )
    assert src.count("suggestServiceCharges:") == 1, (
        "suggestServiceCharges must be defined exactly once"
    )


def test_apply_service_charges_uses_operator_mutation_contract():
    src = _read(PZ_API)
    # Slice the single applyServiceCharges definition (up to the next method or
    # the closing of the api object) and assert its shape.
    idx = src.index("applyServiceCharges:")
    defn = src[idx: idx + 400]
    args_m = re.match(r"applyServiceCharges:\s*\((?P<args>[^)]*)\)\s*=>", defn)
    assert args_m, "applyServiceCharges must be an arrow function"
    args = [a.strip() for a in args_m.group("args").split(",")]
    assert args == ["draftId", "applyList", "updatedAt"], (
        f"applyServiceCharges must keep the 3-arg caller contract, got {args}"
    )
    assert "_postM(" in defn, "applyServiceCharges must call _postM (injects X-Operator)"
    assert "expected_updated_at: updatedAt" in defn, (
        "applyServiceCharges must send expected_updated_at (optimistic lock)"
    )
    assert "apply: applyList" in defn, "applyServiceCharges must send the apply list"


# ── Optional: real logic regression via vendored Babel + Node ────────────────

def test_fmtmoney2_logic_regression_via_node():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available (CI has no Node) — static assertions cover the contract")
    babel = V2 / "vendor" / "babel.min.js"
    if not babel.exists():
        pytest.skip("vendored babel.min.js not present")

    comp_src = COMPONENTS.read_text(encoding="utf-8")
    start = comp_src.index("function fmtMoney2")
    end = comp_src.index("\nObject.assign(window", start)
    fn_src = comp_src[start:end]

    cases = [
        [1234, None, "1,234.00"],
        [1234.5, None, "1,234.50"],
        [6330.499, None, "6,330.50"],
        ["1234.56", None, "1,234.56"],
        ["1,234.56", None, "1,234.56"],
        ["1.5e6", None, "1,500,000.00"],   # HIGH-1: scientific notation must NOT be corrupted
        [None, None, "—"],
        ["", None, "—"],
        [-1234.5, None, "-1,234.50"],
        [0, None, "0.00"],
        ["PLN 6,330", None, "6,330.00"],
        ["n/a", None, "n/a"],
        [1234, {"currency": "USD"}, "USD 1,234.00"],
    ]
    script = (
        fn_src
        + "\nconst cases = " + json.dumps(cases) + ";\n"
        + "let bad = 0;\n"
        + "for (const [inp, opts, exp] of cases) {\n"
        + "  const got = fmtMoney2(inp, opts || undefined);\n"
        + "  if (got !== exp) { bad++; console.error('FAIL', JSON.stringify(inp), JSON.stringify(got), '!=', JSON.stringify(exp)); }\n"
        + "}\n"
        + "process.exit(bad === 0 ? 0 : 1);\n"
    )
    proc = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, f"fmtMoney2 logic regression failed:\n{proc.stderr}"
