import sys
sys.path.insert(0, 'service')

from app.services import name_normalization

cases = [
    "Muller",
    "AEROSKOBING",
    "Strasse",
    "thorsson",
    "Item 2026",
    "Multiple   Spaces",
    "Company Name,",
    "Kowalski Sp. z o.o.",
    "",
    "   "
]

print("=== PACKING CONTRACTOR ===")
for case in cases:
    result = name_normalization.packing_contractor_normalise_name(case)
    print(f'("{case}", "{result}"),')

print("\n=== PROFORMA CLIENT ===")
for case in cases:
    result = name_normalization.proforma_normalize_client_name(case)
    print(f'("{case}", "{result}"),')

print("\n=== CUSTOMER RESOLUTION ===")
for case in cases:
    result = name_normalization.customer_resolution_normalize_name(case)
    print(f'("{case}", "{result}"),')