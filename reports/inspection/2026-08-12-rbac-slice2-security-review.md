# RBAC Slice 2 — Security review (2c / 2d / 2e) before binding

**Date:** 2026-08-12  
**Tree:** `C:\PZ-main` @ `19d9b41645c35bbcf8eba02bfe60799a1b822b0d` (`feat/rbac-slice-2`)  
**Review type:** Charter §12 mandatory domain security review (classification + bind map)  
**Mutation in this document:** none (evidence only; bindings follow in same PR wave)

Continuity: R-1 closed @ `0dc647af`; PR #1200 holds Slice 2b.

---

## 1. Verdict

| Domain | SAFE_TO_BIND | HOLD (individual) | Action |
|---|---|---|---|
| **2c** DHL/AWB | 19 | 1 (`return/create` stub) | Stack `require_permission` on existing `require_role` / `require_admin` |
| **2d** fiscal + prepare | 28 | ~14 mixed-class | Bind single-class fiscal deny (logistics) + prepare; HOLD mixed |
| **2e** inventory | 12 | 2 | Bind execute/correct/warehouse; HOLD recon + lifecycle ownership |

**This review is a checkpoint, not a campaign HOLD.** Implementation continues for SAFE_TO_BIND rows.

**No widening:** Logistics must not receive `FISCAL_FINALIZE_PERMISSIONS`. Current `require_api_key_privileged` still allows logistics on approve/convert — 2d **tightens**.

**API-key rule:** Where today `require_role` blocks key-alone, keep that role gate. Do not replace role+key stacks with `require_permission` alone (would widen key-alone to machine-admin).

---

## 2. Binding patterns (frozen for this PR)

1. **DHL execute / AWB (role-gated today):**  
   `dependencies=[_auth, _op_auth, Depends(require_permission("<verb>"))]`  
   Keep `_op_auth = require_role("admin","logistics")`.

2. **DHL resolve (admin today):**  
   Compose like 2b: `require_admin` + `require_permission("dhl.resolve")`.

3. **Automation schedulers (api_key only today):**  
   `dependencies=[_auth, Depends(require_permission("system.automation.execute"))]`.

4. **Fiscal privileged / api_key-only:**  
   Stack `Depends(require_permission("<fiscal verb>"))` on existing auth. Session logistics loses finalize; key remains documented machine break-glass via `require_permission`.

5. **HOLD:** Do not bind mixed-class routes in this wave (listed below).

---

## 3. 2c SAFE map (summary)

| Permission | Routes (representative) |
|---|---|
| `dhl.execute` | match-and-handle, generate-description/package, send-reply, approve, mark-email-received, proactive-dispatch, dhl-documents received/upload |
| `dhl.resolve` | logistics resolve / reopen |
| `awb.create` | POST carrier `/{batch}/shipment` |
| `awb.label` | label-package, do-not-use |
| `awb.docs_fetch` | waybill-doc/fetch, epod/fetch |
| `shipments.edit` | return/prepare, return PATCH |
| `system.automation.execute` | scheduled-inbox-check, scheduled-followup-check |

**HOLD:** `POST .../return/create` — capability stub; no live verb.

---

## 4. 2d SAFE map (summary) — C2 critical

| Permission | Must deny logistics | Routes |
|---|---|---|
| `proforma.approve` | YES | draft approve, draft post |
| `proforma.convert` | YES | to-invoice (batch + draft) |
| `pz.finalize` | YES | set_pz, pz_adopt, pz_confirm |
| `pz.export_wfirma` | YES | pz_create, clear-mapping, correction-push, correction-commit |
| `pz.process` | NO (logistics OK) | upload process, pz process/_legacy |
| `pz.prepare` | NO | correction-execute/stage/suppress |
| `proforma.edit` | NO | draft PATCH family (single-class edits) |
| `proforma.delete` | admin only | draft delete/cancel |
| `wfirma.goods.write` | YES (logistics denied in catalogue) | goods create/adopt/auto-register family |
| `wfirma.customers.write` | YES | auto-create-from-name; sync apply (keep admin) |
| `wfirma.reservation.create` | YES | reservations create / reset-stuck |

**HOLD (examples):** live `POST /proforma/create`, adopt-issued, cancel-issued-for-reissue, confirm-wfirma-link, products/resolve (RO+write), service-products PUT, send-email, invoice-links reconcile, local customer/product PUT mapping family.

---

## 5. 2e SAFE map (summary)

| Permission | Notes |
|---|---|
| `inventory.execute` | location, sample, returns, qc-disposition |
| `inventory.correct` | identity / archive-proposal / reversal — **admin only** (strips logistics) |
| `warehouse.scan` | scan + locations upsert |
| `warehouse.receipt.confirm` | receipt confirm |

**HOLD:** fiscal-reconciliation/run (wrong class); inventory-state mark-direct-dispatch (ownership).

---

## 6. First code change after this review

`routes_dhl_clearance.py` — add `_perm_exec = Depends(require_permission("dhl.execute"))` next to `_op_auth` (~L72); attach to POST `/match-and-handle` and remaining execute mutations.

---

## 7. Explorer peer

Classification produced by explore agent `[Slice 2 Tier-0 security map](a184547b-cf8a-4f5c-b18b-2e5e4e3a6f52)` against HEAD `19d9b416`; this file is the durable evidence record.
