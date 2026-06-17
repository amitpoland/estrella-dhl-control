# Handoff — AWB 2315714531 Invoice Extraction & PZ Unblock

**Owner:** Amit (operator) · **Authored:** 2026-06-17
**Governs:** ADR-031 (authority separation) · PR #640 (recovery layer) · PR-2 (confirmation workflow)
**Related runbook:** `runbook-invoice-image-only-extraction-sequence.md`

This is the single-page truth for "where is AWB 2315714531 right now, and what
happens next." It is deliberately honest about what is blocked **by design**
versus blocked **by a bug** — they are not the same and must not be conflated.

---

## 1. One-paragraph status

AWB 2315714531 is **customs-cleared and customs-healthy**, but **not
purchase-accounting-ready**. Its commercial invoice arrived as an image-only
scan, which defeats the text parser: `process_batch()` receives FOB=0, zero line
items, and no supplier — so no PZ (goods receipt) is computable and nothing can
post to wFirma. Customs was resolved on its **own** authority ladder (CIF USD
732, via the deployed #632/#633 vision **CIF** fallback) and is unaffected by the
invoice problem. The fix is a permanent, workflow-class one (an advisory
extraction layer + an operator-confirmation gate), not a manual re-key of this
one shipment.

---

## 2. What is true today (FACTS)

| Item | State | Evidence |
|---|---|---|
| Customs / CIF | ✅ **RESOLVED — CIF USD 732** | `resolve_cif(audit)` → `RESOLVED`, source `awb_customs.value_usd`; #632/#633 deployed + verified |
| Customs ladder isolation | ✅ healthy | `vision_invoice` not in CIF ladder; pinned by `test_vision_invoice_negative_scope.py` |
| Commercial invoice | ⚠️ **image-only** | text parser yields rows=[], `invoice_totals.total_fob_usd`=0 |
| Engine accounting (layer 3) | 🚫 **empty** (not computable) | no rows, no positive FOB → `process_batch()` cannot build PZ |
| Advisory recovery layer | 🟡 **built, in PR #640 (HEAD `f6c7ec2`)** | `run_image_only_invoice_extraction` → `audit["vision_invoice"]`; reviewer PASS |
| Accounting authority for the proposal | 🚫 **intentionally NOT granted** | `operator_confirmed=false`; no engine injection exists yet |
| PZ generation | 🚫 **blocked (by design)** | layer 3 empty; no confirmed path to fill it until PR-2 |
| wFirma posting | 🚫 **blocked (by design)** | reads layer 3 only; layer 3 empty |

**Blocked-by-design, not by bug.** PZ and wFirma are blocked because the only
thing that could fill the accounting layer for this shipment is an *unconfirmed
machine proposal*, and ADR-031 forbids that proposal from becoming accounting
authority without an operator confirmation that does not exist yet. That is the
correct, honest state — not a regression.

---

## 3. What PR #640 changes (and what it deliberately does NOT)

**Does:** adds an advisory `vision_invoice` proposal (supplier, USD-only FOB,
line items, confidence, `operator_confirmed=false`) when — and only when — the
engine has not parsed, the document is image-only, and confidence ≥
`MIN_WRITE_CONFIDENCE`. Sticky on confirmation, TOCTOU-guarded, USD-only.

**Does NOT:** touch CIF keys, `invoice_totals`, `rows`, `customs_declaration`, or
any wFirma/PZ/landed-cost path. `process_batch()` is never called from the
extractor (only referenced in comments). No accounting or customs consumer reads
`vision_invoice` — pinned by the negative-scope source contracts.

Net effect for AWB 2315714531 after #640 deploys: a **reviewable proposal**
appears in the audit. PZ/wFirma stay blocked. Nothing is booked.

---

## 4. What happens next (sequence)

Per the runbook (`runbook-invoice-image-only-extraction-sequence.md` §1), the
mandatory order is:

1. **Operator reviews + merges PR #640** (GATE 1 satisfied; queue within GATE 2).
2. **7-agent `/deploy` gate** → deploy #640 (backend-only, no schema, no
   forbidden/root-engine paths → Lesson J N/A). Operator-only prod write.
3. **Post-deploy verify** on a real image-only invoice: `vision_invoice` written
   with `operator_confirmed=false`; `rows`/`invoice_totals`/`clearance_decision`/
   CIF byte-unchanged.
4. **PR-2 — confirmation workflow** (separate PR): lifecycle state, operator-
   confirm endpoint (sole writer of `operator_confirmed=true`), visible+enabled
   confirm control (Lesson M), **gated** engine injection (reads proposal only
   when confirmed), supplier cross-validation. Resolve **Issue #638** (quantity
   coercion) and **Issue #639** (confidence-boundary test) before injection wiring.
5. **Deploy PR-2** through the 7-agent gate.
6. **Re-run recovery on AWB 2315714531** through the deployed permanent path:
   operator reviews the proposal → confirms → engine recomputes → **PZ preview
   (read-only) first**, inspect lines/FOB/supplier → only then PZ create → wFirma
   post (operator-gated writes).

Stages must **not** be collapsed: a combined #640+PR-2 PR would briefly create an
injection path before the confirm gate is proven — the exact audit hole this
sequence exists to prevent.

---

## 5. Ownership / handoff

| Responsibility | Owner |
|---|---|
| Review + merge PR #640; run `/deploy`; prod write | **Operator (Amit)** — prod write is operator-only |
| PR-2 implementation (endpoint, UI, gated injection, Issues #638/#639) | next implementation session, ADR-031 as contract |
| Re-run AWB 2315714531 recovery + confirm + PZ preview | Operator-initiated, after PR-2 deploys |
| Authority-isolation guard (must stay green every PR) | `test_vision_invoice_negative_scope.py` |
| Governance record of this state | this doc + ADR-031 + PROJECT_STATE.md |

Task #15 (PZ/wFirma goods-receipt for this AWB) remains **BLOCKED** and resumes
only after PR-2 deploys. Do not attempt a PZ create or a manual invoice re-key as
a shortcut — that re-introduces the shipment-specific patch Lesson I forbids.

---

## 6. Governance risks & production-safety flags (raised, tracked)

1. **Duplicate `fob_usd` across layers.** It lives in both `vision_invoice`
   (layer 1) and, post-parse, `invoice_totals` (layer 3). Safe **today** only
   because no single consumer reads both. **PR-2 must read layer 3, or read
   layer 1 strictly behind `operator_confirmed` — never "whichever exists."**
   Tracked in ADR-031 Risks.
2. **`operator_confirmed` must have exactly one writer** (the PR-2 endpoint). A
   second writer is an authority-forge risk. Add a static source contract if a
   second candidate path ever appears.
3. **No auto-confirm.** Confidence is a model self-report, not human attestation.
   No machine-decidable "low-risk" boundary may auto-promote a proposal to
   accounting authority (ADR-031 rejected alternative; Lesson M).
4. **Customs stays isolated.** CIF (732) is final on its own ladder and must
   never be re-derived from `vision_invoice`, even once confirmed. Layer 4 and
   layers 1–3 are separate ladders that never cross.

---

## 7. Rollback posture

PR #640 is additive and advisory. Removing the `vision_invoice` block and the
non-fatal orchestrator calls returns the system to text-parser-only behavior:
image-only invoices simply fail to produce PZ (exactly as before #640). No
accounting or customs data is touched by a rollback, because no
accounting/customs consumer reads the proposal. Cost: image-only invoices revert
to manual handling until re-deployed.
