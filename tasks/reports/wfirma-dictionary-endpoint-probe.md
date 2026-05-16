# wFirma dictionary endpoint probe

**Date:** 2026-05-17
**Production credentials:** loaded from `C:\PZ\.env` (read-only)
**Method:** Bare `GET <module>/<action>` requests via `wfirma_client._http_request` with the minimal envelope `<api><{module}><parameters><page>1</page><limit>50</limit></parameters></{module}></api>`.

## Findings

| Candidate endpoint | HTTP | wFirma status | Conclusion |
|---|---|---|---|
| `invoiceseries/find`  | 200 | `CONTROLLER NOT FOUND` | **not available** |
| `proformaseries/find` | 200 | `CONTROLLER NOT FOUND` | **not available** |
| `invoice_series/find` | 200 | `CONTROLLER NOT FOUND` | **not available** |
| `languages/find`      | 200 | `CONTROLLER NOT FOUND` | **not available** |
| `translations/find`   | 200 | `CONTROLLER NOT FOUND` | **not available** |
| `currencies/find`     | 200 | `CONTROLLER NOT FOUND` | **not available** |
| **`series/find`**     | **200** | **`OK`**            | **AVAILABLE** — single endpoint returns ALL series (invoice + proforma + offer + spec + margin + …) |

## The one working endpoint: `series/find`

### Root + node shape

```
<api>
  <series>                <!-- outer collection (same name as module) -->
    <series>              <!-- each item -->
      <id>15827082</id>
      <name>domyślna</name>
      <template>FV [numer]/[rok]</template>
      <initnumber>1</initnumber>
      <visibility>visible</visibility>
      <type>normal</type>            <!-- discriminator -->
      <reset>yearly</reset>
      <used>2026-05-11 10:54:17.5910</used>
      <schema_suggestion>0</schema_suggestion>
      <created>2020-05-18 16:44:31</created>
      <modified>2020-05-18 16:44:31</modified>
    </series>
    ...
  </series>
  <status><code>OK</code></status>
</api>
```

### Observed `<type>` values

- `normal` — standard VAT invoice series
- `margin` — VAT-margin invoice series
- `proforma` — proforma series
- `offer` — offer / quotation series
- `spec` — specification series

### Identity + label mapping (verified against live response)

| Source XML field | Normalised dict key | Notes |
|---|---|---|
| `<id>`       | `id` | string (wFirma series id) |
| `<template>` | `label` | human-readable template (e.g. `FV [numer]/[rok]`) — what the operator should see in the dropdown |
| `<name>`     | `code` | short internal name (often `domyślna` / "default") |
| `<type>`     | `type` | discriminator — used to split into invoice vs proforma |

### Pagination

- `<parameters><page>N</page><limit>K</limit></parameters>` accepted at request root (same shape as `contractors/find`).
- For Estrella's wFirma account the response returns the full series catalog (small set, no pagination needed today).

### Unsupported / 404 behavior

- The five "not available" endpoints all return HTTP 200 with body
  `<api><status><code>CONTROLLER NOT FOUND</code></status></api>`.
- Parser must treat that response as "endpoint unavailable, baseline
  fallback applies" — NOT as an error.

## Implications for the dictionary refresh batch

| Dictionary | Live source | Baseline fallback |
|---|---|---|
| Invoice series  | `series/find` filtered to `type ∈ {normal, margin}` | placeholder (1 entry: `id=""`, label `"— Default series"`) |
| Proforma series | `series/find` filtered to `type == proforma` | placeholder (same shape) |
| Languages       | **no live endpoint** | 7-entry hardcoded list (PR #153) |
| Currencies      | **no live endpoint** | 6-entry hardcoded list (PR #153) |
| VAT modes       | n/a (not a remote catalog) | 3-entry hardcoded list |

## Implementation strategy

1. **One wFirma function** `fetch_series()` returns the parsed list with the `type` discriminator. No `fetch_invoice_series` / `fetch_proforma_series` as separate calls — wasteful and increases failure surface.
2. **Cache module** splits the parsed list by `type` and merges over the baseline.
3. **Refresh route** returns a per-dictionary source-state map so the operator UI can show `live` / `baseline` / `unavailable` per dictionary.
4. Languages + currencies remain on baseline indefinitely (no live endpoint).
5. **No persistence** in this batch — runtime in-memory cache only. Persistence-to-SQLite is a deferred follow-up.

## Sample XML for parser test fixtures

```xml
<?xml version="1.0" encoding="UTF-8"?>
<api>
    <series>
        <series>
            <id>15827082</id>
            <name>domyślna</name>
            <template>FV [numer]/[rok]</template>
            <type>normal</type>
            <visibility>visible</visibility>
        </series>
        <series>
            <id>15827088</id>
            <name>domyślna</name>
            <template>PROF [numer]/[rok]</template>
            <type>proforma</type>
            <visibility>visible</visibility>
        </series>
        <series>
            <id>15827091</id>
            <name>domyślna</name>
            <template>OF [numer]/[rok]</template>
            <type>offer</type>
            <visibility>visible</visibility>
        </series>
    </series>
    <status><code>OK</code></status>
</api>
```

Parsed normalisation:

```python
[
  {"id": "15827082", "label": "FV [numer]/[rok]",   "code": "domyślna", "type": "normal"},
  {"id": "15827088", "label": "PROF [numer]/[rok]", "code": "domyślna", "type": "proforma"},
  {"id": "15827091", "label": "OF [numer]/[rok]",   "code": "domyślna", "type": "offer"},
]
```

After type-filtering in the cache layer:

```python
invoice_series  = [{"id": "15827082", "label": "FV [numer]/[rok]"}]
proforma_series = [{"id": "15827088", "label": "PROF [numer]/[rok]"}]
```
