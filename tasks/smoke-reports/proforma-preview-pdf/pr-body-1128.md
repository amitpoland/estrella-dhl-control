## Summary
- Unify commercial issue date, payment allowlist, Print vs Download PDF, explicit A4 row-packed capture (PR #1128 base).
- Extend the same commercial-document authority to Packing List + CMR:
  - Sales Packing → Client PO, quality, KT/colour, size, dia/col weights, qty, unit price
  - Purchase Packing → gross/net g + product_code identity fallback only
  - Descriptions → shared `product_descriptions` view-model
  - Origin → shared Product Master ISO (`normalize_origin_country`, India→`IN`); no invented IN for missing SKUs
  - HSN removed from printed commercial Packing List
- No second Invoice V2 renderer exists; Proforma preview remains the commercial printable. Posted PDF stays wFirma `document.pdf`.

## Test plan
- [x] Focused: commercial origin + packing SR/authority + preview PDF authority + wireframe slice-1 + soft-delete product_local — 141 passed
- [x] Pre-commit smoke — 63 passed
- [x] Draft evidence: #80 has Sales Packing fields (Client PO/quality/KT); #76 predates variant passthrough (data gap until reset); Product Master origin missing for these SKUs (honest `—`)
- [ ] Operator spot-check Preview → Packing List on Draft #80
- [ ] Deploy only after 7-agent gate (runtime UI + enrichment)

## Authority model
| Field | Authority |
|---|---|
| Issue date / payment | commercial draft (`payment_terms` / wFirma) — never `created_at` |
| Descriptions | `product_descriptions` |
| Product Code | purchase-lot / draft |
| Client PO, quality, KT, colour, size, stone wt, price, qty | Sales Packing → `editable_lines` |
| Gross/net g | Purchase Packing |
| Origin | `product_local.origin_country` → ISO |
