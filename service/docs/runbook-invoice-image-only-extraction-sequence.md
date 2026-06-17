# Runbook — Image-Only Invoice Recovery: Implementation & Deployment Sequence

**Owner:** Amit (operator) · **Authored:** 2026-06-17
**Governs:** ADR-030 (authority separation) · PR #640 (recovery layer) · PR-2 (confirmation workflow)
**Scope:** the permanent path by which an image-only commercial invoice becomes a PZ + wFirma goods receipt — for AWB 2315714531 and every future image-only shipment.

---

## 1. Why this exact order

> **PR #640 (advisory recovery, no accounting authority) → deploy → PR-2 (operator confirmation workflow) → deploy → re-run shipment recovery.**

This order is mandatory, not stylistic. It is the Lesson I rule applied: fix the
**workflow class** (every image-only invoice), never the **shipment**
(AWB 2315714531 only).

- **PR #640 ships the proposal layer with zero accounting authority.** It can be
  deployed safely *today* because nothing reads `vision_invoice` into PZ, wFirma,
  landed cost, or customs (ADR-030 enforcement rule, pinned by
  `test_vision_invoice_negative_scope.py`). Deploying it early lets real
  image-only invoices accumulate **reviewable proposals** in production while the
  confirmation UI is still being built — no risk, immediate diagnostic value.
- **PR-2 adds the human write-gate before any injection exists.** If the order
  were reversed — injection first, confirmation second — there would be a window
  where machine-extracted invoice data could reach the engine without human
  attestation. That window is exactly the audit problem this campaign exists to
  prevent: a wrong OCR line booked as a goods receipt with full audit-trail
  credibility, posted to wFirma, feeding landed cost. The gate must exist
  **before** the door.
- **Re-running recovery last** means AWB 2315714531 flows through the *same*
  permanent path every future shipment uses. No shipment-specific code, no
  one-off manual re-key, no exception branch. If the path works for this AWB it
  works for all of them.

**Audit-safety consequence:** at no point does an unconfirmed proposal become
accounting or customs truth. Every booked PZ line is traceable to a human
`operator_confirmed = true` event.

---

## 2. The permanent data flow (image-only invoice)

```
  Upload / Recheck
        │
        ▼
  Engine parse (process_batch)         ← layer 3 owner
        │
        ├─ text parsed OK ─────────────► rows + invoice_totals present → PZ preview → wFirma   (normal path; #640 no-ops)
        │
        └─ parse failed / incomplete    (image-only: rows=[], total_fob_usd=0)
                │
                ▼
        Vision extraction PROPOSAL       ← layer 1 owner: run_image_only_invoice_extraction
        audit["vision_invoice"]          (supplier, fob_usd[USD-only], line_items, confidence,
                │                          operator_confirmed=false)
                ▼
        Operator review  (PR-2 UI)       ← layer 2: visible, disabled until backend exists (Lesson M)
                │
                ▼
        Operator CONFIRM (PR-2 endpoint) ← sets operator_confirmed=true (sole writer)
                │
                ▼
        Engine consumes confirmed proposal (PR-2 injection, gated on operator_confirmed==true)
                │
                ▼
        process_batch recomputes → rows + invoice_totals   ← layer 3 (accounting authority)
                │
                ▼
        PZ preview  ──────────────────►  wFirma goods receipt
```

Customs (layer 4: `clearance_decision` / `resolve_cif`) runs on its own ladder
throughout and never touches any box in this diagram. For AWB 2315714531 customs
is already RESOLVED (CIF 732) and stays healthy regardless of invoice recovery.

---

## 3. Stage-by-stage gates — which system is blocked when

