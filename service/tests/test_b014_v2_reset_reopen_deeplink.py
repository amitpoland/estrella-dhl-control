"""B-014 — V2 Reset ALL + re-open + Documents deep-link (Decision B).

Pins that V2 detail reuses the same canonical backend operations as V1
(re-open / reset-from-sales-packing) without a second authority, and that
Documents hub / legacy `?draft_id=` resolve to the shell's `?draft=` hydration.

No live wFirma / approve / post / convert / reset writes in these tests —
source-grep + existing HTTP lifecycle suite cover denied paths.
"""
from __future__ import annotations

from pathlib import Path

_V2 = Path(__file__).resolve().parent.parent / "app" / "static" / "v2"
_DETAIL = _V2 / "proforma-detail.jsx"
_API = _V2 / "pz-api.js"
_HUB = _V2 / "documents-hub.jsx"
_INDEX = _V2 / "index.html"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ── Transport (pz-api) — same tokens / endpoints as V1 ───────────────────────

class TestPzApiTransport:
    def test_reopen_uses_canonical_token_and_path(self):
        src = _read(_API)
        assert "reopenDraft:" in src
        assert "/proforma/draft/${draftId}/re-open" in src
        assert "YES_REOPEN_LOCAL_PROFORMA_DRAFT" in src

    def test_reset_accepts_reset_all_flag(self):
        src = _read(_API)
        assert "resetDraftFromSalesPacking:" in src
        assert "/proforma/draft/${draftId}/reset-from-sales-packing" in src
        assert "reset_all:" in src
        # Must not hardcode only false — Reset ALL needs !!resetAll
        assert "reset_all:           !!resetAll" in src or "reset_all: !!resetAll" in src


# ── V2 detail UI — Reset ALL + re-open ───────────────────────────────────────

class TestV2DetailResetReopen:
    def test_toolbar_testids_present(self):
        src = _read(_DETAIL)
        for tid in ("tb-reset-all", "tb-reset-lines", "tb-reopen"):
            assert f'data-testid="{tid}"' in src, f"missing {tid}"

    def test_reopen_prompt_gates_on_v1_token(self):
        src = _read(_DETAIL)
        assert "YES_REOPEN_LOCAL_PROFORMA_DRAFT" in src
        assert "window.prompt(" in src
        assert "token mismatch" in src
        assert "PzApi.reopenDraft" in src

    def test_reopen_only_when_approved(self):
        """Positive gate matches pildb.REOPENABLE_STATES — approved only."""
        src = _read(_DETAIL)
        assert "const canReopen     = draftState === 'approved'" in src or \
               "canReopen     = draftState === 'approved'" in src

    def test_reset_all_confirm_and_true_flag(self):
        src = _read(_DETAIL)
        assert "RESET ALL: replace lines AND wipe buyer" in src
        assert "resetDraftFromSalesPacking(id, updatedAt, true)" in src

    def test_reset_lines_confirm_and_false_flag(self):
        src = _read(_DETAIL)
        assert "CURRENT EDITABLE LINES WILL BE REPLACED" in src
        assert "resetDraftFromSalesPacking(id, updatedAt, false)" in src

    def test_reset_gated_on_can_edit(self):
        """Denied path: buttons only render under canEdit (draft/editing/post_failed)."""
        src = _read(_DETAIL)
        # Both reset buttons sit inside {canEdit && (...)}
        assert 'data-testid="tb-reset-all"' in src
        idx = src.index('data-testid="tb-reset-all"')
        window = src[max(0, idx - 400):idx]
        assert "canEdit" in window

    def test_no_second_reset_authority(self):
        src = _read(_DETAIL)
        # Must go via PzApi transport — no ad-hoc fetch to a parallel reset path
        assert "PzApi.resetDraftFromSalesPacking" in src
        assert "PzApi.reopenDraft" in src
        assert "fetch(" not in src.split("handleResetAll")[1][:800] if "handleResetAll" in src else True
        assert "/api/v1/proforma/draft/" not in src or "PzApi." in src


# ── Documents deep-link ──────────────────────────────────────────────────────

class TestDocumentsDeepLink:
    def test_hub_edit_uses_proforma_detail_draft_param(self):
        src = _read(_HUB)
        assert "/v2/proforma_detail?draft=${draft.id}" in src
        assert "/v2/proforma?draft_id=" not in src

    def test_hub_unapprove_calls_reopen_with_updated_at(self):
        """Denied/broken path fix: do not pass a body object as updatedAt."""
        src = _read(_HUB)
        assert "PzApi.reopenDraft(draft.id, draft.updated_at" in src

    def test_shell_accepts_draft_id_alias(self):
        src = _read(_INDEX)
        assert "sp.get('draft') || sp.get('draft_id')" in src


# ── Wireframe list must include new toolbar pins ─────────────────────────────

class TestWireframeToolbarListUpdated:
    def test_primitives_list_includes_b014_testids(self):
        """Keep slice-2 behavior surface list in sync (additive only)."""
        from pathlib import Path as P
        wire = (
            P(__file__).resolve().parent / "test_proforma_wireframe_primitives.py"
        ).read_text(encoding="utf-8")
        for tid in ("tb-reset-all", "tb-reset-lines", "tb-reopen"):
            assert tid in wire, (
                f"add {tid!r} to TOOLBAR_TESTIDS in "
                "test_proforma_wireframe_primitives.py"
            )
