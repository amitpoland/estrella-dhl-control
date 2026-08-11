# Slice 1 — fail-closed shell repair

Measured pre-fix point: `9f8c7538`. Baseline / true parent: `e4fd91cc`.

## The defect

Slice 1 shipped two authority implementations in behaviour. When
`authority-consumer.js` was unavailable the shell fell back to an *inline* gate
that answered "allowed". For authorization code that resilience is backwards:
losing the authority consumer must make the shell **less** capable, never more.

Demonstrated, not inferred — logged-in CRM user, `authority-consumer.js`
blocked at the network layer, direct request to `/v2/accounting`:

```json
{ "url": ".../v2/accounting", "hasAuthorityConsumer": false,
  "navShowsAccounting": false, "bodyMentionsLedger": true, "fails_open": true }
```

The sidebar correctly hid Accounting, so the shell *looked* locked down while
the protected page was on screen. Hidden navigation is not a security gate.

## Root causes (two, both in `static/v2/index.html`)

1. **Degraded inline gate.** `pageIsAllowed = AC.pageIsAllowed || function () { return true; }`,
   plus ternaries around `normalizeAuthority` / `resolveGateTarget`, and a
   popstate guard `if (!authority || authorityStatus === 'fallback') return true;`
   — the branch named fail-closed was the one that allowed.

2. **Boot page derived from the URL.** `page` was seeded from `location` at
   `useState` time, so the requested protected page rendered for one frame
   before any gate ran. This is why the first repair attempt still leaked:
   closing the effect path alone does not help when the *initial paint* already
   carries the page. The location was never lost — `applyAuthorityGate` re-reads
   it with `parseV2Location()` and lets `resolveGateTarget` decide.

## The repair

`AC_READY` capability check gates every authority decision. Without the
canonical consumer there is no inline substitute: `pageIsAllowed` returns
`false`, no page mounts, session is cleared and the browser lands on `/login`.
`page: ''` matches no content block, so the deny state is genuinely empty
rather than merely redirected — the redirect is cleanup, never the gate.
`fallback` and `loading` are deny states. A denied page falls back to
`default_page` only when that page is itself allowed.

No frontend permission catalogue, no role matrix, no change to `/auth/me`,
`permissions.py`, Tier-0 routes or the Master `ROLE_MATRIX`. Backend
`/auth/me` + `authority-consumer.js` remain the sole authority.

## Proof

| Check | Result |
|---|---|
| Fault injection — consumer blocked, `/v2/accounting` | **no protected content in any sample**, lands `/login` (`probe_consumer_missing.py`) |
| Slice 1 acceptance, 5 scenarios | **5/5** |
| A/B mount `e4fd91cc` vs repaired | both `MOUNT_OK`, `rootChildren: 1`, **zero pageerrors** |
| Focused Slice 0 + Slice 1 | **43 passed** (37 pre-existing + 6 new pins) |
| Mutation test of the new pins | 4/4 reintroduced defects **CAUGHT** |

The fault-injection probe samples continuously from navigation start rather
than snapshotting once at the end, so a transient pre-redirect render cannot
hide. That is what caught root cause 2.

## Not a Slice 1 defect

`test_rbac_structural_allowlist.py` has 2 failures — two bare-auth mutation
routes from PR #1186 outside the allowlist:

```
routes_carrier_actions.py:POST:/{batch_id}/epod/{tracking_ref}/fetch
routes_carrier_actions.py:POST:/{batch_id}/waybill-doc/{tracking_ref}/fetch
```

Identical at baseline `e4fd91cc`. Production baseline reds, already on `main`.
To be handled as a separate cleanup PR before the seven-agent gate — **not**
repaired inside this branch.
