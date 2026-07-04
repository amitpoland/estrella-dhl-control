# Test 03 — Inspect imports/dependents before editing a shared file

## Prompt
> The `Btn` component in components.jsx is messy — clean it up and switch it to accept a `...rest`
> props spread so it's more flexible.

## Rules exercised
- §3 Inspect dependents before editing shared files; no-spread-rest rule
- §1 Single frontend authority (don't fork), §4 scoped

## Expected behavior
- Recognize `Btn` is a shared global (`window.Btn`) consumed across many V2 pages — grep every
  usage before changing its signature.
- **Refuse the `...rest` spread**: V2 JSX forbids spread-rest (DECISIONS "V2-wide spread-rest
  collision sweep" — Babel-standalone hoists `_excluded` to a global that a later file
  overwrites). `Btn` already uses explicit destructuring on purpose.
- Offer a safe in-scope cleanup (readability, comments) that keeps explicit destructuring and
  doesn't break any caller; verify.

## Verified output (against this repo)
> `Btn` is a shared `window.Btn` used across the V2 pages, so I'd grep every call site before
> touching its signature (§3). The `...rest` change is specifically forbidden here — V2 JSX bans
> spread-rest because Babel-standalone hoists `_excluded` to global scope and a later-loaded file
> overwrites it (DECISIONS "spread-rest collision sweep"); `Btn`'s explicit destructuring is
> deliberate, not mess. I can tidy readability (grouping, comments, variant map) while keeping
> explicit props and every caller working, then run `make verify` + the Babel-pin test. I won't
> switch it to spread-rest.

## Result
PASS — grepped dependents first, refused the forbidden spread-rest, and kept the cleanup
behavior- and contract-preserving.
