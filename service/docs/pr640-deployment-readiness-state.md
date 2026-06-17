# PROJECT STATE — PR #640 Deployment Readiness

**Single source of truth for merge review + the 7-agent deploy gate.**
**Authored:** 2026-06-17 · **Owner:** Amit (operator) · **Status of this doc:** pre-merge snapshot

> Read this before approving the merge or firing `/deploy`. It states exactly
> what PR #640 does, what it deliberately does **not** do, what stays blocked
> after it ships, and what the deploy gate must validate. If any line here
> conflicts with the live repo, the repo wins — re-snapshot before deciding.

---

## 0. AT-A-GLANCE

| Field | Value |
|---|---|
| **PR** | #640 — `fix(invoice): advisory image-only invoice extraction (FOB + line items + supplier) — PR-1` |
| **Branch** | `fix/invoice-image-only-lineitem-extraction` |
| **HEAD** | `d04e95c` |
| **Base / merge-base** | `origin/main` = `4652292` (clean; branch adds exactly 3 commits) |
| **Mergeable** | ✅ MERGEABLE · not draft |
| **Reviewer-challenge** | ✅ PASS (all 4 REQUIRED findings resolved at `f6c7ec2`) |
| **Test baseline** | ✅ PZ 221/221 · Carrier 420 ≥ 412 (`.claude/contracts/test-baseline.md`) |
| **Change class** | Backend-only + docs. No schema, no migration, no forbidden/root-engine paths. |
| **Deployed?** | ❌ NO — pending operator merge → 7-agent gate → operator prod write |
| **Net behavioral effect** | image-only invoices accumulate a **reviewable proposal**; PZ/wFirma stay blocked |

**Commits on the branch (over `4652292`):**
- `d8c1710` — advisory image-only invoice extraction (FOB + line items + supplier)
- `f6c7ec2` — reviewer-challenge REQUIRED findings (USD-only gate, engine_parsed guard, TOCTOU stickiness, negative-scope tests)
- `d04e95c` — docs: ADR-030 + runbook + AWB 2315714531 handoff

---

## 1. 🚫 BLOCKERS — read first

### BLOCKER-1 (by design): PZ / wFirma remain blocked pending PR-2

**Status:** EXPECTED. This is **blocked-by-design, not blocked-by-bug.** Do not
treat it as a regression and do not attempt to "unblock" it inside PR #640.

**Why:** PR #640 only produces an *advisory* `vision_invoice` proposal. The only
thing that could fill the accounting layer (layer 3) for an image-only shipment
is that proposal — and ADR-030 forbids any machine proposal from becoming
accounting authority until an operator confirms it. The operator-confirmation
workflow does not exist yet. It is **PR-2**.

**Dependency chain (must happen in this order — see runbook §1):**

```
PR #640 merged
   └─► 7-agent deploy gate (GO)
          └─► #640 deployed to C:\PZ  (proposals now appear in prod, still advisory)
                 └─► PR-2 built: lifecycle state + operator-confirm endpoint
                      + visible/enabled confirm UI (Lesson M) + GATED engine injection
                      + Issue #638 (qty coercion) + Issue #639 (confidence boundary) CLOSED
                       └─► 7-agent deploy gate (GO)
                              └─► PR-2 deployed
                                     └─► re-run recovery on AWB 2315714531
                                          └─► operator reviews proposal → CONFIRM
                                               └─► engine recomputes → layer 3 populated
                                                    └─► PZ preview (READ) → PZ create → wFirma post
                                                         └─► Task #15 CLOSED
```

**Hard rule:** PR #640 and PR-2 must NOT be collapsed into one PR. A combined PR
would briefly create an engine-injection path before the confirm gate is proven —
the exact audit hole this campaign exists to close (machine OCR booked as a goods
receipt with no human attestation).

### BLOCKER-2 (informational): Task #15 stays PENDING

