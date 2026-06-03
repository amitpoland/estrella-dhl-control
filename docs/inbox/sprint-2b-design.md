# Sprint 2B Design — Global Inbox: GET /api/v1/inbox
# Authz audit + aggregator spec + write-action scope

**Status:** DESIGN — operator review required before 2B.1 build begins
**VERIFY_DIR:** C:\PZ-verify @ f9aa00f
**Sources:** all findings from live source files (file:line cited throughout)

---

## PHASE 0 — Three-Way Permission + Data-Segregation Audit

### Source table

| Source | Endpoint | Auth model | Operator-visible? | Shape-compatible? | Segregation-safe? |
|--------|----------|------------|-------------------|-------------------|-------------------|
| (A) Proposals | `GET /api/v1/action-proposals/{batch_id}` | `require_api_key` | **YES** | **PARTIAL** — missing priority/title/actor (derivable); has batch_id, type, status, created_at | **DECISION REQUIRED** — see §A.3 |
| (B) Email queue | `GET /api/v1/admin/email-queue` | `require_admin` (role-based) | **NO** — admin-only | YES — shape has status, batch_id, subject, to | N/A pending authz decision |
| (C) DHL scan state | `GET /api/v1/dhl/scan-inbox` | `require_api_key` | **YES** | **PARTIAL** — scan-inbox triggers a live scan; the aggregator must use `email_intelligence_store` read-only cache instead | YES — scoped by AWB/batch |

### Source A: Proposals — detail

**Auth:** `require_api_key` — `routes_action_proposals.py:44` (router prefix `/api/v1/action-proposals`)

**Batch-scoped list:** `GET /{batch_id}` at `routes_action_proposals.py:755`. No global list endpoint exists.

**Cross-batch resolve exists:** `_resolve_proposal()` at `routes_action_proposals.py:1342-1369` already scans ALL `storage/outputs/*/audit.json` files to find a proposal by ID. This scan logic is the model for the aggregator's "all pending proposals" read — iterate all batch audits, collect `action_proposals` with `status == "pending_review"`.

**Proposal shape** (`routes_action_proposals.py:533-558`):
```
proposal_id, type, batch_id, status, reason, confidence, draft,
created_at, approved_by, approved_at, rejected_by, rejected_at,
reject_reason, email_id, queued_at, validation_failure_reason
```
`_annotate_can_approve()` at `routes_action_proposals.py:1295` adds a `can_approve` field to each proposal.

**Actionable signal:** `status == "pending_review"` — this is the only status that needs operator action. Approved/queued/sent/rejected are terminal or in-progress.

**Attribution:** Approve and reject use body fields (`approved_by`, `rejected_by`), NOT the X-Operator header. Per `routes_action_proposals.py:1411`: "X-Operator header is never trusted." The body attribution IS the audit trail — this is by design, not a missing guard.

#### A.3 — Cross-client boundary: DECISION FOR OPERATOR

Estrella handles multiple clients (ClearDiamonds, Verhoeven, Dream Ring, etc.) whose shipments are separate batches. A global inbox aggregating all pending proposals would show ALL clients' proposals together. There is no per-operator/per-client filter on the proposals system.

**VERDICT: Not a technical violation** (single operator team manages all clients; require_api_key is already the boundary). **BUT this is an explicit design decision that must be documented, not flattened silently.**

> **OPERATOR DECISION A3:** Do all authenticated operators have visibility across all client batches in the global inbox? If yes, document it. If different operators should see only their own clients' batches, a per-operator scope filter is needed before 2B.1 build begins.

**Working assumption (pending confirmation):** ALL authenticated operators see ALL clients' proposals. This matches current V1 behaviour (any admin can open any batch's proposals in batch.html).

---

### Source B: Email queue — detail

**Auth:** `require_admin` at `routes_admin.py:22`. `require_admin` is a role-based check (not just session or API key) — it verifies the user has the admin role.

**Shape:** `{ id, status, batch_id, type, to, subject, ... }` from `email_service.get_all_emails()`.

