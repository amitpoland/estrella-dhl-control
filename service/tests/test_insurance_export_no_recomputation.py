"""Insurance Export Statement — source-grep governance pins.

R-xx style: the reporting surface must never recompute the insurance
premium (ADR-proforma-freight-insurance-authority) and must never make a
country-based pickup decision. Also pins Lesson G no-store headers on the
download route and the mandatory ``resolve_commercial_charges`` import.
"""
from __future__ import annotations

import re
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"

SERVICE = APP / "services" / "insurance_export_statement.py"
ROUTES = APP / "api" / "routes_insurance_export.py"
RENDERER = APP / "services" / "insurance_export_pdf_renderer.py"
JSX = APP / "static" / "v2" / "insurance-export-tab.jsx"


def _sources():
    files = [SERVICE, ROUTES, RENDERER]
    if JSX.exists():
        files.append(JSX)
    return {p: p.read_text(encoding="utf-8") for p in files}


def _strip_comments(path, text):
    """Drop full-line comments so governance prose never trips the grep."""
    if path.suffix == ".py":
        lines = [
            ln for ln in text.splitlines()
            if not ln.strip().startswith("#")
        ]
    else:
        lines = [
            ln for ln in text.splitlines()
            if not ln.strip().startswith("//") and not ln.strip().startswith("*")
        ]
    return "\n".join(lines)


def test_no_premium_recomputation_formula():
    pattern = re.compile(r"sales_total\s*\*\s*rate")
    for path, text in _sources().items():
        assert not pattern.search(text), path.name


def test_no_hardcoded_insurance_rate():
    for path, text in _sources().items():
        assert "0.0035" not in text, path.name


def test_no_country_based_pickup_decision():
    country_eq = re.compile(r"country\s*==")
    for path, text in _sources().items():
        code = _strip_comments(path, text)
        assert not country_eq.search(code), path.name
        assert '"Poland"' not in code, path.name
        assert "'Poland'" not in code, path.name


def test_service_consumes_commercial_charge_authority():
    text = SERVICE.read_text(encoding="utf-8")
    assert "resolve_commercial_charges" in text
    # And it must be an import from the authority module, not a re-definition.
    # (Tolerates the parenthesized multi-line import form.)
    assert re.search(
        r"from\s+\S*commercial_charge_authority\s+import\s+"
        r"(?:\()?[^)]*resolve_commercial_charges",
        text,
        re.DOTALL,
    )
    assert "def resolve_commercial_charges" not in text


def test_routes_set_lesson_g_no_store():
    text = ROUTES.read_text(encoding="utf-8")
    assert "no-store" in text
    assert "must-revalidate" in text
    assert "Pragma" in text


def test_renderer_never_multiplies_sum_insured():
    """The renderer prints strings; any Decimal/float math on row values
    would be recomputation on the presentation layer."""
    text = RENDERER.read_text(encoding="utf-8")
    assert not re.search(r"sum_insured\S*\s*\*", text)
    assert not re.search(r"inv_cif\S*\s*\*", text)


def test_frontend_has_no_monetary_math():
    if not JSX.exists():
        return
    code = _strip_comments(JSX, JSX.read_text(encoding="utf-8"))
    # No arithmetic on monetary fields client-side — totals come only from
    # the declaration-preview response.
    for field in ("sum_insured", "inv_cif", "plus_10", "fx_rate"):
        assert not re.search(re.escape(field) + r"\S*\s*[*+]\s*\d", code), field
    assert "parseFloat" not in code
    assert "toFixed" not in code
