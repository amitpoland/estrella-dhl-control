# Smoke report — Proforma preview / PDF commercial authority (PR #1128)

**Date:** 2026-08-08  
**Campaign:** fix/proforma-preview-pdf  
**Environment:** local validation (artifacts not retained in git)  
**Tester:** claude-session

## Coverage

| Check | Expected | Actual | Verdict |
|-------|----------|--------|---------|
| Focused pytest (preview PDF authority + origin + packing SR + related) | pass | 141 passed (pre-clean) | PASS |
| Pre-commit smoke | pass | 63 passed | PASS |
| Draft #76 Classic/Modern/Bold Print + Download | A4, SKUs present, payment clean | 33/33 SKUs; multi-page packer | PASS (local only) |
| Draft #83 short Classic/Modern Print + Download | A4, clean payment | pass | PASS (local only) |
| Origin for SKUs without Product Master country | honest `—` (no invented IN) | observed | PASS |

## Console / network

none recorded in unit harness; operator spot-check of Preview → Packing List still open on Draft #80.

## Artifacts left behind

Generated PDF/PNG binaries and live draft JSON fixtures were **not** committed (local-only). This markdown is the retained summary.

## Notes

- Commercial printable remains Proforma preview (Estrella sheet). Posted PDF stays wFirma `document.pdf`.
- No second Invoice V2 commercial PDF renderer.
- Deploy only after seven-agent gate.
