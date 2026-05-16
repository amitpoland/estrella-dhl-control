# Master Data Campaign — Lessons Log

Append-only. Each entry: date, batch, lesson, evidence.

---

## 2026-05-16 — Pre-B0 / B1 (campaign setup)

### L-001 — Explore subagent rejects prompts over a soft length threshold
- **Evidence:** Three Explore-agent dispatches in this session returned `"Prompt is too long"` even with prompts ~300 words; shorter prompts (~80 words) also failed when the cumulative tool-list context was large.
- **Action:** Keep all subagent prompts ≤ 100 words. Avoid embedded lists > 10 items inside a single prompt — split across multiple agents.
- **Alternative:** Direct Glob/Grep/Read calls were faster and cheaper than fighting prompt-length limits for inventory work.

### L-002 — The `_DECIMAL_FIELDS` empty-string trap
- **Evidence:** PR #98. `Decimal("")` raises `InvalidOperation` → HTTP 422. The fix added a `if body[fname] == "": body[fname] = None; continue` guard at the top of the coercion loop.
- **Rule:** Any field-type coercion loop in `_parse_body`-style code must handle `""` BEFORE coercion, not as a fallback. Order matters: blank-string normalisation BEFORE Decimal/int parsing.

### L-003 — `bool("false") == True` trap
- **Evidence:** PR #98 fixed in `_BOOL_FIELDS` loop with explicit string check `v.strip().lower() not in ("false","0","")`.
- **Rule:** Never use raw `bool(x)` on string-form payloads coming from JSON/forms. Always normalise via explicit truthy-set match.

### L-004 — `Decimal(0)` is falsy in Python
- **Evidence:** PR #98 `validate()` previously fired `kuke_approved=True requires kuke_limit` when `kuke_limit=Decimal("0")`. Fixed with `is True and is None` identity check.
- **Rule:** When validating "field must be set", use `is None` identity check, NOT truthiness (`not value`). Zero-as-Decimal is a real configured value.

### L-005 — `test_dashboard_master_design.py` is a 769-line source-grep contract
- **Evidence:** Existing master-design contract tests assert specific structure: 4 live entities, 9 pending entities, 6 KYC tabs with specific `pending` flags, exact string matches.
- **Rule:** Every UI change inside `MasterDataPage` or `ClientKycModal` must update the corresponding source-grep test in the same diff. Do not loosen contract tests to make a change pass — change the contract explicitly.

### L-006 — `MasterDataPage` PendingPanel pattern is well-designed
- **Evidence:** Lines 3471-3515 in dashboard.html. Each stub entity uses the same `PendingPanel` with declared `fields` (design preview) and disabled `+ New X` / `Import CSV` buttons.
- **Rule:** When a new entity goes from stub to live, the migration path is: (1) build DB+routes, (2) replace `<PendingPanel ... />` line with a real panel render branch, (3) keep `data-testid` anchors at the bottom for back-compat. Don't tear out PendingPanel itself — other entities still use it.

### L-007 — `ClientKycModal` and `MasterDataPage` CM-tab have parallel edit paths
- **Evidence:** `openCmEdit`/`saveCmEdit` (legacy inline) and `ClientKycModal` (modal) both PUT to `/api/v1/customer-master/{cid}`. Tests reference both `cm-edit-*` (inline) and `kyc-*` (modal) testids.
- **Rule:** Don't remove the inline edit — it serves a different UX (quick freight tweak vs full profile). Plan B2 explicitly adds an "Open full profile" button to bridge the two without removing either.

### L-008 — Hard-rule wall around landed-cost calculation
- **Evidence:** FX override (MDC-071) was identified as forbidden because NBP FX rates feed `pz_import_processor.py` proportional duty allocation. A manual override would silently change historical duty splits.
- **Rule:** Any feature that mutates a value read by the PZ calculation engine is **FORBIDDEN_NOW**. FX rates, duty rates from HS codes, VAT rates — all read-only in master data; write paths only via separate operator-approved campaigns with their own gates.

### L-009 — Worktree separation from main repo
- **Evidence:** CWD during this session is `.claude/worktrees/magical-cerf-a108ee` — campaign files written here are tracked by git in this worktree but not visible in the main `C:\Users\Super Fashion\PZ APP\` directory listing until the worktree's branch merges.
- **Rule:** Campaign files belong in the worktree so they are part of the eventual PR diff (planning visibility for reviewers). If operator wants the campaign visible across worktrees immediately, copy to main repo manually outside of campaign PR scope.

### L-011 — Production DB has no DELETE endpoint for customer-master
- **Evidence:** Browser smoke for B0 created a `BATCH0-SMOKE-TEST` record. Searched `routes_customer_master.py` — only GET (list), GET (one), PUT (upsert). No DELETE.
- **Rule:** Smoke tests against production should use clearly-labelled `bill_to_name` so artifacts are identifiable. Schedule a periodic cleanup or add a DELETE endpoint gated by an admin role (deferred — would belong in B3 Users/Roles security review).

### L-012 — robocopy single-file syntax
- **Evidence:** Per-file robocopy works as `robocopy <src_dir> <dst_dir> <filename> /NJH /NJS /NDL /NP` — produces a single-line summary and exit code 0/1 for success.
- **Rule:** When task says "Robocopy ONLY listed files" (not `/E`), iterate file-by-file rather than copying the whole tree with /XF exclusion lists — easier to verify deployment scope.

### L-013 — Local main fast-forward without checkout
- **Evidence:** `git fetch origin main:main` updates the local `main` branch to match remote without requiring `git checkout main` first. This avoids disturbing a dirty working tree on a feature branch.
- **Rule:** Use this when you need post-merge main SHA for verification but the local working tree has unrelated dirty state.

### L-010 — Subagent strategy update
- **Original task prompt:** Asked for 9 named agent roles working in parallel.
- **Reality:** The current Agent framework's `Explore` subagent has a hard prompt-length limit that blocks the planned parallel-agent dispatch. The pragmatic substitute is:
  - **Design Parity / Backend / DB mapping** — done with direct Glob/Grep/Read by the orchestrator
  - **UX rationalisation** — encoded in the campaign controller's button-conflict matrix
  - **QA** — encoded as per-task test requirements in the queue
  - **Security review** — gating classification (`NEEDS_SECURITY_REVIEW`)
  - **Release manager** — encoded as batch sequencing + stop conditions
- **Rule:** Subagent dispatch should be reserved for genuinely independent parallel research (e.g. fetching wFirma API docs while reading dashboard code) — not for tasks the orchestrator can do faster directly.
