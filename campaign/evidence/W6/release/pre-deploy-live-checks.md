# W6 — pre-deploy live-check baseline

Captured against CURRENT production (SHA 3748daae) before any sync, so the three
post-deploy checks have something to be compared against rather than merely passing.

Date: 2026-08-22T00:48:18Z  Host: 127.0.0.1:47213 (PZService)

## /api/v1/health
  HTTP 200
  keys: ['detail', 'engine', 'environment', 'status']

## /api/v1/dhl/logistics/projection?direction=all&view=active
  HTTP 200
  keys: ['analytics', 'authority', 'count', 'data_gaps', 'filters_applied', 'generated_at_utc', 'generated_at_warsaw', 'intelligence', 'kpis', 'rows', 'timezone']

## /api/v1/carrier/status
  HTTP 200
  keys: ['carrier_api_status', 'carrier_plt_status']

The API key was read from C:\PZ\.env into the shell and is not reproduced here.
