"""
Customer email brand shell — ONE presentation authority for customer-facing mail.

Semantic content (documents list, confirmation CTA, reminder preface) is supplied
by callers. Brand (Estrella identity, emerald/gold/cream card, typography, footer)
lives only here.

Variants:
  CUSTOMER_DOCUMENTS
  DELIVERY_CONFIRMATION
  DELIVERY_REMINDER
"""
from __future__ import annotations

from html import escape
from typing import Any, Dict, List, Optional, Sequence, Tuple

_EMAIL_STYLE = """
    body,table,td,a{-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%;}
    table{border-collapse:collapse;mso-table-lspace:0pt;mso-table-rspace:0pt;}
    @media only screen and (max-width:600px){
      .card{width:100% !important;}
      .pad{padding-left:16px !important;padding-right:16px !important;}
      .fact{display:block !important;width:100% !important;
            border-right:0 !important;border-bottom:1px solid #F0E5C8 !important;}
      .fact-last{border-bottom:0 !important;}
      .cta-link{display:block !important;padding-left:16px !important;padding-right:16px !important;}
      .h1{font-size:20px !important;}
    }
"""

_SANS = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
_MONO = "ui-monospace,SFMono-Regular,Menlo,Consolas,'Courier New',monospace"


def render_customer_email(
    *,
    variant: str,
    eyebrow: str,
    headline: str,
    preheader: str,
    greeting_name: str,
    body_html_blocks: Sequence[str],
    facts: Optional[Sequence[Tuple[str, str, bool]]] = None,
    cta_label: Optional[str] = None,
    cta_url: Optional[str] = None,
    footer_note: Optional[str] = None,
) -> Tuple[str, str]:
    """Return (html_body, plain_text) for a branded customer email."""
    who = escape(greeting_name or "Customer")
    eyebrow_e = escape(eyebrow or "")
    headline_e = escape(headline or "")
    pre_e = escape(preheader or "")
    sans = _SANS
    mono = _MONO

    fact_cells = []
    facts = list(facts or [])
    for idx, (label, value, is_mono) in enumerate(facts):
        last = idx == len(facts) - 1
        cls = "fact fact-last" if last else "fact"
        edge = "" if last else "border-right:1px solid #F0E5C8;"
        vfont = mono if is_mono else sans
        vbreak = "break-all" if is_mono else "break-word"
        fact_cells.append(
            f'<td class="{cls}" bgcolor="#FBF8F1" valign="top"'
            f' style="padding:10px 12px;background:#FBF8F1;{edge}">'
            f'<div style="font-family:{sans};font-size:8.5px;letter-spacing:0.12em;'
            f'text-transform:uppercase;font-weight:600;color:#8B6914;'
            f'padding-bottom:4px;">{escape(label).upper()}</div>'
            f'<div style="font-family:{vfont};font-size:12px;font-weight:700;'
            f'color:#0B3D2E;line-height:1.35;word-break:{vbreak};'
            f'overflow-wrap:anywhere;">{value}</div></td>'
        )
    facts_row = "".join(fact_cells)
    facts_table = ""
    if facts_row:
        facts_table = (
            '<tr><td class="pad" style="padding:0 24px 8px;">'
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"'
            ' style="border:1px solid #F0E5C8;border-radius:6px;overflow:hidden;">'
            f'<tr>{facts_row}</tr></table></td></tr>'
        )

    body_joined = "\n".join(body_html_blocks or [])

    cta_block = ""
    if cta_label and cta_url:
        cta_block = (
            f'<tr><td class="pad" align="center" style="padding:8px 24px 20px;">'
            f'<a class="cta-link" href="{escape(cta_url)}" '
            f'style="display:inline-block;background:#0B3D2E;color:#ffffff;'
            f'font-family:{sans};font-size:14px;font-weight:700;text-decoration:none;'
            f'padding:12px 22px;border-radius:6px;">{escape(cta_label)}</a></td></tr>'
        )

    footer = footer_note or (
        "Estrella Jewels · This message concerns your shipment. "
        "Please do not reply with payment card details."
    )

    html = f"""<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<meta http-equiv="X-UA-Compatible" content="IE=edge"/>
<meta name="color-scheme" content="light only"/>
<title>{headline_e}</title>
<style type="text/css">{_EMAIL_STYLE}</style>
</head>
<body style="margin:0;padding:0;background-color:#FBF8F1;color:#0F172A;font-family:{sans};">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;">{pre_e}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
 bgcolor="#FBF8F1" style="background-color:#FBF8F1;">
<tr><td align="center" style="padding:24px 12px;">
<table role="presentation" class="card" width="600" cellpadding="0" cellspacing="0" border="0"
 style="width:600px;max-width:600px;background-color:#ffffff;border:1px solid #E2E8F0;">

<tr><td class="pad" bgcolor="#0B3D2E"
 style="background-color:#0B3D2E;padding:20px 24px;">
  <div style="font-family:{sans};font-size:13px;letter-spacing:0.22em;text-transform:uppercase;
   font-weight:700;color:#C9A24B;">Estrella Jewels</div>
  <div style="height:1px;line-height:1px;font-size:0;background-color:#C9A24B;
   opacity:0.5;margin:10px 0 12px;">&nbsp;</div>
  <div style="font-family:{sans};font-size:9px;letter-spacing:0.18em;text-transform:uppercase;
   font-weight:600;color:#C9A24B;padding-bottom:6px;">{eyebrow_e}</div>
  <h1 class="h1" style="margin:0;font-family:{sans};font-size:18px;line-height:1.35;
   font-weight:700;color:#ffffff;">{headline_e}</h1>
</td></tr>

<tr><td class="pad" style="padding:20px 24px 8px;font-family:{sans};font-size:14px;line-height:1.55;color:#0F172A;">
  <p style="margin:0 0 12px;">Dear {who},</p>
  {body_joined}
</td></tr>

{facts_table}
{cta_block}

<tr><td class="pad" style="padding:8px 24px 20px;font-family:{sans};font-size:12px;line-height:1.5;color:#475569;">
  <p style="margin:0;">Best regards,<br/><strong>Estrella Jewels</strong></p>
</td></tr>

<tr><td style="padding:14px 24px;background:#F8FAFC;border-top:1px solid #E2E8F0;
 font-family:{sans};font-size:10px;line-height:1.45;color:#94A3B8;">
  {escape(footer)}
</td></tr>

</table>
</td></tr></table>
</body></html>
"""

    # Plain text
    text_parts = [f"Dear {greeting_name or 'Customer'},", ""]
    for block in body_html_blocks or []:
        # crude strip tags
        import re
        text_parts.append(re.sub(r"<[^>]+>", "", block).strip())
    text_parts.append("")
    for label, value, _ in facts:
        # value may already be escaped HTML text
        import re
        text_parts.append(f"{label}: {re.sub(r'<[^>]+>', '', value)}")
    if cta_label and cta_url:
        text_parts.extend(["", f"{cta_label}: {cta_url}"])
    text_parts.extend(["", "Best regards,", "Estrella Jewels"])
    return html, "\n".join(p for p in text_parts if p is not None)