| Stage | After PR #640 (now) | After PR-2 | Gate enforcing it |
|---|---|---|---|
| Vision proposal write | ✅ enabled (advisory) | ✅ enabled | confidence ≥ `MIN_WRITE_CONFIDENCE`, image-only, engine-not-parsed |
| Operator review UI | 🔒 **visible + disabled**, reason: "Confirmation workflow ships in PR-2" (Lesson M) | ✅ enabled | frontend disabled-reason string + `BACKEND_GAP_REGISTER` |
| Operator confirm | 🚫 not present | ✅ enabled (explicit action) | PR-2 endpoint = sole writer of `operator_confirmed` |
| Engine injection | 🚫 **intentionally absent** | ✅ gated | injection reads proposal ONLY if `operator_confirmed == true` |
| **PZ generation** | 🚫 **blocked** (layer 3 empty — not computable) | ✅ once confirmed→injected→recomputed | `routes_pz` / `export_service` read layer 3 only |
| **wFirma posting** | 🚫 **blocked** | ✅ once PZ exists | `routes_wfirma` reads layer 3 only; never `vision_invoice` |
| Customs / CIF | ✅ unaffected (RESOLVED 732) | ✅ unaffected | `cif_resolver` ladder; `vision_invoice` not in ladder |

PZ and wFirma are blocked **by design** after #640 — not by a bug. The block is
"layer 3 is empty and there is no confirmed path to fill it yet." That is the
correct, honest state until PR-2 exists.

---

## 4. Execution checklist

### Stage A — PR #640 (recovery layer)
- [x] Implementation complete, reviewer-challenge PASS (commit `f6c7ec2`), PR #640 open.
- [x] Authority isolation pinned (`test_vision_invoice_negative_scope.py`).
- [x] Baseline: PZ 221, Carrier 420 ≥ 412; smoke 63.
- [ ] **Operator review + merge PR #640** (GATE 1 satisfied; GATE 2 = 2 impl + 1 docs).
- [ ] **7-agent deploy gate** (`/deploy`) — backend-only change, no schema, no forbidden paths; standard `service/app → C:\PZ\app` robocopy (no root-engine file involved → Lesson J N/A here).
- [ ] Post-deploy verify: on a real image-only invoice, confirm `audit["vision_invoice"]` is written with `operator_confirmed=false` and that `rows` / `invoice_totals` / `clearance_decision` / CIF are byte-unchanged.

### Stage B — PR-2 (confirmation workflow)
- [ ] Lifecycle state for the proposal (proposed → confirmed → injected).
- [ ] Operator-confirm endpoint — sole writer of `operator_confirmed=true`; explicit action, no auto-confirm/confirm-on-mount.
- [ ] Visible **enabled** "Confirm extracted invoice" control replacing the disabled placeholder (Lesson M five-state truth model: planned → available).
- [ ] Gated injection step into `process_batch()` inputs (reads proposal only when confirmed).
- [ ] Supplier cross-validation against contractor/customer master.
- [ ] Resolve **Issue #638** (dedicated quantity coercion, not `_coerce_money`) and **Issue #639** (0.49/0.51 confidence boundary test) — both must close before injection wiring.
- [ ] Tests: poison-block invariance for the PZ input-builder + wFirma payload builder; positive source-contract (injection is the only non-extractor reader of `vision_invoice`, on the same path as `operator_confirmed`); confirm-gate test.
- [ ] Reviewer-challenge + baseline + 7-agent deploy gate.

### Stage C — Re-run shipment recovery (AWB 2315714531)
- [ ] Recheck/recovery on the AWB through the deployed permanent path.
- [ ] Operator reviews the proposal, confirms.
- [ ] Engine recomputes → **PZ preview (read-only) first**, inspect lines/FOB/supplier.
- [ ] Only then PZ create → wFirma post (operator-gated writes per "prod write is operator-only").

---

## 5. Production-safety flags raised

- **Duplicate `fob_usd`** lives in both `vision_invoice` (layer 1) and
  `invoice_totals` (layer 3). Safe today (no shared consumer). PR-2 must read
  layer 3, or layer 1 strictly behind `operator_confirmed` — never
  "whichever exists." Tracked in ADR-030 Risks.
- **`operator_confirmed` must have exactly one writer** (the PR-2 endpoint). Any
  second writer is an authority-forge risk; add a static contract if a second
  candidate path appears.
- **Do not let delivery pressure collapse Stage A and Stage B into one PR.** A
  combined PR would briefly create an injection path before the confirm gate is
  proven — the precise audit hole this sequence prevents.
