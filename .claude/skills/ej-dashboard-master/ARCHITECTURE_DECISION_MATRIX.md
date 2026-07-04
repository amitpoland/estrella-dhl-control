# EJ Dashboard — Architecture Decision Matrix (skill routing)

How `ej-dashboard-master` maps a classified request to the **minimum** skills, whether approval
is needed, and whether verification is required. The router activates only the matched row's
skills. `ui-ux-pro-max` is reference-only and is never counted as an activated authority.

## Decision matrix

| Task Type | Selected Skills (minimum) | Approval Required? | Verification Required? | Example |
|---|---|---|---|---|
| **Discussion** | none | No | No | "What's the cleanest way to structure the inbox page?" |
| **Question** | none | No | No | "Which file owns the dashboard route?" |
| **Planning** | none | No | No | "Let's outline the steps to add a reports export." |
| **Architecture Review** | none | No | No | "Review whether the accounting hub should own ledger state." |
| **Documentation** | none (domain skill only if it edits code) | No (unless code) | No (unless code) | "Explain the V2 routing model in a doc." |
| **Code Review** | `ej-dashboard-clean-code` | No | Read-only (no edits) | "Review this diff for scope creep." |
| **UI Implementation** | `frontend-design` + `ej-dashboard-design` | No (unless protected) | Yes — browser (`ej-dashboard-webapp-testing`) if visible | "Make the KPI cards more legible." |
| **Backend Implementation** | `ej-dashboard-fullstack-governance` + `ej-dashboard-clean-code` | If protected (§) | Yes — `make verify` + contract test | "Add `carrier_code` to the batches response." |
| **Full Stack Implementation** | design pair + `ej-dashboard-fullstack-governance` (+ `clean-code`) — the only >2 case | If protected (§) | Yes — `make verify` + browser | "Add `warehouse_note` end-to-end (UI + API + DB)." |
| **Refactoring** | `ej-dashboard-clean-code` + relevant domain skill | If protected (§) | Yes — `make verify` (golden unchanged) | "De-duplicate the status mappers." |
| **Browser Verification** | `ej-dashboard-webapp-testing` (only) | No | Yes — it IS the verification | "Check the proforma page still renders." |
| **Bug Investigation** | none to start (read-only) → +1 domain skill for the fix | If the fix is protected | Yes for the fix | "Find why the dashboard KPI count is wrong." |
| **Deployment** | none here — **7-agent deploy gate owns it** | Yes (deploy gate) | Yes (deploy gate) | "Ship the merged change to prod." |
| **Protected-domain** (financial, customs, accounting, inventory, shipment, document generation, API authority, persistence, business calc) | **STOP → approval**, then `ej-dashboard-fullstack-governance` (+ design skill if UI) | **Yes — always** | Yes — `make verify-full` where figures involved | "Recalculate the VAT total with a handling fee." |

## Minimum Skill Principle (reminder)

Never more than **two** activated skills unless the task genuinely spans domains (Full Stack).
Discussion / Question / Planning / Architecture Review load **none**. `ui-ux-pro-max` is reference
lookup, not an activated authority.

## Worked examples

- *"Make the dashboard KPI cards look cleaner."* → **UI Implementation** →
  `frontend-design` + `ej-dashboard-design`. No approval. Verify in browser. (2 skills.)
- *"Add `carrier_code` to `/api/v1/dashboard/batches`."* → **Backend** →
  `ej-dashboard-fullstack-governance` + `ej-dashboard-clean-code`. If it needs a new DB column →
  **persistence → approval first**. Verify `make verify` + response-shape test.
- *"De-duplicate the batch status mappers."* → **Refactoring** →
  `ej-dashboard-clean-code` + `ej-dashboard-design` (frontend JSX). Behavior-preserving; `make verify`.
- *"Check the proforma page still renders."* → **Browser Verification** →
  `ej-dashboard-webapp-testing` only. No edit skills.
- *"Should the accounting hub own ledger state?"* → **Architecture Review** → discussion only,
  **no implementation skills**, answered directly.
- *"Round the duty figure before display."* → **Protected (customs/financial)** → STOP, ask
  approval; route to `ej-dashboard-fullstack-governance`; never recompute outside `process_batch()`.
- *"Create `InventoryPageV2` next to the old one."* → **rejected** (duplicate authority) unless
  explicitly approved + a PROJECT_STATE DECISIONS entry; refactor in place instead.

## Anti-patterns (router rejects)

- Loading implementation skills for a discussion/planning/architecture-review request.
- Activating >2 skills for a single-domain task.
- Treating `ui-ux-pro-max` output as authoritative.
- Creating `*New`/`*Modern`/`*V2`/`*Next` parallel page/API/route/state/component/logic.
- Editing protected-domain logic before explicit approval.
- Skipping `/context` / planning from memory (non-discussion tasks).
