# TASK_STATE.md

## Current task

- **Task:** B-014 Decision B — port Reset ALL + re-open + deep-link to V2
- **Status:** `IN_PROGRESS` (implement → PR → 7-agent → App-deploy → RO remeasure)
- **Branch:** `fix/b014-v2-reset-reopen-deeplink` (from main `9fa7126d`)
- **Authority:** same `POST .../re-open` + `POST .../reset-from-sales-packing` — no new financial path
- **Safety:** no live approve/convert/post/reset/re-open/wFirma writes in prod browser verify
- **Do not:** activate V1→V2 hard cutover without explicit operator approval
- **Prior closed:** #1231 DEPLOYED; queue otherwise exhausted
