# B-MD4 — Master Data Full Browser Smoke Checklist (Operator-Driven)

> **Status:** awaiting operator session. NO mechanical execution from this run.
> 20 surface walks. Safe smoke actions only. NO destructive writes against
> real production records.
> **Campaign:** `MDOC-2026-05` / batch `B-MD4`. **Date:** 2026-05-16.

This checklist is the operator-driven browser smoke for every live Master
Data surface after B-MD3 deploy. Run when an operator (or operator + claude
pair) has a session at `https://pz.estrellajewels.eu/login` and is willing
to drive through 20 visual checks. Estimated time: ~30–40 minutes.

---

## How to use this checklist

1. Log in at `https://pz.estrellajewels.eu/login`.
2. For each surface below, follow the exact steps in the "Safe smoke action" column.
3. For destructive writes, use the documented **temp smoke records**:
   - Designs: `SMOKE_MD4_DSGN_001` (delete at end of section 11)
   - Suppliers: `SMOKE_MD4_SUP_001` (delete at end of section 8)
   - Customer Master: **DO NOT MUTATE.** Read-only walk only — see §2.
4. Open browser DevTools → Console + Network tabs before starting.
5. After each surface, record verdict by editing this file: change `[ ]` → `[x]` (pass) or `[!]` (fail with note).
6. If ANY destructive surface mutates a real production record, STOP immediately and escalate.

---

## 1 — Clients (read-only mirror over wFirma customers)

- **Page path:** `Setup → Master Data → Clients` (sidebar entity `clients`)
- **Expected panel/testid:** `master-page` + clients table renders with `customers.items`
- **Enabled buttons:** Row "Open profile" (opens KYC modal). `Re-check` header button.
- **Disabled buttons:** None expected.
- **Safe smoke action:** Click `↻ Re-check` (triggers GET-only reloads). Open any row's profile via "Open profile" → KYC modal renders.
- **Destructive action:** None possible; ClientKycModal opens but does not write.
- **Expected console:** No errors.

`[ ]` Passed   `[ ]` Failed (note: ____________)

---

## 2 — Customer Master (read-only walk; do NOT mutate)

- **Page path:** Open Clients → "Open profile" on a real client → KYC modal Customer Master tab.
- **Expected panel/testid:** `master-cm-section` (or equivalent) inside KYC modal.
- **Enabled buttons:** Inline `Edit` per field group (would save via PUT). **DO NOT click Save with edits in this smoke.**
- **Disabled buttons:** None.
- **Safe smoke action:** Click `Edit` to enter edit mode, then immediately click `Cancel`. Verify no PUT fires in Network tab.
- **Destructive action AVOIDED:** Do not enter values and click Save.
- **Expected console:** No errors; no PUT requests visible.

`[ ]` Passed   `[ ]` Failed

---

## 3 — Shipping Addresses (per client; read-only walk preferred)

- **Page path:** Same KYC modal → Addresses tab.
- **Expected panel/testid:** addresses table renders with `client_addresses` items.
- **Enabled buttons:** `+ New address`, `Edit`, per-row `×`.
- **Safe smoke action:** Click `+ New address`. Cancel without filling. Verify zero network writes.
- **Destructive action AVOIDED:** Do not add or delete a real address.

`[ ]` Passed   `[ ]` Failed

---

## 4 — Client Carrier Accounts (per client)

- **Page path:** Same KYC modal → Carriers tab.
- **Expected panel/testid:** carrier accounts table renders.
- **Enabled buttons:** `+ New carrier account`, `Edit`, per-row `×`.
- **Safe smoke action:** Click `+ New carrier account`, Cancel without filling.
- **Destructive action AVOIDED:** Do not save credentials to a real client.

`[ ]` Passed   `[ ]` Failed

---

## 5 — KYC tab

- **Page path:** KYC modal → KYC tab.
- **Expected panel/testid:** KYC form with `kyc_status`, `kyc_approved_on`, `kyc_expiry` fields.
- **Enabled buttons:** Inline Edit/Save (writes via Customer Master PUT).
- **Safe smoke action:** Open KYC tab; read values; do NOT save changes.

`[ ]` Passed   `[ ]` Failed

---

## 6 — KUKE / Credit tab

- **Page path:** KYC modal → Credit tab.
- **Expected fields:** `kuke_limit`, `kuke_approved`, `credit_limit`.
- **Safe smoke action:** Open Credit tab; read values; do NOT save changes.
- **Regression watch:** L-004 (`Decimal(0)` falsy trap) fix from B0 must still hold; entering `kuke_limit=0` while `kuke_approved=true` must not 422.

`[ ]` Passed   `[ ]` Failed

---

## 7 — Invoice Settings tab

- **Page path:** KYC modal → Invoices tab.
- **Expected fields:** `vat_id`, `default_vat_code`, `default_incoterm`, etc.
- **Safe smoke action:** Open Invoices tab; read values; close modal without saving.

