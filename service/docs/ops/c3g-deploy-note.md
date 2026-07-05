# C-3g deploy note — mirror-only product reads (Phase-C Wave 2)

**Slice:** C-3g (transitional dual-write cleanup + cache-passthrough retirement)
**Applies to:** the first production deploy that includes C-3g.
**Gate:** 7-agent deploy gate + CP4 (this note is the CP4 payload).

C-3g makes `wfirma_product_mirror` the SOLE identity source for every
business-route product read (proforma fiscal reads, PZ preview/create maps,
reverse maps). The C-1f cache fallback is gone — a product code without a
mirror row resolves as UNMAPPED. Service-charge emission metadata moved from
the legacy `wfirma_products` cache to `service_product_registry`
(proforma_links.db).

## Mandatory deploy-ritual steps (run AFTER robocopy, BEFORE service start)

1. **Mirror backfill re-run** (idempotent):
   ```python
   from pathlib import Path
   from datetime import datetime, timezone
   from app.services.reservation_db import backfill_product_authority
   sr = Path(r"C:\PZ\app\storage")
   print(backfill_product_authority(
       sr / "reservation_queue.db", sr / "wfirma.db", sr / "master_data.db",
       now_iso=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")))
   ```
2. **Check the collision count in the output.** `wfirma_id_collisions > 0`
   means two product_codes claim the same wFirma goods id — the loser gets an
   EMPTY mirror id and will resolve UNMAPPED. Each collision must be resolved
   by the operator (which code truly owns the goods id in wFirma) BEFORE
   going live. Known verify-tree example: cache rows `EJL/26-27/254-1` and
   `EJL/26-27/257-2` both claim goods id `99`.
3. **Service-charge registry backfill** (idempotent):
   ```
   python tools\backfill_service_product_registry.py --storage-root C:\PZ\app\storage
   ```
   Confirm `copied` lists the production freight/insurance rows (production
   has registered service products; an empty `copied` on prod is a STOP —
   investigate before starting the service, or freight lines will emit with
   the fallback label "freight" instead of the registered label).
4. Start the service; smoke: `GET /api/v1/proforma/service-products` must
   show the same mappings as before the deploy.

## Rollback

Standard rollback (previous SHA robocopy) fully restores the cache-fallback
behavior; no schema is dropped by this slice (the new
`service_product_registry` table is additive and ignored by old code).
