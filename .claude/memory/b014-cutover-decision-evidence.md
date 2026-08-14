# B-014 — V1 → V2 Pro Forma cutover DECISION EVIDENCE

**Campaign mode:** DECISION-EVIDENCE (no cutover activated)  
**Recorded:** 2026-08-14  
**Production SHA:** `9fa7126d1feb15436ad0c86df851a326b2def702`  
**origin/main SHA:** `9fa7126d1feb15436ad0c86df851a326b2def702` (identical)  
**#1231:** CLOSED / DEPLOYED (mobile shell) — not reopened  
**Production writes this campaign:** `0`  
**Prior checkpoint:** `.claude/memory/b014-cutover-checkpoint.md` (2026-08-13 birth-block parity; cutover HOLD)

---

## 1. Authority owner

Canonical Pro Forma **workflow + API** = `routes_proforma.py` (`/api/v1/proforma/*`).  
Cutover question = which **UI surface** is the operator default — not a second fiscal authority.

| Layer | Authority |
|---|---|
| Fiscal writes | Same APIs (approve / post / to-invoice) + permission gates |
| V1 UI default (today) | `shipment-detail.html` → Sales tab → `ProformaDraftPanel` |
| V2 UI (available) | `/v2/proforma*` + `proforma-list.jsx` / `proforma-detail.jsx` / `proforma-search.jsx` |

---

## 2. Exact entry points

### V1 (live)

| Entry | Pattern | Notes |
|---|---|---|
| Shipment detail Sales | `/dashboard/shipment-detail.html?id={batch_id}` → tab **Sales** | **Production default** for batch draft ops. No `tab=` / draft deep-link. |
| Dashboard `?id=` | `/dashboard/dashboard.html?id=` → redirects to shipment-detail | Indirect |
| Orphan | `dashboard.html` embedded `ProformaDraftPanel` | **Unreachable** after detail extraction |

### V2 (live)

| Entry | Pattern |
|---|---|
| Landing | `/v2/proforma` |
| Batch list | `/v2/proforma?batch_id={id}` |
| Detail by draft | `/v2/proforma_detail?draft={n}` |
| Detail scoped | `/v2/proforma_detail?batch_id={id}&draft={n}` |
| Search | `/v2/proforma_search` |
| From V2 shipment | `shipment-detail-page.jsx` → `/v2/proforma?batch_id=` |
| From inbox | `inbox-page.jsx` → `/v2/proforma?batch_id=` |
| NAV | Sidebar **Pro Forma** (`components.jsx`) |

**V2 → V1 bounce for proforma:** none found (stays on `/v2/proforma*`).

---

## 3. V1 → V2 capability matrix

| Capability | V1 | V2 | Class |
|---|---|---|---|
| Batch draft list | Sales panel list | `/v2/proforma?batch_id=` | **PARITY** |
| Cross-batch search | no | `/v2/proforma_search` + landing search | **V2_SUPERSEDES** |
| Draft detail edit (lines, buyer, ship-to, payment, remarks) | yes | yes (`proforma-detail.jsx`) | **PARITY** |
| Birth blocks + assign | yes (B-014 parity) | yes (`proforma-list.jsx`) | **PARITY** |
| Advisory contractor conflicts | yes | yes | **PARITY** |
| Link packing as sales / create | yes (empty-state) | yes (+ create modal / packing upload) | **PARITY** / V2 richer |
| Approve | yes | yes | **PARITY** |
| Post to wFirma | yes | yes (+ disclose modal) | **PARITY** / V2 richer |
| Convert → invoice | handlers only, **no live UI** | **ConvertToInvoiceModal** wired | **V2_SUPERSEDES** |
| Preview / PDF | yes | yes | **PARITY** |
| Service charges + freight/insurance suggest | yes | yes | **PARITY** |
| Bulk price recovery | yes | import-sales-prices / related | **PARITY** (different UX) |
| Event history | yes | Audit tab | **PARITY** |
| **Reset ALL / reset-from-sales-packing** | **UI button** (`btn-draft-reset-all`) | API in `pz-api.js` only — **no V2 shell UI** | **V1_ONLY_REQUIRED** |
| Re-open / unapprove | on draft panel | Documents hub only — **not on detail toolbar** | **V1_ONLY_REQUIRED** (alternate path partial) |
| Readiness card (standalone) | defined, unwired | readiness panel on detail | **V2_SUPERSEDES** |
| Documents / email / reservation / AWB from draft | limited / none | Documents hub + logistics tabs | **V2_SUPERSEDES** |
| Export CSV | n/a | toolbar disabled | **UNKNOWN** / incomplete |
| Landing create “From Shipment / Manual / Clone” | n/a | UI stubs (modal close only) | **UNKNOWN** / incomplete |
| Deep link draft from Documents hub | n/a | uses `?draft_id=` — shell expects `?draft=` | **V1_ONLY_OBSOLETE** N/A — **V2 bug / gap** |
| `default_surface=v1` users | full V1 dashboard | redirected off V2 shell entirely | **RBAC / surface policy** |

Classification key: PARITY · V2_SUPERSEDES · V1_ONLY_REQUIRED · V1_ONLY_OBSOLETE · UNKNOWN

---

## 4. Unresolved V1-only functions (block hard sole-surface)

1. **Reset ALL / `POST …/reset-from-sales-packing`** — destructive packing re-sync used on V1 Sales panel; V2 Atlas shell has transport only (`pz-api.js` 451–453), no operator button on `proforma-detail.jsx` / `proforma-list.jsx`.
2. **Re-open from draft editor** — V1 panel action; V2 only via Documents hub (easy to miss).
3. **Bookmark habit** — operators bookmarked `shipment-detail.html?id=` + Sales tab; cutover must preserve or migrate those paths.