`[ ]` Passed   `[ ]` Failed

---

## 8 — Suppliers (live CRUD)

- **Page path:** Master Data → Suppliers entity (sidebar).
- **Expected panel/testid:** `master-suppliers-panel`.
- **Enabled buttons:** `+ New supplier`, `Edit`, per-row `×` (testid `master-suppliers-btn-delete-*`).
- **Safe smoke action (temp record):**
  1. Click `+ New supplier`.
  2. Set name `SMOKE_MD4_SUP_001`, country `PL`, tax_id `SMOKE-MD4`, click Save.
  3. Confirm row appears in the list.
  4. Click `Edit`; change note to "B-MD4 smoke"; Save.
  5. Click `×` on the row; confirm dialog; Yes; confirm row disappears.
- **Cleanup:** Step 5 deletes the temp record. Confirm `GET /api/v1/suppliers/?name=SMOKE_MD4_SUP_001` returns empty (or verify visually).

`[ ]` Passed   `[ ]` Failed

---

## 9 — Products (read-only mirror over wFirma)

- **Page path:** Master Data → Products entity.
- **Expected panel/testid:** `master-products-panel`.
- **Enabled buttons:** None (read-only).
- **Safe smoke action:** Verify the table renders. Confirm no Add/Edit/Delete buttons exist.

`[ ]` Passed   `[ ]` Failed

---

## 10 — Product Local (B5)

- **Page path:** Master Data → Product local entity.
- **Expected panel/testid:** `master-product-local-panel`.
- **Enabled buttons:** `+ New augmentation`, `Edit`, per-row `×`.
- **Safe smoke action (temp record):**
  1. `+ New augmentation`; product_code `SMOKE-MD4-PL`; hs_code_override `711319`; Save.
  2. Edit notes to "smoke"; Save.
  3. Delete via `×`; confirm gone.

`[ ]` Passed   `[ ]` Failed

---

## 11 — Designs (B-MD2 live)

- **Page path:** Master Data → Designs entity.
- **Expected panel/testid:** `master-designs-panel`, `master-designs-btn-new`.
- **Enabled buttons:** `+ New Design`, `Edit`, per-row `×`, `master-designs-btn-save`, `master-designs-btn-cancel`.
- **Safe smoke action (temp record):**
  1. Click `+ New Design`.
  2. design_code `SMOKE_MD4_DSGN_001`; display_name `Smoke MD4 Test`; design_family `Ring`; metal `Au18K`; active=checked; Save.
  3. Confirm row appears in the list with `count` badge incrementing.
  4. Click `Edit`; change notes to "B-MD4 smoke"; Save.
  5. Verify "(soft)" / "(soft ref)" labels on `product_ref`, `hs_code`, `unit` fields.
  6. Cancel out of edit mode.
  7. Click `×` on the row; confirm dialog; Yes; confirm row disappears.
- **Cleanup:** Step 7 deletes. Confirm `GET /api/v1/designs/SMOKE_MD4_DSGN_001` → HTTP 404 in DevTools Network.

`[ ]` Passed   `[ ]` Failed

---

## 12 — HS Codes (B5)

- **Page path:** Master Data → HS Codes entity.
- **Expected panel/testid:** `master-hs-codes-panel`.
- **Safe smoke action:** Verify table renders. Open `+ New HS code` form; Cancel without saving.

`[ ]` Passed   `[ ]` Failed

---

## 13 — Units (B5)

- **Page path:** Master Data → Units entity.
- **Expected panel/testid:** `master-units-panel`.
- **Safe smoke action:** Verify table renders. Open `+ New unit` form; Cancel.

`[ ]` Passed   `[ ]` Failed

---

## 14 — Incoterms (B7)

- **Page path:** Master Data → Incoterms entity.
- **Expected panel/testid:** `master-incoterms-panel`.
- **Safe smoke action:** Verify table renders. Open `+ New incoterm` form; Cancel.

`[ ]` Passed   `[ ]` Failed

---

## 15 — VAT Config (B7)

- **Page path:** Master Data → VAT Config entity.
- **Expected panel/testid:** `master-vat-config-panel`.
- **Safe smoke action:** Verify table renders. Open `+ New VAT entry`; Cancel.

`[ ]` Passed   `[ ]` Failed

---

## 16 — FX Rates (B8, reference-only)

- **Page path:** Master Data → FX Rates entity.
- **Expected panel/testid:** `master-fx-rates-panel`.
- **Hard rule:** MDC-071 — FX **never** overrides PZ landed-cost.
- **Safe smoke action:** Verify table renders. Open `+ New FX entry` form; Cancel.
- **Regression watch:** No FX-override write must appear in the form description.

`[ ]` Passed   `[ ]` Failed

---

## 17 — Global Carrier Config (B9)

- **Page path:** Master Data → Carriers Config entity.
- **Expected panel/testid:** `master-carriers-config-panel`.
- **Hard rule:** Local, non-secret only. No credentials.
- **Safe smoke action:** Verify table renders. Open `+ New carrier` form; Cancel.

