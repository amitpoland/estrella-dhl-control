# RBAC Slice 2 — Definition (backend permission enforcement)

**Status:** DEFINED — waiting for explicit **OPEN SLICE 2**  
**Date:** 2026-08-11  
**Pinned main:** `C:\PZ-main` @ `42f8a1f93e8be5975d08d5d8afd4a0fa4463ca04`  
**Charter:** `.claude/campaigns/rbac-authority-consolidation.md` (§9–§12, Gate 3)  
**Prior Tier-0 review:** `reports/inspection/2026-08-11-rbac-tier0-security-review.md`  
**Authority owner:** backend authorization layer (`auth/dependencies` + route modules)  
**Consumers:** none new on FE — Slice 1 already consumes `/auth/me`; Slice 2 makes API deny match catalogue

> This document **defines** Slice 2. It does **not** authorize coding, PR open, or production deploy until the operator says **OPEN SLICE 2**.

---

## 1. Mission

Close **Gate 3** of the frozen three-gate contract:

| Gate | Owner | Slice |
|---|---|---|
| 1 Navigation | V2 `/auth/me` consumer | Slice 1 — done (undeployed) |
| 2 Direct URL | V2 shell gate | Slice 1 — done (undeployed) |
| 3 Backend API | `require_permission(...)` on Tier-0 writes | **Slice 2** |

Session users (and role-bound sessions) must receive **403** when a catalogue permission is missing — even if they forge a URL or call Postman. Hidden nav is not a security control.

---

## 2. In scope

1. **`require_permission(permission: str)` dependency** in `service/app/auth/dependencies.py`  
   - Reads permissions from the authenticated user (same derivation as `/auth/me` / `permissions_for_role`)  
   - Deny-by-default: missing permission → 403  
   - Must compose with existing session auth (`get_current_user` / `require_admin` / `require_role`) — **not** replace API-key automation blindly

2. **Tier-0 route bindings** from charter §9.1 — map each representative write to its required permission(s), **same PR as deny-path tests**

3. **Deny-path tests first** (charter §9.2):
   - logistics session → 403 on `pz.finalize` / `pz.export_wfirma` / `proforma.approve` / `proforma.convert`
   - crm / viewer → 403 on fiscal + inventory.execute + dhl.execute writes
   - accounts / admin → allow only where catalogue grants
   - API-key automation paths remain explicitly documented (break-glass); do not silently equate key = any role

4. **Per-domain `/security-review`** before binding Financial / Customs / Inventory writes (charter §12) — may be one review per sub-batch if Slice 2 is split

5. **Lesson O:** any auth-dependency tightening migrates affected tests in the **same** PR (no weakening routes to green tests)

---

## 3. Explicit out of scope / HOLD

| Item | Disposition |
|---|---|
| Production deploy of Slice 0/1/2 | **HOLD** — separate operator decision; never bundled with enforcement PRs' "done" |
| Changing PZ / proforma / wFirma **business** semantics | Off-limits (auth only) |
| `process_batch()` / landed-cost | Off-limits |
| Frontend permission catalogue / second ROLE_MATRIX | Forbidden |
| Collapsing API-key automation into human roles | Forbidden (charter §9.3) |
| Enabling `master_role_enforcement` silently | Forbidden — separate decision |
| Reclassifying every read endpoint in one PR | Forbidden |
| Widening logistics into fiscal finalize “because matrix said Full” | Forbidden (C2) |

---

## 4. Recommended sub-slices (optional sequencing inside Slice 2)

Do **not** mix production sync into any sub-slice.

| Sub-slice | Bind | Risk class | Gate |
|---|---|---|---|
| **2a** | Helper `require_permission` + unit/deny tests (no route change yet) | auth infra | `/security-review` light |
| **2b** | User/system admin routes → `users.admin` / `system.settings.admin` | admin | security-review |
| **2c** | DHL execute / AWB create / label | customs | **mandatory** security-review |
| **2d** | Proforma approve/convert + PZ finalize/export_wfirma + wFirma writes | financial | **mandatory** security-review |
| **2e** | Inventory execute/correct + warehouse scan/receipt | inventory | **mandatory** security-review |

Operator may open **2a only** first. Opening 2d/2e without prior security-review is a charter violation.

---

## 5. Acceptance criteria (Slice 2 complete when)

- [ ] `require_permission` exists and is the sole new session-user permission gate helper
- [ ] Every Tier-0 row in charter §9.1 either bound + tested **or** explicitly deferred with named follow-up (no silent gaps)
- [ ] Logistics cannot call finalize/export/approve/convert APIs (403) — deny tests green
- [ ] CRM cannot call `pz.*` write / `wfirma.*` write / `inventory.execute` / `dhl.execute` / `accounting.*` write / `users.*` (403)
- [ ] No FE catalogue; Master `ROLE_MATRIX` still non-authority
- [ ] No production deploy claimed as part of Slice 2 closure
- [ ] Rollback story: revert enforcement commit(s) restores prior role/api_key gates without data mutation

---

## 6. Preconditions before OPEN SLICE 2

| Precondition | Status @ `42f8a1f9` |
|---|---|
| Slice 0 merged + baseline CLEAR | YES |
| Slice 1 merged + baseline CLEAR | YES (`2026-08-11-rbac-slice1-postmerge-baseline.md`) |
| Catalogue + `/auth/me` contract stable | YES |
| Production deploy of Slice 0/1 | **HOLD** (not a blocker for defining/coding Slice 2, but must not be mixed into the same PR or “ship” claim) |
| Tier-0 security review (read-only) | YES — gaps documented; Slice 2 is the tightening |

---

## 7. First action after OPEN SLICE 2

1. Fresh worktree from `origin/main` tip  
2. `/context` + confirm pin SHA  
3. Implement **2a** (`require_permission` + tests) unless operator names a different sub-slice  
4. Do **not** run Deploy-PZ / robocopy / service restart as part of Slice 2

---

## Amendment hook

When Slice 2 coding starts, append an AMD block to the frozen charter naming the opened sub-slice and SHA pin. Do not silently edit §9 tables.
