# Campaign Closure — Proforma Wireframe Rebuild (PFW)

Engineering OS v1.3 Phase 9 record (Operational Excellence & Knowledge Capture).
Companion documents: `docs/decisions/ADR-proforma-wireframe-rebuild.md` (ADR),
`service/docs/ops/proforma-detail-wireframe-runbook.md` (runbook),
Phase-8 certification: https://claude.ai/code/artifact/a2221cee-fce5-4b67-ac53-fdd22a7eda77

## 9. Campaign closure record

| Field | Value |
|---|---|
| Campaign name | Proforma Detail — Wireframe 1:1 UI/UX Rebuild |
| Campaign ID | PFW (memory: `project-proforma-wireframe-rebuild`) |
| Start / end | 2026-07-10 / 2026-07-10 (single-day, 4 sequential releases) |
| PRs | #870 · #872 · #874 · #875 (+ certification, evidence-only) |
| Production commits | `709f8592` → `7ca509e8` → `52ee8ad2` → `b1caafd4` (current prod) |
| Rollback commits | revert in reverse: `b1caafd4`, `52ee8ad2`, `7ca509e8`, `709f8592` |
| Final status | **Complete with Residue** (register below; nothing load-bearing) |

## 2. Technical Debt Register

| # | Item | Category | Priority | Effort | Blocking? |
|---|---|---|---|---|---|
| 1 | Modal a11y set: `role="dialog"`/`aria-modal`, Escape handlers, named "×" close buttons, input `htmlFor`/`id` association, focus-ring restoration (`outline:none` in `PF_EDIT_INPUT` + autocomplete) | Accessibility | HIGH | 1 slice (page-wide, mechanical) | No |
| 2 | Old drafts show `—` in variant columns until reset/new intake; Slice-1 live-intake confirmation still pending the next real shipment | Backend | MED | observation only | No |
| 3 | Tare weight `—` (needs box-types join); no standalone Box-Profile panel in Logistics | UI | LOW | small | No |
| 4 | CMR number has no persistence anywhere (client-side preview renderer only) | Backend | LOW | needs design (new column/authority ruling) | No |
| 5 | Total PLN tile `—` until a backend-provided posted PLN total is surfaced | UI/Backend | LOW | small (surface wFirma posted total) | No |
| 6 | ⚙ Generate ▾ disabled — backend gap M4 (`POST /draft/{id}/generate-documents`) | Integration | LOW | medium | No |
| 7 | Per-line variant editing rejected by `EDITABLE_LINE_FIELDS` (reset is the refresh path) — revisit only with a business rule | Backend | LOW (by design) | n/a | No |
| 8 | Pre-existing `...payload })` spread-rest regex false-positive inside protected AWB modal (baseline-registered; fix requires touching protected block) | Testing | LOW | trivial but gated on AWB-block approval | No |
| 9 | List-page programmatic row-click drill inert under automation (human clicks fine) — matters only if E2E automation lands | Testing | LOW | small | No |
| 10 | Screenshot pipeline unusable in the verification environment (no visual-regression tooling) | Infrastructure | MED | tooling investigation | No |
| 11 | No performance instrumentation in the Babel-standalone stack (no render-count profiling) | Performance | LOW | tooling | No |
| 12 | Docs: none outstanding — this Phase-9 set closes the documentation items | Documentation | — | — | No |

GATE-4 note: items above are the campaign's residue register (disposition =
SCHEDULED-in-register); #1 is the recommended next slice, #10 the recommended
next infrastructure task. Previously-filed GATE-4 items from the campaign
(print-pin repoint) were executed in #875.

## 4. Dependency Audit

- New libraries: **none**. Updated: **none**. Deprecated: **none**.
  (Verified: no `requirements*`, `package*`, or `static/v2/vendor` files in
  `b751dd2b..b1caafd4`.) Babel-standalone 7 pin and React CDN pins unchanged.
- External APIs touched at runtime: none new — the page reuses existing
  internal endpoints only; the one "new" call site (KUKE panel) reuses
  `GET /api/v1/customer-master/{id}`.
- Migration impact: zero schema migrations; `editable_lines`/`source_lines`
  are JSON blobs extended additively.

## 5. Performance Baseline (reference point, 2026-07-10 @ `b1caafd4`)

| Metric | Value |
|---|---|
| `proforma-detail.jsx` size | 365,758 bytes (pre-campaign 329,262 → +36.5 KB, +11%; in-browser Babel compile, served no-store) |
| Detail-page API calls (full load) | 10 endpoints; `draft/{id}` ×2 (load + hydration), `readiness` ×2 (two intents), rest ×1 — no duplication storm |
| Prod `/docs` latency (local) | ~0.21 s |
| Console on tracked full load | 0 errors, 0 warnings, 0 React warnings |
| Render counts / memory | not instrumentable in Babel-standalone prod mode (register item #11) |

## 6. Production Health Check (first observation period)

- PZService RUNNING; `/docs` 200; `/api/v1/health` 401 (alive + auth-gated).
- Deployed `proforma-detail.jsx` hash-matches repo @ `b1caafd4` (LF-normalized).
- `pz_stderr.log`: **zero** proforma/carrier/AWB errors. One live defect
  present — `sqlite3.OperationalError: no such column: o.occurred_at`
  (`routes_inventory_sample.py:188`) — **inventory module, unrelated to PFW,
  already tracked by open PR #876** (2 occurrences).
- Extended monitors are owned by POST-RELEASE STABILIZATION-1 (separate
  session): draft lifecycle, webhook delivery, PM sync, carrier, stderr;
  event-gated exits pending real business activity.

## 7. Documentation Update Confirmation

- README: unaffected (no build/run changes) — no update needed.
- CLAUDE.md: workflow unchanged; Phase-8/9 doctrine lives in operator memory
  (`feedback-phase8-release-certification`) pending an operator decision to
  ratify Engineering OS v1.2/v1.3 into CLAUDE.md — **deliberately not edited**
  here (CLAUDE.md changes are operator-ratified).
- Architecture docs: ADR added (this campaign's decision record).
- API docs: draft GET additive keys are documented in the Slice-1 PR body and
  ADR; no OpenAPI hand-written docs exist to update (FastAPI auto-docs cover).
- User documentation: none exists for this page; runbook covers operator needs.

## 8. Knowledge Transfer (summary for future engineers)

**What changed:** the V2 Proforma Detail page now renders the operator's
wireframe design over the existing draft authority; the draft API additionally
exposes per-line variant identity and VAT/NBP/payment header keys; a KUKE
insurance panel reads Customer Master.

**Why:** operator-approved wireframe, 1:1 UI/UX parity with zero authority
loss.

**Do not modify without reading the ADR first:**
`AwbGenerateModal` (protected, byte-stable through the rebuild), the `Pf*`
primitive names (global-scope collision), the authority pins that beat the
wireframe (Total PLN `—`, "✎ Edit" label), `EDITABLE_LINE_FIELDS` (variant
keys deliberately excluded), and any test-pinned `data-testid`.

**Remaining limitations:** tech-debt register above.

**Recommended next campaign:** the accessibility slice (register #1) — one
mechanical, page-wide pass adding dialog semantics, label association, and
focus rings; zero authority risk, HIGH operator value for keyboard use.
