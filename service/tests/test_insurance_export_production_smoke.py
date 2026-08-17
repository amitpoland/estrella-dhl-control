"""Insurance Export — production acceptance smoke (opt-in, live).

Unit tests prove the code is self-consistent. They cannot prove that the
figures an operator is looking at right now are still the figures that were
signed off. This file closes that gap: it reads the LIVE statement and
compares it against measured production values in
``fixtures/insurance_export_production_pins.json``.

It is skipped by default and never runs in CI — it needs a running service and
a credential. Run it as the business step of a post-deployment closure::

    set PZ_SMOKE_BASE_URL=http://127.0.0.1:47213
    set PZ_SMOKE_API_KEY=<the service API key>
    pytest tests/test_insurance_export_production_smoke.py -v

READ-ONLY: one GET per pinned period. It never posts, never converges, never
writes. The API key is read from the environment, never from a file, and is
never logged — a failure message names documents and amounts, not the key.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from decimal import Decimal
from pathlib import Path

import pytest

PINS = Path(__file__).resolve().parent / "fixtures" / "insurance_export_production_pins.json"
BASE_URL = os.environ.get("PZ_SMOKE_BASE_URL")
API_KEY = os.environ.get("PZ_SMOKE_API_KEY")

pytestmark = pytest.mark.skipif(
    not BASE_URL or not API_KEY,
    reason="live smoke — set PZ_SMOKE_BASE_URL and PZ_SMOKE_API_KEY to run",
)


def _pins():
    return json.loads(PINS.read_text(encoding="utf-8"))


def _fetch(period):
    url = "%s/api/v1/accounting/insurance-export?from=%s&to=%s" % (
        BASE_URL.rstrip("/"), period["from"], period["to"])
    req = urllib.request.Request(
        url, headers={"X-API-Key": API_KEY, "User-Agent": "PZ-smoke/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:      # never echo the request headers
        pytest.fail("insurance-export %s..%s returned HTTP %s"
                    % (period["from"], period["to"], exc.code))


def _rows(report):
    return [r for g in report["contractors"] for r in g["rows"]]


def _all_rows(report):
    out = []
    for grp in report["contractors"]:
        for row in grp["rows"]:
            out.append(row)
            out.extend(row["adjustments"])
        out.extend(grp["unattached_adjustments"])
    return out


@pytest.fixture(scope="module")
def live():
    """One fetch per pinned period, shared across the assertions below."""
    return [(p, _fetch(p)) for p in _pins()["periods"]]


def test_the_pinned_documents_still_publish_the_same_figures(live):
    """Row-level: currency, sum insured, displayed rate, INR, premium.

    A refactor that changes any of these has changed a number a customer and
    an insurer have already been shown.
    """
    for period, report in live:
        by_number = {r["fullnumber"]: r for r in _rows(report)}
        for number, want in period["rows"].items():
            got = by_number.get(number)
            assert got is not None, "%s vanished from %s..%s" % (
                number, period["from"], period["to"])
            for field in ("currency", "sum_insured", "fx_rate_display",
                          "sum_insured_inr"):
                assert got[field] == want[field], "%s.%s" % (number, field)
            rec = got.get("insurance_recovered") or {}
            assert rec.get("amount") == want["recovered"]["amount"], number
            assert rec.get("currency") == want["recovered"]["currency"], number
            assert got["charge_authority_on_record"] is want[
                "charge_authority_on_record"], number
            if "status" in want:
                assert got["status"] == want["status"], number


def test_the_period_totals_and_authority_coverage_are_unchanged(live):
    for period, report in live:
        kpi = report["kpi"]
        assert len(_rows(report)) == period["documents"], period["from"]
        for field, want in period["kpi"].items():
            assert kpi[field] == want, "%s %s" % (period["from"], field)
        assert report["report_totals"]["rows_without_inr"] == period[
            "rows_without_inr"], period["from"]


def test_the_four_way_total_identity_holds_live(live):
    """The same identity the offline projection contract pins, measured on
    real data: rows -> contractor subtotals -> report totals -> KPI."""
    for period, report in live:
        groups = report["contractors"]
        docs = sum((Decimal(r["sum_insured_inr"]) for g in groups
                    for r in g["rows"] if r["sum_insured_inr"]), Decimal("0"))
        subs = sum((Decimal(g["subtotals"]["sum_insured_inr_documents"])
                    for g in groups), Decimal("0"))
        assert docs == subs, period["from"]
        assert str(subs) == report["report_totals"]["sum_insured_inr_documents"]
        assert report["kpi"]["gross_insured_inr"] == report["report_totals"][
            "sum_insured_inr_documents"]
        grand = sum((Decimal(g["subtotals"]["sum_insured_inr"])
                     for g in groups), Decimal("0"))
        assert str(grand) == report["report_totals"]["sum_insured_inr_grand"]
        assert report["kpi"]["net_insured_inr"] == report["report_totals"][
            "sum_insured_inr_grand"]


def test_every_live_review_row_still_shows_its_reason(live):
    """The operator-visible defect. If it returns, it returns here first."""
    for period, report in live:
        for row in _all_rows(report):
            if row["status"] != "needs_review":
                continue
            assert (row.get("recommendation_reason") or "").strip(), (
                "%s is needs_review with no reason" % row["fullnumber"])


def test_no_live_row_displays_more_than_four_decimals_of_rate(live):
    """And the full-precision rate stays available for provenance — capping
    the display must not delete the applied rate."""
    for period, report in live:
        for row in _all_rows(report):
            shown = row.get("fx_rate_display")
            if shown is None:
                continue
            assert len(shown.split(".")[1]) == 4, "%s %s" % (
                row["fullnumber"], shown)
            assert row.get("fx_rate"), row["fullnumber"]
            assert Decimal(shown) == Decimal(row["fx_rate"]).quantize(
                Decimal("0.0001")), row["fullnumber"]


def test_no_draft_derived_premium_has_reappeared(live):
    """A recovered premium exists only because an ISSUED document billed it.
    The forbidden amounts are values a draft once supplied and no issued
    document supports."""
    forbidden = set(_pins()["forbidden_recovered_amounts"])
    for period, report in live:
        for row in _all_rows(report):
            rec = row.get("insurance_recovered") or {}
            assert rec.get("amount") not in forbidden, "%s %s" % (
                row["fullnumber"], rec.get("amount"))
