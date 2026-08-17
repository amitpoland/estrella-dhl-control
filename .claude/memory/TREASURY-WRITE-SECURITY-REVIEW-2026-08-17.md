# Treasury Write Security Review — 2026-08-17

**Scope:** `routes_treasury.py`, `treasury_db.py`, `bank_statement_import.py`, auth/RBAC, audit  
**Campaign:** `feat/accounting-cfo-mis` @ `C:\PZ-wt\accounting-cfo-mis`  
**Verdict:** **PASS_WITH_FIXES** (MEDIUM findings remediated in-campaign)

---

## Authorization model (validated)

| Surface | Auth | Write gate |
|---------|------|------------|
| GET `/balances`, `/meta` | `reports.financial` | n/a |
| POST manual / import / daily-close | `reports.financial` + session role `admin\|accounts` | API key alone cannot write |

No CRITICAL/HIGH auth bypass, IDOR, SQL injection, or path traversal found.

---

## Findings

### TRE-001 MEDIUM — Non-atomic import confirm → REMEDIATED

**Was:** `confirm_import_batch` called `insert_balance_snapshot` which opened a separate connection and committed per row; concurrent confirm could double-insert.

**Fix:**
- `insert_balance_snapshot(..., conn=optional)` participates in caller transaction
- Conditional `UPDATE … WHERE status='PREVIEW'` with `rowcount != 1` abort
- Already-CONFIRMED still refused

### TRE-002 MEDIUM — Hardcoded operator `"api"` → REMEDIATED

**Was:** All write paths attributed operator/closed_by/uploaded_by as `"api"`.

**Fix:** `_operator_from_user(user)` from session (`email` / `username` / `id`) on manual, import preview/confirm, and daily-close.

---

## Residual risks (accepted / backlog)

| ID | Severity | Note |
|----|----------|------|
| TRE-003 | LOW | Cookie-session CSRF — inherited app pattern, not Treasury-specific |
| TRE-004 | LOW | `correction_of_id` has no FK — integrity only |
| TRE-005 | LOW | Manual duplicate POSTs append by design (latest wins on read) |
| TRE-006 | INFO | Route-level RBAC regression suite for treasury still thin — recommend mirroring `test_reports_financial_permission.py` |

---

## Inventory webhook note (out of Treasury, campaign-linked)

Stock quantity consumer remains **BLOCKED BY OI-10** until one real `Produkty » Zmiana ilości` payload is captured. Router now classifies `Produkty.*` / `Towary.*` as STOCK (no invoice fetch). Do not update inventory from undocumented assumptions.

---

## Production gate

Treasury **writes** may proceed only after this review + remediations land in the deploy SHA. Treasury **reads** (balances for CFO Liquidity) are lower risk and already gated by `reports.financial`.