Frozen V1 `dashboard.html` panel = **V1_ONLY_OBSOLETE** (unreachable).

---

## 5. Deep-link / external compatibility risks

| Risk | Severity | Mitigation if cutover approved |
|---|---|---|
| `shipment-detail.html?id=` bookmarks still open V1 Sales | High habit | Soft redirect Sales → `/v2/proforma?batch_id=` **or** keep panel as escape |
| No V1 `tab=Sales` / draft id in URL | Med | V2 already supports `draft=` |
| `documents-hub.jsx` `?draft_id=` vs shell `?draft=` | Med | Fix before or with cutover |
| Legacy `?batch_id=` on V1 detail (some pages) | Low | V1 reads `id` only — pre-existing |
| `default_surface=v1` accounts never see V2 | Med | Per-user surface policy separate from proforma cutover |

---

## 6. RBAC differences

| Concern | Finding |
|---|---|
| Backend permissions | Shared: `proforma.edit` / `proforma.approve` / `proforma.convert`; assign = `require_admin` |
| V1 UI | No role matrix in JSX; API key / session + tokens |
| V2 UI | Page allowlist `allowed_pages` (+ aliases fold detail/search → `proforma`); action gates are readiness/state, not a second permission matrix |
| Permission widening | **None required** for cutover; do not weaken gates |

---

## 7. Financial / write-path differences

| Path | V1 | V2 |
|---|---|---|
| Approve / post | Same endpoints + confirm tokens | Same + richer disclose/post modals |
| Convert | **Not operator-reachable** on live V1 | Full two-step convert UI |
| Reset from packing | Live UI | Missing UI (API exists) |
| wFirma goods adopt/create | Limited in panel | Explicit product resolver on detail |

Cutover does **not** change fiscal authority — only which UI calls the same gated APIs.

---

## 8. Proposed cutover mechanism (NOT implemented)

**Soft default switch (recommended shape if operator says yes):**

1. On V1 `shipment-detail.html` Sales tab: replace inline `ProformaDraftPanel` mount with a prominent **Open Pro Forma (V2)** link to `/v2/proforma?batch_id={id}` **or** auto-redirect with a one-click “Use classic panel” escape for N days.
2. Optionally add Overview pipeline pill → V2 instead of `setActiveTab('Sales')`.
3. Fix Documents hub `draft_id` → `draft`.
4. Do **not** delete V1 panel source until Reset ALL + re-open exist on V2 detail.
5. Seven-agent gate + browser verify on a real batch with birth-blocks + drafts (per prior checkpoint).

**Hard sole-surface (remove V1 panel):** blocked by §4 until gaps closed → treat as **NOT_READY**.

---

## 9. Proposed rollback

| If soft redirect/link | Revert App deploy of cutover SHA; restore Sales panel mount; clear any temporary redirect. Unit via `Deploy-PZ.ps1 -Rollback -Unit <unit>`. |
|---|---|
| Data / drafts | Unchanged (same DB / APIs) — rollback is UI-only |
| Operator message | “Classic Sales panel restored” |

---

## 10. Files that WOULD change if soft cutover approved (candidate only)

| File | Change |
|---|---|
| `service/app/static/shipment-detail.html` | Sales tab → V2 entry / optional escape |
| `service/app/static/v2/documents-hub.jsx` | `draft_id` → `draft` |
| Possibly `shipment-detail.html` Overview pills | Point to `/v2/proforma?batch_id=` |
| Tests | Source-grep / browser pins for new default |
| **Not** in first cutover | Engine, routes_proforma.py permissions, wFirma flags |

**Pre-hard-cutover (separate):** wire Reset ALL + re-open on `proforma-detail.jsx`.

---

## 11. Recommendation

### Soft cutover (V2 default entry; V1 panel retained as escape):  
**CUTOVER_READY_WITH_EXPLICIT_KNOWN_GAPS**

Known gaps to accept in writing:

1. Reset ALL remains on V1 escape path until V2 UI exists.  
2. Re-open primarily via Documents hub on V2.  
3. Documents hub `draft_id` deep-link should be fixed in the same or immediately preceding PR.  
4. Export CSV / some landing create stubs remain incomplete (non-blocking if unused).

### Hard cutover (V1 panel removed / unreachable):  
**NOT_READY**

Until Reset ALL + draft-level re-open are on V2 Atlas shell and verified.

---

## 12. Exact operator decision required

Choose **one**:

**A.** Approve **soft cutover** — V2 becomes the default Pro Forma entry from shipment/overview; V1 Sales panel remains reachable as repair escape; accept known gaps above; authorize an App-only PR + seven-agent gate + browser verify before activate.

**B.** Defer — remain on V1 Sales as production default; optionally schedule Reset ALL + re-open on V2 first (then revisit hard or soft).

**C.** Reject cutover for now — no route/nav changes.

**Do not** interpret silence as approval. **Do not** remove V1 routes without a separate explicit “hard cutover” decision after gaps close.

---

## 13. Evidence sources

- Explore inventories (this session): V1 `shipment-detail.html` ProformaDraftPanel; V2 `index.html` / `proforma-*.jsx` / `pz-api.js`
- Prior: `b014-cutover-checkpoint.md`, `b014-authority-map.json`
- HEAD / prod identity: both `9fa7126d…`
