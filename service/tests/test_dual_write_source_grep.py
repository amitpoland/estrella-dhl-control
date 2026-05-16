"""Phase 6F.5 — source-grep contracts for dual-write helper + hook site.

Pins the architectural rules mechanically. Any future edit that breaks
one of these contracts FAILS this test before reaching production.

Contracts pinned:
  - Two feature flags exist in config.py with default=False.
  - The hook fires AFTER mark_post_succeeded in routes_proforma.py.
  - The flag check appears textually BEFORE the dual_write call site.
  - The dual-write helper does NOT import wFirma / FX / settlement modules.
  - The dual-write helper uses Decimal arithmetic, not int(x*100).
  - No write SQL against proforma_service_charges in the helper.
  - The helper file has the LIVE- prefix and [live:sha1= prefix constants.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


_REPO     = Path(__file__).resolve().parents[2]
_CONFIG   = _REPO / "service" / "app" / "core" / "config.py"
_HELPER   = _REPO / "service" / "app" / "services" / "finance_dual_write.py"
_ROUTE    = _REPO / "service" / "app" / "api" / "routes_proforma.py"


def _strip_docstrings_and_comments(text: str) -> str:
    """Remove triple-quoted strings and ``# ...`` comments.

    The dual-write helper's docstring contains the literal text of the
    forbidden patterns it WARNS against (e.g. ``int(amount * 100)``).
    Source-grep contracts must inspect executable code only, not commentary
    about what NOT to do.
    """
    # Remove triple-quoted strings (both """ and ''').
    text = re.sub(r'"""[\s\S]*?"""', '', text)
    text = re.sub(r"'''[\s\S]*?'''", '', text)
    # Remove line comments.
    text = re.sub(r"(?m)#.*$", '', text)
    return text


# ── Feature flag contracts ───────────────────────────────────────────────────

def test_two_feature_flags_exist_with_default_false():
    if not _CONFIG.exists():
        pytest.skip("config.py missing")
    text = _CONFIG.read_text(encoding="utf-8")
    # Pattern requires both flag name AND default=False on the same line.
    assert re.search(
        r'finance_dual_write_enabled\s*:\s*bool\s*=\s*Field\(\s*default\s*=\s*False',
        text,
    ), "FINANCE_DUAL_WRITE_ENABLED must default to False in config.py"
    assert re.search(
        r'finance_dual_write_shadow\s*:\s*bool\s*=\s*Field\(\s*default\s*=\s*False',
        text,
    ), "FINANCE_DUAL_WRITE_SHADOW must default to False in config.py"


def test_flag_env_var_names_are_canonical():
    text = _CONFIG.read_text(encoding="utf-8")
    assert 'env="FINANCE_DUAL_WRITE_ENABLED"' in text
    assert 'env="FINANCE_DUAL_WRITE_SHADOW"' in text


# ── Hook site contracts ──────────────────────────────────────────────────────

def test_hook_fires_after_mark_post_succeeded():
    """The dual_write_proforma_post call site appears AFTER mark_post_succeeded."""
    text = _ROUTE.read_text(encoding="utf-8")
    idx_mark = text.find("pildb.mark_post_succeeded")
    idx_hook = text.find("dual_write_proforma_post")
    assert idx_mark >= 0, "mark_post_succeeded call missing in routes_proforma"
    assert idx_hook >= 0, "dual_write_proforma_post hook missing in routes_proforma"
    assert idx_hook > idx_mark, (
        "Hook must appear textually AFTER mark_post_succeeded; "
        f"found mark at {idx_mark} and hook at {idx_hook}"
    )


def test_flag_check_precedes_dual_write_call():
    """settings.finance_dual_write_enabled appears BEFORE the call site."""
    text = _ROUTE.read_text(encoding="utf-8")
    # Find the call site
    idx_call = text.find("dual_write_proforma_post(")
    assert idx_call >= 0
    # Find the flag check before it (within ~600 chars window above)
    window = text[max(0, idx_call - 600): idx_call]
    assert "settings.finance_dual_write_enabled" in window, (
        "Flag check must guard the dual_write_proforma_post call site"
    )


def test_hook_wrapped_in_try_except():
    """Hook must be wrapped in try/except so an unexpected exception is logged."""
    text = _ROUTE.read_text(encoding="utf-8")
    idx_call = text.find("dual_write_proforma_post(")
    assert idx_call >= 0
    # Hook spans multiple lines (the call is multi-arg). Widen the window
    # generously — the try/except brackets the entire block.
    window = text[max(0, idx_call - 600): idx_call + 1200]
    assert "try:" in window, "Dual-write hook must be wrapped in try:"
    assert "except Exception" in window, (
        "Dual-write hook must catch Exception (defense in depth — helper "
        "already catches internally, but the call itself must also be guarded)"
    )


def test_hook_appears_before_audit_append():
    """Hook fires BEFORE the post-issuance audit append in post_proforma_draft_to_wfirma.

    Note: ``record_proforma_issued`` appears elsewhere in routes_proforma.py
    (e.g. in approval / re-issue paths). We scan forward FROM the hook for
    the next reference, which by construction is the audit block immediately
    following the hook inside post_proforma_draft_to_wfirma.
    """
    text = _ROUTE.read_text(encoding="utf-8")
    idx_hook  = text.find("dual_write_proforma_post(")
    assert idx_hook >= 0
    idx_audit_after = text.find("record_proforma_issued", idx_hook)
    assert idx_audit_after >= 0, (
        "Expected a record_proforma_issued audit block after the hook"
    )
    # The audit block must follow within a small window — the hook and
    # the audit append live in the same function.
    assert idx_audit_after - idx_hook < 2000, (
        "Audit append should follow the hook closely within the same route function"
    )


# ── Helper-file contracts ────────────────────────────────────────────────────

def test_helper_does_not_import_wfirma_or_fx_or_settlement():
    text = _strip_docstrings_and_comments(_HELPER.read_text(encoding="utf-8")).lower()
    forbidden_imports = [
        # wFirma write surfaces
        "from ..services.wfirma",
        "from .wfirma",
        "import wfirma_client",
        # FX
        "from ..services.fx",
        "import fx_",
        # PZ landed-cost
        "from ..engine.landed_cost",
        "import landed_cost",
        "from ..services.golden_constants",
        # Settlement-close
        "settlement_close",
        # Proforma engines / legacy DB
        "proforma_service_charges_db",
        "proforma_pz_",
    ]
    hits = [tok for tok in forbidden_imports if tok in text]
    assert hits == [], (
        f"finance_dual_write.py contains forbidden imports/symbols: {hits}"
    )


def test_helper_uses_decimal_for_amount_conversion():
    raw = _HELPER.read_text(encoding="utf-8")
    # These imports/identifiers are looked up in the raw text since they
    # legitimately may also appear in docstrings — we just need them present.
    assert "from decimal import Decimal" in raw, (
        "finance_dual_write.py must import Decimal"
    )
    assert "ROUND_HALF_EVEN" in raw, (
        "finance_dual_write.py must use ROUND_HALF_EVEN for amount conversion"
    )
    # Forbid naive int(x*100) outside Decimal context — but only check
    # executable code, not docstrings/comments that describe the forbidden
    # pattern.
    code_only = _strip_docstrings_and_comments(raw)
    bad = re.findall(r"int\s*\(\s*amount\s*\*\s*100", code_only)
    assert bad == [], f"Forbidden naive int(amount*100) in executable code: {bad}"


def test_helper_namespaces_disjoint_from_backfill():
    """LIVE- and [live:sha1= constants exist; helper does not WRITE BACKFILL-."""
    raw = _HELPER.read_text(encoding="utf-8")
    assert 'POSTING_LIVE_PREFIX = "LIVE-"' in raw
    assert 'CHARGES_LIVE_NOTE_PREFIX = "[live:sha1="' in raw
    # Helper code must not produce BACKFILL- postings (e.g. as a literal
    # string passed to create_posting). Docstring mentions are allowed.
    code_only = _strip_docstrings_and_comments(raw)
    # Forbidden: any literal "BACKFILL-" string in executable code.
    assert "BACKFILL-" not in code_only, (
        "Executable code in finance_dual_write.py must not produce BACKFILL- postings"
    )


def test_helper_function_never_raises_signature_contract():
    """The public function must catch Exception at the outermost layer."""
    text = _HELPER.read_text(encoding="utf-8")
    # Find the def line
    idx = text.find("def dual_write_proforma_post(")
    assert idx >= 0
    body = text[idx:]
    # The body must contain a top-level try/except Exception.
    assert "except Exception" in body, (
        "dual_write_proforma_post must catch Exception at the outermost layer"
    )


def test_helper_returns_dict_not_raises_on_garbage():
    """Static check: there is no `raise` of an uncaught exception in the helper.

    We accept `raise` only inside test/comment lines (none expected). Any
    `raise <Type>` statement must live inside a function the outer try/except
    catches.
    """
    text = _HELPER.read_text(encoding="utf-8")
    # The helper never re-raises — find any `\n    raise ` occurrence outside
    # of comments. Allow `raise` in docstrings/comments only.
    raise_lines = [
        ln for ln in text.splitlines()
        if re.match(r"\s+raise\s", ln) and not ln.strip().startswith("#")
    ]
    # Permitted: zero raise statements in production code paths.
    assert raise_lines == [], (
        f"finance_dual_write.py must not raise; found: {raise_lines}"
    )


# ── Hook-call argument shape contract ────────────────────────────────────────

def test_hook_passes_all_keyword_args():
    """Hook must invoke the helper with keyword args matching the signature."""
    text = _ROUTE.read_text(encoding="utf-8")
    # Pull out the chunk from `dual_write_proforma_post(` to the matching `)`.
    idx = text.find("dual_write_proforma_post(")
    assert idx >= 0
    # 600 chars is plenty for the call.
    chunk = text[idx: idx + 1200]
    for kw in (
        "db_path",
        "batch_id",
        "client_name",
        "currency",
        "full_number",
        "service_charges_json",
        "enabled",
        "shadow",
    ):
        assert f"{kw} " in chunk or f"{kw}=" in chunk, (
            f"dual_write_proforma_post call must pass {kw} explicitly"
        )