`[ ]` Passed   `[ ]` Failed

---

## 18 — Admin · Users (B-MD1; admin-only)

- **Page path:** `Setup → Admin · Users`.
- **Expected panel/testid:** `admin-users-page` (admins) OR `admin-users-access-denied` (non-admins).
- **Enabled buttons (admins):** `↻ Refresh`, `Approve` / `Reject` (pending rows), `Set role ▾` / `Deactivate` (approved active rows; not on self-row), `Activate` (inactive rows).
- **Disabled buttons:** `Invite user · Backend pending / out of scope` chip (testid `admin-users-invite-disabled`).
- **Safe smoke action:**
  1. Verify page renders for admin session; banner renders for non-admin if available.
  2. Click `↻ Refresh`. Single GET fires.
  3. On any pending row (if one exists), hover Approve/Reject — confirm dialogs would appear; do NOT click through.
  4. On current admin's own row: confirm Actions column shows `—` (self-lockout).
  5. Verify the disabled Invite-user chip carries the visible reason text.
- **Destructive action AVOIDED:** Do NOT click through any Approve/Reject/Set-role/Deactivate confirm dialog on a real user.

`[ ]` Passed   `[ ]` Failed

---

## 19 — Roles read-only explainer (B-MD2c)

- **Page path:** Master Data → Roles entity.
- **Expected panel/testids:** `master-roles-panel`, `master-roles-explainer`, `master-roles-enforcement-matrix`, `master-roles-btn-open-admin-users`.
- **Enabled buttons:** Exactly 1: "Open Admin · Users →" (navigation).
- **Disabled buttons:** None.
- **Safe smoke action:**
  1. Verify explainer text describes the 5 roles + "deferred" enforcement engine.
  2. Verify enforcement matrix shows 5 rows with `admin / accounts / logistics / auditor / viewer`.
  3. Click "Open Admin · Users →"; verify navigation to AdminUsersPage.

`[ ]` Passed   `[ ]` Failed

---

## 20 — Finance Posting Breakdown panel (6F.4, read-only)

- **Page path:** `Setup → Diagnostics` (NOT inside Master Data).
- **Expected panel/testid:** `diagnostics-finance-posting-panel`, `diagnostics-finance-readonly-badge`, `diagnostics-finance-posting-id-input`, `diagnostics-finance-posting-fetch`.
- **Enabled buttons:** `Fetch` (requires id input).
- **Disabled buttons:** None visible; no create/update/delete affordances.
- **Safe smoke action:**
  1. Enter `999999` (non-existent id).
  2. Click Fetch.
  3. Verify HTTP 404 → empty-state copy "No posting with id 999999 ... by design ... dormant until backfill runs or a posting is created."
  4. Verify `schema_version` chip displays a non-empty value.
- **Regression watch:** `C:\PZ\storage\finance_postings.sqlite` size must remain 81,920 B (6F.5 default-OFF).

`[ ]` Passed   `[ ]` Failed

---

## 21 — Final state checks

After all 20 surfaces are walked:

`[ ]` Browser console: zero errors across all sessions.
`[ ]` Network tab: zero unexpected 4xx/5xx (404s on smoke-design-after-delete are expected).
`[ ]` `pz_stderr.log` (tail 50): no new tracebacks; zero `finance_dual_write` lines.
`[ ]` `C:\PZ\storage\finance_postings.sqlite` size unchanged at 81,920 B.
`[ ]` `C:\PZ\storage\users.db`: no row mutated unless explicitly approved as part of step 18.
`[ ]` `C:\PZ\storage\master_data.sqlite`: temp smoke records (DSGN/SUP/PL) all deleted.

---

## Closure

When all 20 + final check items are `[x]`:

1. Append a "Browser smoke result" section at the bottom of this file with date/time + operator name.
2. Update `tasks/campaign-state.json`: `B-MD4` → `smoked`.
3. Update `tasks/todo.md` with MDOC closure status.
4. Open a docs-only closure PR (`docs/b-md4-browser-smoke-closure`).
5. If MDOC-2026-05 has no remaining batches, mark the campaign `closed_pending_reopening` with a closure doc (mirror `phase-6f-campaign-close.md` pattern).

If ANY check fails:

1. STOP immediately.
2. Capture screenshot + console output + network HAR.
3. Append to this file with `[!]` and a Root-cause-pending note.
4. Open a focused fix PR (no widening of scope).
5. Re-run only the failing checks after the fix deploys.

---

## Hard rules in effect during B-MD4

- No env vars set
- No flags flipped
- No 6F.5 activation
- No `routes_auth.py` change
- No auth schema change
- No new write endpoint
- No new UI button
- No mutation of real user accounts in step 18
- No mutation of real customer master rows
- No mutation of real address/carrier-account rows
- Phase 6F remains paused/default-OFF
