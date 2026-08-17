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


def test_the_pdf_renderer_only_adds_already_quantized_values():
    """The PDF prints a group subtotal, which means it aggregates. Aggregation
    of authority-quantized strings is presentation; anything else is a second
    monetary authority.

    So: ``+`` and ``quantize`` are permitted on Decimal, ``*`` and ``/`` are
    not, and no money value may pass through ``float`` — which would silently
    make the printed total disagree with the backend's.
    """
    code = _strip_comments(RENDERER, RENDERER.read_text(encoding="utf-8"))
    assert not re.search(r"Decimal\([^)]*\)\s*[*/]", code)
    assert not re.search(r"[*/]\s*Decimal\(", code)
    assert "float(" not in code
    assert "round(" not in code
    # The one aggregation is an accumulation of sum_insured_inr, nothing else.
    accumulated = re.findall(r"total\s*\+=\s*Decimal\((\w+)\)", code)
    assert accumulated == ["v"], accumulated
    assert re.search(r'v\s*=\s*r\.get\("sum_insured_inr"\)', code)


def test_the_pdf_footer_totals_come_from_the_backend():
    """ORIGINAL SHIPMENTS / ADJUSTMENTS / PERIOD TOTAL are the declaration
    totals the backend resolved. The renderer must not re-derive them from the
    rows it happens to have printed — that is how a PDF starts disagreeing
    with the screen."""
    code = _strip_comments(RENDERER, RENDERER.read_text(encoding="utf-8"))
    for label in ("ORIGINAL SHIPMENTS", "ADJUSTMENTS", "PERIOD TOTAL"):
        row = re.search(
            r'_totals_row\(\s*\n?\s*"%s",\s*\n?\s*([^)]+)\)' % label, code)
        assert row, label
        assert row.group(1).strip().startswith("declaration_totals.get("), label


def test_each_renderer_has_exactly_one_money_formatter():
    """Two formatters is two rounding policies waiting to diverge."""
    pdf = _strip_comments(RENDERER, RENDERER.read_text(encoding="utf-8"))
    assert len(re.findall(r"^def _num_cell\(", pdf, re.M)) == 1

    if not JSX.exists():
        return
    jsx = _strip_comments(JSX, JSX.read_text(encoding="utf-8"))
    assert len(re.findall(r"function InsMoney\(", jsx)) == 1
    # No locale/number formatting anywhere: the backend string is the value.
    assert "Intl.NumberFormat" not in jsx
    assert "toLocaleString" not in jsx


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


def test_frontend_never_derives_a_cross_rate():
    """PLN→USD→INR is resolved server-side inside the FX boundary. The JSX may
    only display the provenance the backend already computed."""
    if not JSX.exists():
        return
    code = _strip_comments(JSX, JSX.read_text(encoding="utf-8"))
    # No arithmetic involving either leg of the cross rate.
    for field in ("fx_rate", "nbp_leg", "india_leg", "pln_per", "inr_per"):
        assert not re.search(re.escape(field) + r"\S*\s*[*/]\s*\w", code), field
        # No numeric coercion of a rate either — display strings stay strings.
        # (``Number()`` on the period selector inputs is not monetary.)
        assert not re.search(r"Number\([^)]*" + re.escape(field), code), field
    assert "CROSS_RATE" not in code


def test_only_the_fx_boundary_consults_nbp():
    """NBP is reachable from exactly one module in this surface. The statement
    service, the routes and the renderer must never reach it directly."""
    for path in (SERVICE, ROUTES, RENDERER):
        code = _strip_comments(path, path.read_text(encoding="utf-8"))
        assert "nbp_rate_service" not in code, path.name
        assert "get_nbp_rate" not in code, path.name


def test_fx_boundary_never_reads_the_nbp_inr_quote():
    """NBP's own INR mid is a Polish accounting rate, never the insurer's
    India benchmark. Only the USD bridge leg may be fetched."""
    provider = APP / "services" / "insurance_fx_provider.py"
    code = _strip_comments(provider, provider.read_text(encoding="utf-8"))
    assert 'fetch_rate("INR"' not in code
    assert "fetch_rate('INR'" not in code
    # The one NBP call site asks for the declared bridge currency, nothing else.
    calls = re.findall(r"nbp_rate_service\.fetch_rate\(\s*([^,]+)", code)
    assert calls == ["BRIDGE_CURRENCY"], calls