**ADMIN-ONLY BOUNDARY CONFIRMED.** Surfacing email queue items in a `require_api_key` inbox endpoint = privilege escalation for non-admin operators.

#### B.1 — Admin boundary: DECISION FOR OPERATOR

Two options:

**(B-i) Inbox is admin-only** (`require_admin`): All three sources visible. No privilege issue. Operators who aren't admins cannot use the inbox. Given the single-team operation, this may be acceptable.

**(B-ii) Inbox is operator-level** (`require_api_key`) with **conditional B inclusion**: Source B items are included when `check_session_or_redirect` reveals the user is an admin; omitted for non-admin operators. This is a role-conditional inclusion, not escalation.

**Recommendation:** **(B-ii)** — keeps the inbox operator-accessible while respecting the admin boundary on email queue items. The aggregator reads user role from the session (same mechanism as require_admin), and conditionally includes B items.

> **OPERATOR DECISION B1:** Admin-only inbox (B-i) or role-conditional email queue (B-ii)?

---

### Source C: DHL scan state — detail

**Auth:** `require_api_key` — operator-accessible.

**CRITICAL CONSTRAINT — NO SIDE EFFECTS IN READ:**
`GET /api/v1/dhl/scan-inbox` at `routes_dhl_clearance.py:1599` **triggers a live Zoho Mail scan** (`scan_for_dhl_customs_emails`). The aggregator MUST NOT call scan-inbox. A GET /api/v1/inbox must never fire a Zoho scan.

**Cached path:** `email_intelligence_store` at `service/app/services/email_intelligence_store.py` stores verified scan results in:
- `storage/email_intelligence/master_email_map.json` — flat map of all records
- `by_awb/`, `by_invoice/`, `by_mrn/`, `by_ticket/` indexes

**Gap:** `email_intelligence_store` has no `list_recent(limit=N)` public function. The master map can be read directly, but a clean `list_recent()` function should be added in 2B.1 as a pure read-only helper (no scan, no write).

**Shape:** each record has `awb`, `matched`, `last_scanned_at`, `linked_batches`, `recommended_next_action` — suitable for inbox items when `recommended_next_action` is non-null.

---

## PHASE 1 — Aggregator Design: GET /api/v1/inbox

### Auth model

Follows decision B1. **Recommended: require_api_key + role-conditional email queue.**

```python
GET /api/v1/inbox
Auth: require_api_key (session cookie fallback)
User role read from session → include email queue items if admin
```

If operator decides admin-only (B-i), change to `require_admin` throughout.

### Query parameters

```
?priority=urgent|high|normal|info|all    (default: all)
?type=proposal|email|approval|customs    (default: all)
?limit=50                                (default: 50; max: 100)
```

### Item shape

All items conform to:

```json
{
  "id":             "proposal-{proposal_id} | email-{email_id} | dhl-{awb}",
  "type":           "proposal | email | approval | customs",
  "priority":       "urgent | high | normal | info",
  "title":          "human-readable one-liner",
  "detail":         "batch/client/subject context",
  "age":            "ISO timestamp of creation",
  "actor":          "AI Bridge | email queue | DHL scanner | ...",
  "primary_action": "Approve | Reject | Review | Open",
  "linked_batch_id": "SHIPMENT_... | null",
  "actionable":     true,
  "endpoint":       "/api/v1/action-proposals/{id}/approve"
}
```

**All fields derivable from existing sources — no new DB columns required.** Derivation map:

| Field | From proposals (A) | From email queue (B) | From DHL cache (C) |
|-------|-------------------|---------------------|-------------------|
| id | `"proposal-" + proposal_id` | `"email-" + id` | `"dhl-" + awb` |
| type | `"proposal"` | `"email"` | `"customs"` |
| priority | derived from `type` (see §Priority) | `"high"` if pending | `"high"` if `recommended_next_action` non-null |
| title | derived from proposal `type` field | email `subject` | `"DHL scan: " + awb` |
| detail | `batch_id + " · " + reason[:80]` | `"to: " + to` | `"last scanned: " + last_scanned_at` |
| age | `created_at` | `queued_at` | `last_scanned_at` |
| actor | `"AI Bridge"` / proposal `type` | `"Email queue"` | `"DHL scanner"` |
| primary_action | `"Approve"` | `"Send"` (admin) | `"Scan"` (triggers explicit scan) |
| linked_batch_id | `proposal.batch_id` | `email.batch_id` | `linked_batches[0]` |
| actionable | `status == "pending_review"` | `status == "pending"` | `recommended_next_action != null` |
| endpoint | `/api/v1/action-proposals/{id}/approve` | `/api/v1/admin/email-queue/{id}/send` | `null` (scan is explicit, not inline) |

