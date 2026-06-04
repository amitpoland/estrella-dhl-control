"""
Fixture: AWB 8400636576 — Estrella Jewels LLP supplier invoices.

Source: real invoice lines from EJL/26-27/233-236 (June 2026 shipment).
Used for regression testing of the ingestion parser and product classifier.

Summary (after last-noun-authority classification fix):
    RING    6 PCS
    PENDANT 7 PCS
    Total  13 PCS  (no STUD entries)

Freight totals:
    FOB       USD 12,277  (sum of all line_total values)
    Freight   USD     95
    Insurance USD     55
    CIF       USD 12,427

Note on prior misclassification: lines 233-1, 234-1, 235-3, 236-1
previously classified as STUD because re.search() matched "Stud" before
"RING". The last-noun authority rule (findall[-1]) corrects this.
"""
from __future__ import annotations

# Freight figures for this AWB (separate from the invoice line amounts).
AWB_8400636576_FREIGHT:   float = 95.0
AWB_8400636576_INSURANCE: float = 55.0

AWB_8400636576_BATCH = {
    "awb":          "8400636576",
    "freight_usd":   AWB_8400636576_FREIGHT,
    "insurance_usd": AWB_8400636576_INSURANCE,
    "invoices": [
        # ── EJL/26-27/233: 1 ring (LGD 14KT, Stud Jewell RING) ────────────
        {
            "invoice_number": "EJL/26-27/233",
            "items": [
                {
                    "description": "PCS, 14KT Gold,LGD Gold Stud Jewell RING",
                    "quantity":    1,
                    "unit_price":  279.0,
                    "line_total":  279.0,
                    "hsn_code":    "71131914",
                    # note: previously mis-classified as STUD before last-noun fix
                },
            ],
        },
        # ── EJL/26-27/234: 1 ring (LGD 14KT, space variant) ───────────────
        {
            "invoice_number": "EJL/26-27/234",
            "items": [
                {
                    "description": "PCS, 14KT Gold, LGD Gold Stud Jewell RING",
                    "quantity":    1,
                    "unit_price":  872.0,
                    "line_total":  872.0,
                    "hsn_code":    "71131914",
                },
            ],
        },
        # ── EJL/26-27/235: 7 pendants + 2 platinum rings ──────────────────
        {
            "invoice_number": "EJL/26-27/235",
            "items": [
                {
                    "description": "PCS, 18KT Gold,Plain Jewellery PENDANT",
                    "quantity":    7,
                    "unit_price":  650.0,
                    "line_total":  4550.0,
                    "hsn_code":    "71131911",
                },
                {
                    "description": "PCS, PT950 Platinum,Plain Jewel RING",
                    "quantity":    1,
                    "unit_price":  2555.0,
                    "line_total":  2555.0,
                    "hsn_code":    "71131921",
                },
                {
                    "description": "PCS, PT950 Platinum,Stud With Diam Jewel RING",
                    "quantity":    1,
                    "unit_price":  2830.0,
                    "line_total":  2830.0,
                    "hsn_code":    "71131923",
                    # note: previously mis-classified as STUD before last-noun fix
                },
            ],
        },
        # ── EJL/26-27/236: 2 rings (Stud DIA&CLS + Plain) ─────────────────
        {
            "invoice_number": "EJL/26-27/236",
            "items": [
                {
                    "description": "PCS, 14KT Gold,Stud Jewelry DIA&CLS RING",
                    "quantity":    1,
                    "unit_price":  516.0,
                    "line_total":  516.0,
                    "hsn_code":    "71131919",
                    # note: previously mis-classified as STUD before last-noun fix
                },
                {
                    "description": "PCS, 14KT Gold,Plain Jewellery RING",
                    "quantity":    1,
                    "unit_price":  675.0,
                    "line_total":  675.0,
                    "hsn_code":    "71131911",
                },
            ],
        },
    ],
    "invoice_totals": {
        "total_cif_usd": 12427.0,
    },
}