def customer_documents_email(
    *,
    customer_name: str,
    doc_ref: str,
    document_labels: Sequence[str],
    optional_message_html: str = "",
) -> Tuple[str, str]:
    """Branded shell for customer document package send."""
    labels = [str(x) for x in document_labels if str(x).strip()]
    joined = ", ".join(labels) if labels else "documents"
    items = "".join(f"<li style='margin:0 0 4px;'>{escape(x)}</li>" for x in labels)
    blocks = [
        f"<p style='margin:0 0 12px;'>Please find attached the following document(s) "
        f"for <strong>{escape(doc_ref)}</strong>:</p>",
        f"<ul style='margin:0 0 12px;padding-left:18px;'>{items}</ul>",
    ]
    if (optional_message_html or "").strip():
        blocks.append(
            f"<p style='margin:0 0 12px;'>{optional_message_html.strip()}</p>"
        )
    blocks.append(
        "<p style='margin:0;'>If you have any questions, please do not hesitate to contact us.</p>"
    )
    return render_customer_email(
        variant="CUSTOMER_DOCUMENTS",
        eyebrow="Customer documents",
        headline=f"Documents for {doc_ref}",
        preheader=f"Your Estrella documents: {joined}",
        greeting_name=customer_name,
        body_html_blocks=blocks,
        facts=[
            ("Reference", escape(doc_ref), True),
            ("Documents", escape(joined), False),
        ],
    )
