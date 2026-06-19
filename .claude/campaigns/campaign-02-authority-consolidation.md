# Campaign 02 — Authority Consolidation & Workflow Completion

**Status**: EXECUTING (verification + design phase started 2026-06-12)
**Operator brief**: received 2026-06-12 — authority, governance, reliability, workflow completion ONLY. No redesigns.
**Parent**: `.claude/campaigns/platform-remediation.md` (Phase 0 audit + backlog)
**Mission**: "Production-stable with bounded compliance debt" → "Authority-complete and production-ready."

---

## Scope mapping (operator brief → backlog)

| Campaign 02 item | Backlog ID | Notes |
|---|---|---|
| P0 Automated Backup Program | B7 | Operator elevated to P0 — lands FIRST so every later deploy has backup protection (deploy gate step 1 = "Backup verified") |
| P1 Lesson G Compliance | B1 **+ B4** | Operator's required outcome ("complete audit headers, complete lineage tracking, consistent audit behavior") spans BOTH download-header compliance (B1, Lesson G proper) AND the business-write audit-trail standard (B4). Both are in-scope; B1 ships first (small), B4 as its own PR. |
| P1 Lesson M Compliance | B2 | Bar raised by operator: EVERY disabled action shows reason + authority source + next required action — full sweep, not just the 3 known buttons |
| P1 Reservations Authority Decision | B3 | Binary: register+activate (A) or retire completely (B). Investigation produces decision package; operator picks; architect signoff mandatory |
| P2 Name Normalization Authority | B5 | `NameNormalizationService`, deprecate ×3 implementations, regression tests |
| P2 DHL Follow-up Authority | B6 | Single `FollowUpAuthority`: inputs (shipment/DHL/customs/DSK state) → waiting/eligible/blocked/completed; all DHL pages consume it |
| P3 AWB Pipeline Verification | (B19/B20 context) | Verify-only: backend route, DHL integration, address authority, label generation, tracking persistence |
| P3 Reservation Pipeline Verification | — | Verify-only: design_no mapping, product resolution, ambiguity handling, operator decision path |
| P3 Documents Lineage Review | B21 | Verify shipment/SAD/invoice/proforma/PZ linkage; close B21 |

**Explicitly deferred (operator)**: DHL workspace redesign, Customer Master redesign, Proforma UX
modernization, Inbox modernization, Shipment Detail redesign → Campaign 03.

---

## Execution constraints (binding)

- **GATE 2 queue FULL at campaign start**: #570, #568, #522 implementation + #498 draft.
  No new implementation PR opens until ≥1 clears. Locked queue order preserved:
  #568 merge+deploy → #570 → SHIPMENT_9938632830 recovery → #522 rebase → #498.
- **Branch strategy**: implementation prepared in dedicated git worktrees cut from
  `origin/main` (`ff1f4b5` — identical to `C:\PZ-verify` HEAD, eliminating source drift).
  Branches pushed; PRs open only when GATE 2 slots free, in the order below.
- **All verification reads**: `C:\PZ-verify` only (PATH GUARD).
- **Architect signoff**: required on B7/B1/B2 designs, mandatory on B3/B5/B6 — captured as
  written verdicts before implementation of each item.
- **Testing gates (operator)**: regression + authority + workflow tests pass, rollback tested,
  backup restore tested, architect signoff — before every merge.
- **Deploy gate (operator)**: backup verified → tests green → merge → deploy → browser smoke →
  workflow smoke → production verification → PROJECT_STATE update. Per PR. 7-agent gate applies.

## PR plan (open order as slots free)

| # | Branch | Content | Size |
|---|---|---|---|
| C02-PR1 | `feat/c02-b7-backup-program` | B7: backup service + retention + restore validation + pre-deploy hook + runbook + monitoring + tests | M |
| C02-PR2 | `fix/c02-compliance-lessong-lessonm` | B1 (Lesson G no-store headers, full sweep) + B2 (Lesson M reasons, full sweep) + regression tests | S |
| C02-PR3 | `feat/c02-b4-write-audit-standard` | B4: shared audit-write helper + adoption in document_db, packing_db, warehouse_db, tracking_db, master_data_db | M |
| C02-PR4 | `feat/c02-b5-name-normalization-authority` | B5: NameNormalizationService + migrate 3 call sites + regression tests | M |
| C02-PR5 | `feat/c02-b6-followup-authority` | B6: FollowUpAuthority + both engines consume it + integration test | M |
| C02-PR6 | `fix/c02-b3-reservations-<register|retire>` | B3 outcome after operator A/B decision | S |
| docs | rides docs-PR slot | campaign docs + verification reports (AWB, reservation pipeline, B21) under `docs/inspection/` | — |

## Success definition (operator)

B1, B2, B3, B5, B6, B7, B21 closed; AWB verified; Reservations verified; Restore verified.
Then → Campaign 03 (Professional UX & Operator Experience Modernization).

## Log

- 2026-06-12: Campaign opened. GATE 2 queue full — verification/design workflow launched;
  B7 + compliance implementation prepared on worktree branches pending queue slots.
