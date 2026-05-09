"""
test_payments_probe_phase10a5.py — Phase 10A.5 probe tool guards.

Covers:
  * Tool imports cleanly without live wFirma calls.
  * The write-action screen rejects every forbidden action and lets
    legitimate read actions through to the underlying transport.
  * Source-grep: tool source contains no `payments/add` / `invoices/add`
    / `*_edit` / `*_delete` / `*_send` / `*_fiscalise` references in
    code paths (only in the FORBIDDEN_ACTIONS sentinel + docstring).
  * The committed evidence markdown contains NO raw XML, NO `<api>`
    payload, NO monetary value, and NO customer name.
  * The placeholder evidence file does not yet claim probe results.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.tools import probe_payments_and_invoice_payment_state as probe


REPO_ROOT = Path(__file__).resolve().parents[2]
TOOL_PATH = (
    REPO_ROOT / "service" / "app" / "tools"
    / "probe_payments_and_invoice_payment_state.py"
)
EVIDENCE_PATH = REPO_ROOT / "docs" / "WFIRMA_PAYMENTS_PROBE_EVIDENCE.md"


# ── 1. Import cleanly ──────────────────────────────────────────────────────

def test_tool_imports_cleanly():
    assert hasattr(probe, "main")
    assert hasattr(probe, "probe_invoice_get")
    assert hasattr(probe, "probe_payments_find")
    assert hasattr(probe, "probe_payments_get")
    assert hasattr(probe, "render_evidence_markdown")


def test_field_inventory_pinned():
    """The seven payment-state fields plus the four sanity-baseline
    fields are exactly what the task spec demands."""
    assert set(probe._INVOICE_FIELDS_OF_INTEREST) == {
        "paymentstate", "alreadypaid", "remaining",
        "paymentdate", "paid_date",
        "total", "netto", "brutto", "currency",
        "contractor/id", "fullnumber",
    }


def test_forbidden_actions_pinned():
    assert set(probe._FORBIDDEN_ACTIONS) == {
        "add", "edit", "delete", "send",
        "fiscalise", "unfiscalise",
    }


# ── 2. Write-action screen ────────────────────────────────────────────────

@pytest.mark.parametrize("module,action", [
    ("invoices",  "add"),
    ("invoices",  "edit"),
    ("invoices",  "delete"),
    ("invoices",  "send"),
    ("invoices",  "fiscalise"),
    ("invoices",  "unfiscalise"),
    ("payments",  "add"),
    ("payments",  "edit"),
    ("payments",  "delete"),
    # Composite shapes — the screen splits on '/' and inspects head.
    ("invoices",  "add/12345"),
    ("payments",  "edit/9001"),
    ("payments",  "delete/1"),
])
def test_read_only_call_refuses_writes(module, action, monkeypatch):
    """Even if a buggy probe path tries to call a write action, the
    transport guard refuses BEFORE any HTTP call is made."""
    called = {"n": 0}
    def _spy(*a, **kw):
        called["n"] += 1
        return 200, "<api/>"
    # If the screen leaks, the spy would be invoked — fail loudly.
    monkeypatch.setattr(
        "app.services.wfirma_client._http_request", _spy,
    )
    with pytest.raises(probe.ProbeWriteRefused):
        probe._read_only_call("POST", module, action, "<api/>")
    assert called["n"] == 0


@pytest.mark.parametrize("module,action", [
    ("invoices",  "find"),
    ("invoices",  "get"),
    ("invoices",  "get/12345"),
    ("payments",  "find"),
    ("payments",  "get"),
    ("payments",  "get/9001"),
])
def test_read_only_call_allows_reads(module, action, monkeypatch):
    """Read actions reach the transport layer."""
    called = {"args": None}
    def _spy(method, m, a, body):
        called["args"] = (method, m, a, body)
        return 200, '<api><status><code>OK</code></status></api>'
    monkeypatch.setattr(
        "app.services.wfirma_client._http_request", _spy,
    )
    probe._read_only_call("GET", module, action, "")
    assert called["args"] == ("GET", module, action, "")


# ── 3. Source-grep: no write call paths ───────────────────────────────────

def test_tool_source_has_no_live_write_call_paths():
    """Defence-in-depth: greps the tool source to confirm no
    ``_http_request("..."  + writeaction)`` patterns exist outside the
    forbidden-set / docstring. We assert that the tool only ever passes
    one of these literal action strings to ``_read_only_call`` /
    ``_http_request``: 'find', 'get', 'get/{id}'."""
    src = TOOL_PATH.read_text(encoding="utf-8")
    # Find every direct _read_only_call / _http_request invocation
    # and confirm the action argument is NOT a forbidden literal.
    pattern = re.compile(
        r"_(?:read_only_call|http_request)\(\s*"
        r'"(?P<method>GET|POST|PUT|DELETE)"\s*,\s*'
        r'"(?P<module>\w+)"\s*,\s*'
        r'(?:f?)"(?P<action>[^"]+)"',
        re.MULTILINE,
    )
    matches = pattern.findall(src)
    assert matches, "expected at least one _http_request call site"
    for method, module, action in matches:
        head = action.split("/", 1)[0]
        assert head not in probe._FORBIDDEN_ACTIONS, (
            f"forbidden action literal {action!r} found in tool source "
            f"({module}/{action}) — must use only read endpoints"
        )


def test_tool_uses_only_get_method():
    """Reading wFirma data is GET-only in this codebase. No POST/PUT/
    DELETE call sites in the probe."""
    src = TOOL_PATH.read_text(encoding="utf-8")
    # Same regex as above but only inspect the method field.
    methods = re.findall(
        r"_(?:read_only_call|http_request)\(\s*\"(\w+)\"",
        src,
    )
    assert methods, "expected at least one transport call"
    for m in methods:
        assert m == "GET", (
            f"non-GET method {m!r} in probe tool — read-only constraint "
            "broken"
        )


# ── 4. Evidence markdown contract ─────────────────────────────────────────

def test_evidence_file_exists_as_placeholder():
    assert EVIDENCE_PATH.exists(), (
        "Phase 10A.5 evidence placeholder must exist so the "
        "routes_ledgers.py TODO can be satisfied by a single probe run."
    )


def test_evidence_file_carries_no_raw_xml():
    """The placeholder must not invent probe results. Specifically: no
    <api>... payload, no <invoice>... fragment, no monetary values."""
    text = EVIDENCE_PATH.read_text(encoding="utf-8")
    forbidden_substrings = [
        "<api>", "</api>",
        "<invoice>", "</invoice>",
        "<payment>", "</payment>",
        "<paymentcontent>",
    ]
    for s in forbidden_substrings:
        assert s not in text, (
            f"raw XML fragment {s!r} must not appear in committed "
            "evidence — re-run probe with --save-raw to a LOCAL path"
        )
    # No decimal-looking monetary values (defensive heuristic). A long
    # number with two decimal places strongly suggests a leaked amount.
    assert not re.search(r"\b\d{2,}\.\d{2}\b", text), (
        "decimal-formatted number in evidence — possible leaked "
        "monetary value; remove before committing"
    )


def test_evidence_file_records_a_real_probe_run():
    """Phase 10A.5 has run — the placeholder banner is gone, replaced
    with a real-probe evidence summary. This test pins the post-probe
    state so a future revert to placeholder content is loud."""
    text = EVIDENCE_PATH.read_text(encoding="utf-8")
    # Placeholder banner gone.
    assert "Status: NOT YET RUN" not in text
    # Probe output present.
    assert "Generated by `app.tools.probe_payments_and_invoice_payment_state`" in text
    # The first run was placeholder-driven and explicitly says so.
    # When a follow-up run with a real invoice id replaces it, the
    # "Run context" section is rewritten — but the run-context block
    # itself must remain so consumers know the evidence basis.
    assert "Run context" in text or "real invoice id" in text.lower()


# ── 5. Markdown renderer redaction (unit) ─────────────────────────────────

def test_render_evidence_markdown_includes_no_xml():
    """Synthetic report → rendered markdown → no XML fragments."""
    sample_report = {
        "invoice_get": {
            "endpoint":        "invoices/get",
            "filter":          "path-id=999",
            "accepted":        True,
            "wfirma_status":   "OK",
            "wfirma_message":  "OK",
            "http_status":     200,
            "fields_present":  {"fullnumber": True, "paymentstate": False},
            "leaf_tag_count":  3,
            "leaf_tag_sample": ["id", "fullnumber", "currency"],
            "conclusion":      "OK",
        },
        "payments_no_filter": {
            "endpoint":        "payments/find",
            "filter":          "no-filter",
            "accepted":        True,
            "wfirma_status":   "OK",
            "wfirma_message":  "OK",
            "http_status":     200,
            "payment_count":   0,
            "leaf_tag_sample": [],
            "first_payment_id": "",
            "conclusion":      "request accepted — zero payments returned",
        },
    }
    md = probe.render_evidence_markdown(sample_report)
    assert "<api>"     not in md
    assert "<invoice>" not in md
    assert "<payment>" not in md
    # Field-availability rows ARE in the rendered text — confirm the
    # presence-only contract.
    assert "fullnumber"   in md
    assert "paymentstate" in md


def test_render_evidence_no_payment_values_for_zero_count():
    """When zero payments are returned, the renderer must say so
    explicitly and NOT pretend fields exist."""
    sample_report = {
        "payments_no_filter": {
            "endpoint":        "payments/find",
            "filter":          "no-filter",
            "accepted":        True,
            "wfirma_status":   "OK",
            "wfirma_message":  "OK",
            "http_status":     200,
            "payment_count":   0,
            "leaf_tag_sample": [],
            "conclusion":      "request accepted — zero payments returned",
        },
    }
    md = probe.render_evidence_markdown(sample_report)
    assert "zero payments returned" in md
    # No leaf-tag block when there are no leaves.
    assert "Leaf tag inventory of first payment" not in md


# ── 6. CLI defaults are read-only ─────────────────────────────────────────

def test_main_help_runs_without_network(monkeypatch, capsys):
    """`-h` must work without any live wFirma call (no creds in CI)."""
    with pytest.raises(SystemExit) as exc:
        probe.main(["--help"])
    assert exc.value.code == 0


def test_skip_payments_flag_skips_payments_calls(monkeypatch):
    """`--skip-payments` short-circuits all payments/* probes — the
    spy below confirms no call lands."""
    called = {"n": 0}
    def _spy(*a, **kw):
        called["n"] += 1
        return 200, '<api><status><code>OK</code></status></api>'
    monkeypatch.setattr(
        "app.services.wfirma_client._http_request", _spy,
    )
    # No invoice_id either → no calls at all.
    rc = probe.main(["--skip-payments"])
    assert rc == 0
    assert called["n"] == 0
