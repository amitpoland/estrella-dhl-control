# AR baseline lock — 2026-08-17 (pre Slice-2 semantics change)

**Production SHA:** `2f04ae1c20ae17cfa72765df76ea3db59268f415`  
**Aligned:** `C:\PZ\version.txt` = `C:\PZ-main` = `origin/main` = campaign worktree base  
**Measured at (UTC):** see `baseline-ar-2026-08-17.json`  
**Endpoint:** `GET /api/v1/ledgers/management-analysis.json?scope=all_outstanding&refresh=1`  
**Mode:** READ-ONLY

## Locked totals (current live MA, pre as-of correction)

| Ccy | Total receivable | Overdue | Not due | Credits | Customers outstanding | Oldest overdue (days) |
|-----|------------------|---------|---------|---------|----------------------|------------------------|
| USD | 373,062.49 | 280,798.80 | 92,263.69 | 170,204.80 | 25 | 2029 |
| EUR | 212,383.49 | 39,826.04 | 172,557.45 | 14,584.41 | 10 | 685 |
| PLN | 96,077.65 | 18,002.90 | 78,074.75 | 31,296.79 | 1 | 33 |

These match the Stage A pre-Stage-B lock figures exactly.

## Performance (this measure)

- MA `all_outstanding` refresh: cold wFirma waterfall (see JSON `query_stats`)
- Client Balance default quarter refresh: ~2.7s wall / ~2.6s wFirma wait (narrow activity window — known understated vs position-as-of)

## Aging keys on this baseline (pre-canonical)

MA still uses legacy merged buckets: `not_due`, `b_1_30`, `b_31_90`, `b_91_180`, `b_180_plus`, `due_date_unavailable`.

## Slice 0 (WZ)

- Target: `warehouse_document_w_z/get/197253795` (WZ 12/8/2026)
- **Classification: DIRECT JOIN** via top-level `invoice/id = 498723555`
- contractor_id present on get; parent=0; documents empty
- Evidence: `slice0-wz-probe-197253795.json`

## Do not treat post–Slice-2 AR increases as regressions

As-of settlement will surface previously omitted valid open positions when activity-window payments are restored. Reconcile with before/after report.