#### Priority derivation for proposals

```
"dhl_proactive_dispatch" → "urgent" (clearance deadline risk)
"dhl_clearance_inquiry"  → "urgent"
"customs_description_mismatch" → "high"
all others               → "normal"
```

### Strategy: Thin aggregator

For current item counts (order of tens across ~30 active batches), **thin aggregator** is the correct strategy. A materialized view would require a separate table, background writes, and cache invalidation logic — complexity not justified until item counts exceed ~500 regularly.

**Thin aggregator behaviour:**
1. Scan `storage/outputs/*/audit.json` → collect `action_proposals` where `status == "pending_review"`
2. Call `email_service.get_all_emails(limit=50)` → filter `status == "pending"` → include only if user is admin
3. Call `email_intelligence_store.list_recent(limit=20)` (NEW helper, pure read) → include records with `recommended_next_action != null`
4. Merge, sort by (priority desc, age asc), apply `?priority` and `?type` filters, slice to `?limit`

### Hard constraints

**1. NO SIDE EFFECTS IN READ**
The aggregator never calls `scan_for_dhl_customs_emails` or any function that makes an outbound Zoho API call. Source (C) data comes from `email_intelligence_store.list_recent()` — a file-system read only. A refresh button in the UI calls `GET /api/v1/dhl/scan-inbox` as a SEPARATE explicit operator action, not as part of the inbox GET.

**2. GRACEFUL DEGRADATION**
If any source read fails, return the others with a per-source marker:
```json
{
  "ok": true,
  "items": [...],
  "sources": {
    "proposals":   { "ok": true,  "count": 4 },
    "email_queue": { "ok": false, "error": "email_service unavailable" },
    "dhl_cache":   { "ok": true,  "count": 2 }
  }
}
```
The inbox must not return 500 when one source is down.

**3. EXISTING IDEMPOTENCY GUARDS HONOURED**
When the inbox's primary_action calls through to `POST /api/v1/action-proposals/{id}/approve`, that endpoint's guards remain the authority:
- Terminal status check: 409 if already queued/sent (`routes_action_proposals.py:798-803`)
- Auto-actor sentinel block (`routes_action_proposals.py:779-790`)
- Polish customs description gate for `dhl_proactive_dispatch` type
- `_assert_can_queue` guards (G1-G5) at the queue stage

The aggregator does not bypass these — it only constructs the URL for the item's `endpoint` field. The client calls that endpoint directly.

---

## PHASE 2 — Write-Action Scope + Snooze Decision

### Write-action table

| Action | Endpoint | Exists? | Attribution | Idempotent | Side-effectful | Verdict |
|--------|----------|---------|-------------|------------|----------------|---------|
| Approve | `POST /api/v1/action-proposals/{id}/approve` (body: `approved_by`) | YES | Body `approved_by` (not X-Operator header; by design — `routes_action_proposals.py:1411`) | YES — 409 on double-approve | Lifecycle transition only; approve ≠ send; NO auto-send | **IN SCOPE — 2B.2** |
| Reject | `POST /api/v1/action-proposals/{id}/reject` (body: `rejected_by`, `reason`) | YES | Body `rejected_by` | YES — 409 if already queued/sent | Lifecycle transition only; terminal status | **IN SCOPE — 2B.2** |
| Send (email queue) | `POST /api/v1/admin/email-queue/{id}/send` | YES | `require_admin` | Idempotent design (`routes_admin.py:70` docstring) | **SIDE-EFFECTFUL — triggers real SMTP send** | **GATED — pending SECURITY review in 2B.x** |
| Scan DHL (refresh) | `GET /api/v1/dhl/scan-inbox` | YES | `require_api_key` | Not idempotent (triggers scan) | **SIDE-EFFECTFUL — triggers Zoho scan** | **EXPLICIT OPERATOR BUTTON ONLY** — not inline in inbox GET |

