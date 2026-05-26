# Sprint 15 — Ledgers V2

**Campaign:** Atlas-V2  
**Sprint:** 15 of 23  
**Branch:** `atlas-v2/sprint-15-ledgers-v2`  
**Dependency:** Sprint 14 merged (Accounting Hub establishes ledger endpoints)  
**New file:** `service/app/static/ledgers-v2.html`  
**URL:** `/dashboard/ledgers-v2.html`  
**Design source:** `design-files/ledgers-page.jsx`

---

## Authority Boundary

```
OWNS:  Read-only client/supplier statements, aging buckets, balance views,
       per-party transaction history sourced from wFirma, PLN/EUR formatting
NEVER: Manual ledger edits, payment posting, invoice correction, write to wFirma,
       any mutation of ledger state
```

Source of truth: wFirma. Display only. No reconciliation actions on this page —
those live in finance workflows that this page does not host.

---

## Page Purpose

Today balances and aging are computed ad-hoc by Tejal pulling from wFirma. Ledgers V2
consolidates that view: pick a party, see balance, aging buckets, statement lines, and
download a PDF statement (read-only artifact).

---

## APIs

| Endpoint | Purpose |
|----------|---------|
| `GET /api/v1/ledger/clients` | Client list with balance | (Sprint 14) |
| `GET /api/v1/ledger/suppliers` | Supplier list with balance | (Sprint 14) |
| `GET /api/v1/ledger/{party}/transactions?from=&to=` | Per-party transactions | NEW |
| `GET /api/v1/ledger/{party}/aging` | Aging bucket breakdown | NEW |
| `GET /api/v1/ledger/{party}/statement.pdf` | PDF download | NEW (generated artifact — Lesson G applies) |

**Lesson G binding:** statement PDF download endpoint MUST set `Cache-Control: no-store,
no-cache, must-revalidate, max-age=0`. Statement generation must be validate-then-rollback
overwrite-safe. Regression test must pin both.

---

## Page Structure

- PageHeader (h1: "Ledgers", subtitle: "Client & Supplier statements")
- Tab: Clients | Suppliers
- Left rail: party search + balance list
- Main: selected party transactions table + aging bucket strip + "Download statement (PDF)" Btn
- SessionBanner for wFirma-down

---

## Mandatory Agents

Same 15-agent sequence as Sprint 14, with these emphases:
- `backend-safety-reviewer` verdict: zero writes
- `testing-verification` adds Lesson G regression test for statement PDF (no-store + validate-then-rollback)
- `wfirma-integration` verifies ledger queries map correctly to wFirma reports

---

## Acceptance Criteria

1. Page loads, no console errors, no 4xx
2. Client tab and Supplier tab both functional
3. Selecting party shows transactions + aging
4. Statement PDF downloads with `Cache-Control: no-store` headers (Lesson G verify)
5. Empty state when party has no transactions
6. SessionBanner on auth/wFirma errors
7. All testids present
8. Zero writes (verified via Network panel)
9. Rollback: remove file from C:\PZ\app\static\

---

## `/run` Prompt

```
/run

Campaign: Atlas-V2 | Sprint 15 — Ledgers V2
Branch: atlas-v2/sprint-15-ledgers-v2 (from origin/main; Sprint 14 must be merged)

STACK CONSTRAINTS: (same as Sprint 14 header — read frontend-design.md, vanilla HTML+Babel, no TS/Tailwind, follow proforma-v2.html pattern)

Design reference: git show origin/atlas-v2/source-bundle:design-files/ledgers-page.jsx

TASK: Create service/app/static/ledgers-v2.html — read-only ledger viewer.

AUTHORITY:
OWNS: read display of client/supplier ledgers, aging, statement PDF download
NEVER: any write, payment posting, invoice correction, ledger mutation

LESSON G BINDING (mandatory):
- Statement PDF download MUST emit Cache-Control: no-store, no-cache, must-revalidate, max-age=0
- Statement generation must be validate-then-rollback (validate before audit pointer update)
- Regression test required: test_ledger_statement_cache_and_overwrite.py

BACKEND: add ledger transaction + aging + statement-PDF read endpoints.
backend-safety-reviewer verdicts no-write compliance.

GATE 2 + agent sequence + test baseline: same as Sprint 14.

End with /deploy after merge.
```