PZ/wFirma goods-receipt for AWB 2315714531 (Task #15) cannot progress until
BLOCKER-1's chain completes. No PZ create, no manual invoice re-key as a
shortcut (a re-key is the shipment-specific patch Lesson I forbids).

---

## 2. 🔒 AUTHORITY LIMIT — `vision_invoice` is PROPOSAL authority ONLY

This is the load-bearing invariant of the whole campaign. Downstream services
**must** respect it.

> **No service may read `vision_invoice` directly to drive PZ generation, wFirma
> posting, landed-cost computation, accounting exports, or warehouse booking
> unless `vision_invoice.operator_confirmed == true`.** — ADR-030 enforcement rule

**Four-layer authority model (ADR-030):**

| Layer | Key | Trust | Owner / sole writer |
|---|---|---|---|
| 1 — proposal | `audit["vision_invoice"]` | **NONE** (advisory) | `vision_extractor.run_image_only_invoice_extraction` |
| 2 — adoption | `vision_invoice.operator_confirmed == true` | human-attested | PR-2 operator-confirm endpoint (**does not exist yet**) |
| 3 — accounting | `audit["rows"]` + positive `invoice_totals.total_fob_usd` | authoritative (accounting) | `process_batch()` |
| 4 — customs | `audit["clearance_decision"]` / `resolve_cif()` | authoritative (customs) | `clearance_decision` over `cif_resolver` |

**Enforced today by:**
- `test_vision_invoice_negative_scope.py` — poison-block behavioral invariance
  (a `99999` CIF-shaped value in `vision_invoice` never perturbs `resolve_cif` /
  `build_clearance_decision` output) + static source contracts asserting the
  substring `"vision_invoice"` is absent from `cif_resolver.py`,
  `clearance_decision.py`, `active_shipment_monitor.py`.
- USD-only gate in `_merge_vision_invoice` (FOB accepted only when currency reads USD).
- Sticky confirmation + TOCTOU re-read before atomic write; `vision_invoice` in
  `audit_merge.PRESERVED_KEYS`.

**Corollary — customs is fully isolated.** CIF (layer 4) and purchase accounting
(layers 1–3) are separate ladders that never cross. The vision *CIF* fallback
(#632/#633) writes only CIF-ladder keys; the vision *invoice* layer (#640) writes
only `vision_invoice`. Neither reads the other. Customs for AWB 2315714531 is
already **RESOLVED (CIF USD 732)** and is unaffected by anything in PR #640.

---

## 3. SCOPE BOUNDARIES

### In scope (PR #640 — PR-1)
- Advisory recovery layer: `run_image_only_invoice_extraction` reads supplier /
  USD FOB / goods line-items from an image-only invoice into `audit["vision_invoice"]`
  with `operator_confirmed=false`, `confidence`, gated on: engine-not-parsed AND
  image-only AND confidence ≥ `MIN_WRITE_CONFIDENCE`.
- Authority-isolation guard tests (negative scope).
- Governance docs: ADR-030, runbook, AWB 2315714531 handoff.

### Out of scope (deferred to PR-2 — must NOT appear in #640)
- Operator-confirm endpoint / any writer of `operator_confirmed=true`.
- Engine injection of confirmed proposal into `process_batch()` inputs.
- Confirm UI control (will be visible-and-disabled meanwhile, per Lesson M).
- Supplier cross-validation against contractor/customer master.
- Issue #638 (dedicated quantity coercion) and Issue #639 (0.49/0.51 confidence
  boundary test) — both close **before** injection wiring.

### Forbidden (standing campaign constraints — never in this campaign)
- No touching wFirma booking, SAD/ZC429 accounting, VAT posting, or deploy scripts.
- No shipment-specific hardcoding. No faked CIF/FOB zero ("Unknown = UNKNOWN").
- No removal of the authority guard. AI advisory only; operator approval is the
  only write gate. Prod writes and `gh pr merge` are operator-only.

---

## 4. ✅ 7-AGENT DEPLOY GATE — what must be validated before progression

`/deploy` is mandatory for this Git-based production deploy (CLAUDE.md permanent
rule). Run all 7 agents in parallel; `deploy-lead-coordinator` issues go/no-go.
This deploy runs **after** operator merges #640 to main.

| # | Agent | Must confirm for #640 |
|---|---|---|
| 1 | `deploy_lead_coordinator` | final GO/NO-GO; conflicts resolved |
| 2 | `deploy_git_diff_reviewer` | changed files classify SAFE; **no FORBIDDEN_PATH**; no root-engine file (Lesson J **N/A** — change is `service/app/**` + docs only) |
| 3 | `deploy_backend_impact_reviewer` | routes/auth guards intact; router registration unchanged; no new requirements.txt; no platform-specific import |
| 4 | `deploy_persistence_storage_reviewer` | **no schema mutation, no migration, no new storage write path** |
| 5 | `deploy_security_reviewer` | no credential exposure; no auth/guard removal; **authority guard (`vision_invoice` isolation) intact** |
| 6 | `deploy_qa_reviewer` | PZ 221/221 + carrier ≥ 412 green; no regression introduced by the diff |
| 7 | `deploy_release_manager` | clean tree, main branch, ff-only; exact rollback command for the deploy SHA; standard `service/app → C:\PZ\app` robocopy plan; post-deploy checklist |

**Deploy hygiene reminder (PROJECT_STATE PYCACHE RULE):** clear ALL `__pycache__`
recursively under `C:\PZ` (app + engine) before service restart, else stale
`.pyc` shadows new source silently.

**Post-deploy verification (release-manager checklist must include):** on a real
image-only invoice in production, confirm `audit["vision_invoice"]` is written
with `operator_confirmed=false` AND that `rows` / `invoice_totals` /
`clearance_decision` / CIF are **byte-unchanged**. Prod write + verify are
operator-only; do not report "deployed" until the prod hash flips.

---

## 5. MERGE-GATE STATUS (GATE 1 / GATE 2)

- **GATE 1 (PR open discipline):** ✅ satisfied — reviewer-challenge PASS, all
  HIGH/REQUIRED findings resolved inline, regression baseline green, forbidden-
  files check clean. Backend-only (no UI surface) → browser-verification N/A.
- **GATE 2 (max open PRs):** confirm live count before merge. Per last
  PROJECT_STATE snapshot the implementation queue was 2/3 (#630, #633); #633 has
  since merged (`4652292`). #640 is 1 implementation PR + docs ride the same
  branch (zero-blast-radius docs). Re-check `gh pr list` at merge time.
- **GATE 4 dispositions filed:** Issue #638 (SCHEDULED → PR-2), Issue #639
  (SCHEDULED → PR-2). Finding 6 (full-doc image-only limitation) documented in PR body.

---

## 6. REFERENCE GLOSSARY (deployment chain)

| Reference | What it is in this chain |
|---|---|
| **PR #640** | This PR. PR-1 of the invoice-extraction campaign: the advisory `vision_invoice` recovery layer. Adds proposal data + governance docs; grants no accounting authority. |
| **ADR-030** | `.claude/adr/ADR-030-invoice-extraction-authority-separation.md` — permanent four-layer authority law + enforcement rule + test pattern. The governing contract PR-2 must implement against. |
| **AWB 2315714531** | The triggering shipment: customs-cleared (CIF 732) but image-only invoice → no PZ computable. The first shipment to flow the permanent path once PR-2 deploys. Handoff: `service/docs/awb-2315714531-extraction-handoff.md`. |
| **PZ / wFirma** | Purchase-accounting goods receipt (PZ = Przyjęcie Zewnętrzne) and the wFirma accounting system it posts to. Both read **layer 3 only**; blocked while layer 3 is empty. |
| **PR-2** | Not yet opened. The operator-confirmation workflow: lifecycle state, confirm endpoint (sole writer of `operator_confirmed`), enabled confirm UI, **gated** engine injection. Unblocks PZ/wFirma. |
| **vision_invoice** | `audit["vision_invoice"]` — layer-1 proposal block. Advisory only. May influence PZ/wFirma/landed-cost **only** behind `operator_confirmed == true`. |
| **#632 / #633** | Already MERGED to main (the vision **CIF** fallback + UI resolved-CIF authority). Separate authority ladder (customs); resolved AWB 2315714531's CIF to 732. Confirm production-deploy state via the release manager — do not assume from merge state. |

---

## 7. SIGN-OFF CHECKLIST (before merge)
- [ ] Re-snapshot `git rev-parse HEAD` of branch == `d04e95c` (or newer, re-reviewed).
- [ ] `gh pr list` confirms GATE 2 has an open slot for this implementation PR.
- [ ] Reviewer-challenge PASS still current for HEAD.
- [ ] PZ 221 + carrier ≥ 412 green on the merge SHA.
- [ ] Operator merges #640 (operator-only).
- [ ] 7-agent `/deploy` gate → GO.
- [ ] Operator executes robocopy + `__pycache__` clear + restart (operator-only).
- [ ] Post-deploy verify: proposal written `operator_confirmed=false`; layer 3 / CIF byte-unchanged.
- [ ] `flow-context-keeper` records the deploy SHA + verification in PROJECT_STATE.md FACTS.