#### Approve/Reject SECURITY note

The body-based attribution (`approved_by`, `rejected_by`) is intentional — the auto-actor sentinel guard at `routes_action_proposals.py:779` prevents system actors from approving. The inbox UI must pass the logged-in operator's identity in the body, not rely on a header. This means the inbox's approve action requires knowing the current user's display name — readable from `GET /auth/me`.

### Snooze decision

`POST /api/v1/inbox/{id}/snooze` does not exist. Options:

- **Client-side fake snooze:** REJECTED. State resets on refresh = dishonest UI. Violates the "no fake persistence" principle that governs this sprint.
- **Backend snooze table (new):** Valid, but its own scope and decision. Would need a new `inbox_snooze` table / JSON store, its own PR, and a TTL mechanism.
- **OMIT from v1 inbox:** Recommended. Snooze is a quality-of-life UX feature, not a triage requirement. The inbox works without it; items are actioned (approve/reject) or left pending.

> **SNOOZE DECISION:** Omit snooze from the v1 inbox. Surface as a follow-on when item volume justifies it.

---

## Open questions for operator

| # | Question | Blocks |
|---|----------|--------|
| **OQ-1** | **B1 — Admin boundary.** Inbox is require_api_key + role-conditional email queue (B-ii, recommended), or require_admin (B-i)? | 2B.1 auth model |
| **OQ-2** | **A3 — Cross-client visibility.** All authenticated operators see all clients' proposals in the global inbox? (Working assumption: YES — consistent with current V1 behaviour.) | 2B.1 build |
| **OQ-3** | **Snooze.** Confirmed omit from v1? | 2B.2 UI scope |
| **OQ-4** | **Send action in inbox.** Email queue "Send" is admin-only and SIDE-EFFECTFUL (real SMTP). Keep gated with a visual "Admin action →" link to the admin queue page, or include as a conditionally-shown button for admin users? | 2B.2 UI scope |

---

## Sprint tasks

### 2B.1 — Build GET /api/v1/inbox (backend PR)

**Files to create/modify:**
- `service/app/api/routes_inbox.py` — new; the aggregator endpoint
- `service/app/services/email_intelligence_store.py` — add `list_recent(limit=N)` pure read helper
- `service/app/main.py` — register inbox router
- `service/tests/test_inbox_contract.py` — new; contract tests

**Scope:**
- Auth per OQ-1 decision
- Thin aggregator (proposals scan + email queue conditional + DHL cache read)
- Graceful degradation per §1 hard constraints
- No side effects on GET
- Idempotency of action endpoints unchanged

**PR gate:** #422 (blocked), #430 (open) + this = 3 PRs at GATE 2 limit. Operator sequences.

### 2B.2 — Wire inbox-page.jsx (frontend PR)

**Files to modify:**
- `service/app/static/v2/inbox-page.jsx` — replace `INBOX_ITEMS` hardcoded array with real fetch from `GET /api/v1/inbox`; wire approve/reject actions with `approved_by`/`rejected_by` from session
- `service/app/static/v2/pz-api.js` — add `getInbox()`, `approveProposal()`, `rejectProposal()` wrappers

**Scope:**
- Remove MOCK badge when reads are live AND approve/reject persist
- Snooze omitted (OQ-3)
- Send action: gated or conditional per OQ-4

**Depends on:** 2B.1 merged and on main.

---

**HARD STOP.** This document is the deliverable. No endpoint, no wire, no PR. 2B.1 proceeds when operator resolves OQ-1 and OQ-2. OQ-3 and OQ-4 can be resolved during 2B.1 or at the start of 2B.2.
