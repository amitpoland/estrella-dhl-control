# Wave 3 + Wave 4 — Release Candidate Review Package (2026-07-05)

**Status:** RC prepared for operator review. **NOT deployed, NOT merged, NOT pushed.**
This is a review package only — no production action taken.

---

## 1. RC branch / commit

| Field | Value |
|---|---|
| RC branch | `feat/w4-item11-source-extraction` (carries all of Wave 3 + Wave 4) |
| RC HEAD | `10352a9b` (docs: Wave 4 closeout) |
| vs `origin/main` | **198 ahead / 15 behind** |
| Upstream push | **none** — branch is LOCAL-ONLY (no remote tracking) |
| Tracked WIP (uncommitted, NOT in RC) | `pz-api.js` (operator dedup WIP), 4 `.claude` skill files |
| Untracked | 33 temp/scratch files (scripts/tmp_*, dhl_* diag) — not part of RC |

> The branch name is historical; it is the accumulated Wave 3+4 line, not just Item 11.

## 2. Completed pages / items (DONE — safe reuse shipped)

**Wave 4 (this campaign):**
| Item | Surface | Commit |
|---|---|---|
| 1A | Accounting Overview KPIs (Sales Receivable per-currency, Last wFirma Sync) | `75f096eb` |
| 2  | Accounting Overview doc-count panels (Proforma count live; rest honest pending) | `ca30ed55` |
| 3A | Accounting Invoice + Credit Note grids (wFirma `invoices/find`) | `1094a9f9` |
| 4  | Accounting Client Balance roster | `4e0b58b3` |
| 7  | wFirma Sync PULL-ONLY slice (payments-pull + per-source cards) | `6835c642` |
| 8  | Proforma Import Packing List wizard (reuse `packing/{batch}/upload`) | `eef901eb` |
| 9  | Proforma list Print → existing detail flow | `4bd1dbe4` |
| 11 | Proforma Detail → Source & Extraction | `dd36cbf7` |
| 12 | Proforma Detail → Logistics | `8f708047` |
| 13 | Proforma Detail → Documents | `17ac9299` |
| 6  | Client Ledger — pre-existing reuse (not Wave-4 work) | — |

**Wave 3 (parity, on the same branch):** full HTML port of Accounting hub, Proforma
landing + detail tabs, Documents hub, Dashboard/Shipment census closure, CP3
recognition set. Plus `supplier-invoice-ocr` (`92de6112`, operator-gated OCR).

## 3. Gated items (STOP — UI visible + honest reason; no code shipped)

| Item / Ref | State | Reason |
|---|---|---|
| 10 — bulk Push/Send | STOP — operator approval | new bulk endpoint over per-draft write; partial-failure + bulk idempotency undesigned |
| 5 — Supplier Ledger / Supplier Payable | STOP — new authority | no Supplier Master / AP authority; source undocumented (SVT-class) |
| 3B — WZ/PW/RW/MM grids | STOP — undocumented / sandbox | SVT-1 recorded, awaiting operator approval to probe |
| I1-BP1 / I4-BP1 — due-date aging | STOP — sandbox | PHASE10A.5 payment-state probe; invoice-age shown + disclosed |
| I4-BP2 — Last 30d · I7-BP1 — stock-pull | Backend Pending rendered | no authority emits the figure / no persistence target (OI-10) |
| I7-CP4-1..4 — Customer/Product/Goods-edit/Invoice·Proforma push | CP4 — fiscal write gated | each behind `wfirma_create_*_allowed`, per-flag operator approval |

## 4. Test status

| Suite | Result |
|---|---|
| Root golden regression (`python test_pz_regression.py`) | **160/160 passed, 0 failed** |
| Service smoke (`pytest -m smoke`) | **63 passed, 1 skipped** |
| Wave 4 JSX transpile (`@babel/preset-react`, matches pinned 7.26.4) | proforma-detail / proforma-list / accounting-hub — **all OK** |
| Per-item V2 structural pins | green (no-spread-rest, design-baseline, authority contracts) |
| Known pre-existing reds (NOT introduced by Wave 4; reproduced at HEAD) | `test_print_uses_window_open`, `test_no_forbidden_endpoints_in_hub`, `test_pipeline_summary_panel_preserved`, `test_v2_prod_unauth_redirects_to_login` (env fixture) |

## 5. Composite (CP3) status

