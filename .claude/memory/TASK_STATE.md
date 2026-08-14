# TASK_STATE.md

## Current task

- **Task:** B-014 HARD CUTOVER — V1 Sales/Pro Forma entry → V2
- **Status:** `IN_PROGRESS` (implement → PR → 7-agent → App-deploy → RO verify → CLOSE)
- **Baseline prod/main start:** `cc8d6b30abb3d614f8cfca8f6451c09afe6bd427`
- **Branch:** `fix/b014-hard-cutover-v1-to-v2`
- **Scope:** `shipment-detail.html` navigation only — ProformaDraftPanel source retained
- **Do not:** delete V1 panel; widen permissions; touch routes_proforma / engine / wFirma
- **Verify:** GET/navigation/static only — no Reset/Re-open/Approve/Convert/wFirma writes
