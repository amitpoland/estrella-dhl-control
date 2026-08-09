#!/usr/bin/env python
"""Render the customer delivery-confirmation email to local files for review.

DEV TOOL — not part of the deployed runtime payload (``service/app`` + the
governed engine files). It imports the body builder directly and therefore has
no path to ``email_service.queue_email``, SMTP, or any customer address: it
structurally cannot send mail. Nothing is written outside ``--output-dir``.

Run it from ``service/`` so ``app.services`` resolves::

    cd service
    python scripts/preview_delivery_email.py --output-dir <a scratch directory>
    python -m http.server 9876 --directory <that same directory>
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.delivery_confirmation_service import (  # noqa: E402
    _delivery_email_bodies,
)

LINK = "https://pz.estrellajewels.eu/receipt/AbCd3fGh1JkLmN0pQrSt-uVwXyZ_01234567890a"

# name → kwargs for _delivery_email_bodies
VARIANTS = {
    "01-normal": dict(
        customer_name="Aurum Retail Sp. z o.o.",
        awb="9158478722",
        carrier_delivered_at="2026-08-08T12:04:00Z",
        delivery_location="WARSZAWA - PL",
    ),
    "02-long-company": dict(
        customer_name="Internationale Handelsgesellschaft für Edelmetalle GmbH",
        awb="9158478722",
        carrier_delivered_at="2026-08-08T12:04:00Z",
        delivery_location="FRANKFURT AM MAIN - DE",
    ),
    "03-no-location": dict(
        customer_name="Aurum Retail Sp. z o.o.",
        awb="9158478722",
        carrier_delivered_at="2026-08-08T12:04:00Z",
        delivery_location=None,
    ),
    "04-no-time-no-location": dict(
        customer_name="Aurum Retail Sp. z o.o.",
        awb="9158478722",
        carrier_delivered_at=None,
        delivery_location=None,
    ),
    "05-long-awb": dict(
        customer_name="Aurum Retail Sp. z o.o.",
        awb="JJD0002909008430073591234567890",
        carrier_delivered_at="2026-08-08T12:04:00Z",
        delivery_location="SAINT-LAURENT-DU-VAR - FR",
    ),
}

INDEX_ROW = (
    '<li><a href="{n}.html">{n}</a> &middot; '
    '<a href="{n}.txt">plain text</a></li>'
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--output-dir",
        required=True,
        help="Directory to write the preview artifacts into (created if absent).",
    )
    args = ap.parse_args()

    out = Path(args.output_dir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)

    rows = []
    for name, kwargs in VARIANTS.items():
        html, text = _delivery_email_bodies(
            kwargs["customer_name"],
            kwargs["awb"],
            LINK,
            carrier_delivered_at=kwargs["carrier_delivered_at"],
            delivery_location=kwargs["delivery_location"],
        )
        (out / f"{name}.html").write_text(html, encoding="utf-8")
        (out / f"{name}.txt").write_text(text, encoding="utf-8")
        rows.append(INDEX_ROW.format(n=name))
        print(f"wrote {name}.html ({len(html)} chars) + {name}.txt ({len(text)} chars)")

    (out / "index.html").write_text(
        "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\"/>"
        "<title>Delivery email preview</title></head><body "
        "style=\"font-family:system-ui,sans-serif;padding:24px\">"
        "<h1>Delivery-confirmation email — preview variants</h1><ul>"
        + "".join(rows)
        + "</ul></body></html>",
        encoding="utf-8",
    )
    print(f"\nindex: {out / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