- CP3 side-by-side composites last regenerated at **`bff200e3`** (Wave 3 close):
  `reports/wave3/cp3/` (page pairs + authority comparisons + integrity audit).
- Wave 4 changed the rendered content of three surfaces — **proforma_detail**
  (Source/Logistics/Documents tabs), **proforma_search/list** (Print enabled),
  **accounting** (Overview doc-count). Their composites are therefore **STALE**.
- **Regeneration is a review-harness task, not done here:** the screenshot harness
  needs the authenticated review server + seeded drafts; the verify clone is behind
  session login with no seeded data (same barrier that blocked per-item GATE-6
  click-through). Not fabricated. **Not a deploy blocker** — code correctness was
  verified per item (transpile + served-200 + API-layer probes + green golden/smoke).

## 6. Deploy blockers (process gates — no code failures)

1. **Branch 15 behind `origin/main`** — needs `git pull --ff-only` / rebase reconciliation before any sync.
2. **Not merged to main** — RC is a feature branch; production deploys from main.
3. **Local-only (unpushed)** — a PR/review requires an operator-gated push first.
4. **7-agent deploy gate not run** — mandatory before any `C:\PZ` sync (per CLAUDE.md).
5. **Uncommitted tree WIP** — `pz-api.js` (operator) + 4 `.claude` skill files must be reconciled/excluded for a clean deploy.
6. **Stale Wave 4 composites** — regenerate on the authenticated review harness for full visual sign-off (review gate, not runtime).
7. **Full authenticated GATE-6 click-through** — Wave 4 tabs verified at transpile/served/API level; end-to-end browser walk pending on an authenticated instance.

## 7. Operator recognition checklist (Wave 4)

- [ ] Item 1A — Overview Sales Receivable (per-currency, never summed) + Last Sync render live
- [ ] Item 2 — Overview: Proforma count live; Invoices/CN/PZ/WZ/PW/RW/MM show honest `— · Backend Pending`
- [ ] Item 3A — Invoice + Credit Note grids load from wFirma; WZ/PW/RW/MM grids Backend Pending
- [ ] Item 4 — Client Balance roster (Open/YTD/Overdue-age); due-date + Last 30d disclosed as pending
- [ ] Item 7 — wFirma Sync: PULL cards active; PUSH section visible-but-disabled (CP4)
- [ ] Item 8 — Import Packing List wizard uploads → creates/syncs draft (real file, honest result)
- [ ] Item 9 — Proforma list Print enabled on single-select → opens detail Print/Preview; multi-select disabled with reason
- [ ] Item 11 — Proforma Detail Source & Extraction: per-row confidence + match + unmatched advisory
- [ ] Item 12 — Proforma Detail Logistics: carrier/route/CMR/pieces/weights; AWB+box Backend Pending
- [ ] Item 13 — Proforma Detail Documents: Proforma PDF / CMR / Packing / Invoice manifest with real actions
- [ ] No control removed/hidden vs wireframe; every gate shows a visible reason (Lesson M)

## 8. Deploy-readiness checklist

- [ ] Operator approves landing the RC (PR from `feat/w4-item11-source-extraction`)
- [ ] Reconcile `pz-api.js` operator dedup WIP (legitimate — see Item 11 note) + `.claude` skill WIP
- [ ] `git pull --ff-only origin main` to clear the 15-behind gap; resolve any conflict
- [ ] Push branch → open PR → GATE 1 (subagent verdicts, forbidden-files, regression)
- [ ] Regenerate Wave 4-affected CP3 composites on the authenticated review harness
- [ ] Full authenticated GATE-6 browser walk of the 10 Wave 4 surfaces
- [ ] Run the mandatory 7-agent deploy gate before any `C:\PZ` sync (never merge without it)
- [ ] Confirm no CP4 write flag flipped as a side-effect (pull-only slice proven no-push)

## 9. Next exact operator action

**Approve pushing `feat/w4-item11-source-extraction` and opening a PR to `main`** so
the RC enters GATE 1 review — OR, if landing the full 198-commit line at once is too
broad, instruct which slice(s) to carve into a smaller PR. Do **not** deploy or merge
until GATE 1 + the 7-agent deploy gate pass. The lowest-risk follow-on engineering
step (separate approval) remains **SVT-1**, the read-only warehouse-doc sandbox probe.
