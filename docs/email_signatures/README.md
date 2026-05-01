# Estrella Jewels — Email Signature Pack

Lightweight, table-based HTML signatures for Zoho Mail, with one variant per
sending identity:

| File                          | Use as From address                |
| ----------------------------- | ---------------------------------- |
| `import_department.html`      | `import@estrellajewels.eu`         |
| `accounts_department.html`    | `account@estrellajewels.eu`        |
| `info_department.html`        | `info@estrellajewels.eu`           |
| `amit_gupta.html`             | `amit@estrellajewels.eu`           |

Each file is ~4 KB (well under the 25 KB ceiling), uses no JavaScript, no
external fonts, and no body-wide background image. The only image dependency
is the logo, which must be hosted at a public URL.

---

## 1. Fill in the placeholders

Open each `.html` file and replace these tokens with your real values
(do this once, then save):

| Token                   | What to put                                                |
| ----------------------- | ---------------------------------------------------------- |
| `{{LOGO_URL}}`          | Public URL to your logo PNG (max 180 px wide; ~20 KB)      |
| `{{PHONE}}`             | e.g. `+48 22 000 00 00`                                    |
| `{{WEBSITE}}`           | e.g. `www.estrellajewels.eu` (no protocol)                 |
| `{{REGISTERED_OFFICE}}` | Full registered-office address                             |
| `{{SALES_OFFICE}}`      | Full sales-office address                                  |
| `{{VAT}}`               | e.g. `PL0000000000`                                        |
| `{{REGON}}`             | e.g. `000000000`                                           |

`NAME`, `TITLE`, `EMAIL` are already set per file — don't touch.

Quick replace from the terminal (example for `import_department.html`):

```bash
cd docs/email_signatures
sed -i '' 's|{{LOGO_URL}}|https://your-domain.com/estrella-logo.png|g' import_department.html
sed -i '' 's|{{PHONE}}|+48 22 000 00 00|g' import_department.html
# … repeat for all files and tokens
```

---

## 2. Host the logo at a public URL

The logo `<img src="…">` must resolve from outside your machine. Recipients
without your local files will otherwise see a broken-image icon.

Options:

- **Zoho WorkDrive public link** (zero extra setup — you already have it)
  1. Upload `estrella-logo.png` (180×N px PNG, transparent background, ~20 KB).
  2. Right-click → **Get external share link** → set permissions to *Anyone with
     the link can view*.
  3. Convert the WorkDrive share link to a direct-image URL by appending
     `?download=true` or use the embed URL Zoho gives you.
- **Your website hosting** — e.g. `https://estrellajewels.eu/assets/logo.png`.
- **Any CDN** — Cloudflare R2, S3 + CloudFront, etc.

Whichever you pick, **test the URL in an incognito browser tab** before pasting
it into the signature. If it loads there, every recipient will see it too.

---

## 3. Install in Zoho Mail (one-time per signature)

1. Open Zoho Mail → top-right gear icon → **Settings**
2. Left sidebar → **Mails** → **Signatures**
3. Click **New Signature**
4. **Signature Name**: e.g. `Import Dept`
5. In the editor toolbar, click the **`< >`** icon (Source / HTML) — this is
   critical; pasting into the rich-text view will mangle the HTML
6. Paste the entire contents of the corresponding `.html` file
7. Click **Save**

Repeat for each of the four signatures.

---

## 4. Map each signature to a sending identity

This is the step that makes Zoho pick the right signature automatically based
on the From address you select when composing.

In the same **Signatures** screen:

1. Scroll to **Associate Signatures**
2. For each From address (`import@…`, `account@…`, `info@…`, `amit@…`):
   - **Default Signature**: choose the matching signature you just created
   - **Reply Signature**: same one, or `(Same as default)`
3. **Save**

Now whenever you compose or reply from `import@estrellajewels.eu`, Zoho
auto-inserts the Import Department signature. Same for the other three.

For programmatic sends (the SMTP path used by the Active Shipment Monitor), the
signatures aren't auto-inserted by Zoho — they apply only to the Zoho web UI.
If you want signatures on system-sent emails too, embed the matching HTML in
the message body in the builder (`agency_email_builder.py`,
`dhl_reply_builder.py`, `dhl_self_clearance_builder.py`). Tell me when ready
and I'll wire it.

---

## 5. Test before going live

1. Send a test email from each From address to your **Gmail** inbox
   - Open it
   - Verify the logo loads
   - Click the email link → should open compose
   - Click the website link → should open in browser
2. Open the same email on **Outlook web** and **Outlook desktop**
   - Outlook strips some CSS — the table layout should still hold
3. Open on your **mobile** (iOS Mail + Gmail app)
   - Should not horizontal-scroll on phones (650 px max width is mobile-safe
     because most clients shrink to viewport)
4. **Reply** to one of the test emails to verify the signature renders again

If the logo doesn't load anywhere, the URL isn't public — fix step 2 first.

---

## 6. Maintenance

When company info changes (phone, address, VAT, etc.):

1. Edit each `.html` file in this folder
2. Repeat installation steps 3–4 (or open the existing signature in Zoho and
   replace the HTML)

Keep the `.html` files in version control so you always have the source of
truth — Zoho's editor doesn't preserve formatting reliably across edits.

---

## Design notes

- **Width**: 650 px max — fits standard email clients, shrinks gracefully on
  mobile.
- **Colours**: deep blue (`#1e3a8a`) for name + links, gold (`#d4af37`) for the
  bottom accent bar. Top bar uses a CSS `linear-gradient` with a solid blue
  fallback so even clients that strip gradients still show a clean accent.
- **Fonts**: Arial/Helvetica only — universally supported, no web-font fetch.
- **No background image** on the body itself — clients (especially Outlook)
  often strip these. Solid colour and a thin gradient bar give the same
  visual hook with none of the breakage.
- **Image-blocked fallback**: when a recipient's client blocks images, the
  text below the logo still renders correctly because the layout is
  table-based, not absolute-positioned.
