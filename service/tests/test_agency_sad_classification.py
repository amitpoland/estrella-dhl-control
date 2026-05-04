"""
test_agency_sad_classification.py — Unit tests for agency_sad_reply detection
in classify_event_type().

Coverage:
  1. Attachment-based detection: agency + SAD/PZC attachment → agency_sad_reply
  2. Text-based detection: agency + SAD keyword in subject/body, no attachments → agency_sad_reply
  3. No false positive: external sender, no SAD evidence → "other"
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.email_thread_mapper import classify_event_type


# ── 1. Attachment-based detection ────────────────────────────────────────────

def test_agency_sad_reply_detected_by_attachment():
    """Agency email with a SAD document attachment → agency_sad_reply."""
    atts = [{"filename": "SAD_123456789.pdf", "document_type": "sad"}]
    ev = classify_event_type(
        direction="incoming",
        sender_role="agency",
        subject="Przesyłam SAD",
        body="W załączeniu SAD.",
        attachments=atts,
    )
    assert ev == "agency_sad_reply", f"Expected agency_sad_reply, got: {ev}"


def test_agency_sad_reply_detected_by_pzc_attachment():
    """Agency email with a PZC document attachment → agency_sad_reply."""
    atts = [{"filename": "PZC_2824111912.pdf", "document_type": "pzc"}]
    ev = classify_event_type(
        direction="incoming",
        sender_role="agency",
        subject="Dokumenty celne",
        body="",
        attachments=atts,
    )
    assert ev == "agency_sad_reply", f"Expected agency_sad_reply, got: {ev}"


# ── 2. Text/keyword-based detection ──────────────────────────────────────────

def test_agency_sad_reply_detected_by_text_sad():
    """Agency email with 'SAD' in subject, no attachments → agency_sad_reply via keyword."""
    ev = classify_event_type(
        direction="incoming",
        sender_role="agency",
        subject="SAD gotowe do odbioru",
        body="",
        attachments=[],
    )
    assert ev == "agency_sad_reply", f"Expected agency_sad_reply, got: {ev}"


def test_agency_sad_reply_detected_by_text_mrn():
    """Agency email containing 'mrn' in body → agency_sad_reply via keyword."""
    ev = classify_event_type(
        direction="incoming",
        sender_role="agency",
        subject="Odprawa zakończona",
        body="MRN: 26PL44302D00A1J5R7 — odprawa zakończona.",
        attachments=[],
    )
    assert ev == "agency_sad_reply", f"Expected agency_sad_reply, got: {ev}"


def test_agency_sad_reply_detected_by_text_odprawa():
    """Agency email containing 'odprawa' → agency_sad_reply via keyword."""
    ev = classify_event_type(
        direction="incoming",
        sender_role="agency",
        subject="Odprawa celna",
        body="Odprawa zakończona.",
        attachments=[],
    )
    assert ev == "agency_sad_reply", f"Expected agency_sad_reply, got: {ev}"


def test_agency_sad_reply_detected_by_text_customs_cleared():
    """Agency email containing 'customs cleared' → agency_sad_reply via keyword."""
    ev = classify_event_type(
        direction="incoming",
        sender_role="agency",
        subject="Update",
        body="Customs cleared successfully.",
        attachments=[],
    )
    assert ev == "agency_sad_reply", f"Expected agency_sad_reply, got: {ev}"


def test_agency_sad_reply_detected_by_text_zoll():
    """Agency email containing 'zoll' → agency_sad_reply via keyword (German customs)."""
    ev = classify_event_type(
        direction="incoming",
        sender_role="agency",
        subject="Zollerklärung",
        body="",
        attachments=[],
    )
    assert ev == "agency_sad_reply", f"Expected agency_sad_reply, got: {ev}"


# ── 3. No false positive ──────────────────────────────────────────────────────

def test_no_false_positive_on_random_email():
    """External sender with no SAD/customs evidence → 'other', not agency_sad_reply."""
    ev = classify_event_type(
        direction="incoming",
        sender_role="external",
        subject="Hello",
        body="Please confirm your order.",
        attachments=[],
    )
    assert ev == "other", f"Expected 'other' for random external email, got: {ev}"


def test_no_false_positive_agency_pure_invoice():
    """Agency email that is purely an invoice (no SAD) → agency_invoice, not agency_sad_reply."""
    atts = [{"filename": "invoice_123.pdf", "document_type": "invoice"}]
    ev = classify_event_type(
        direction="incoming",
        sender_role="agency",
        subject="Invoice for services",
        body="Please find attached invoice.",
        attachments=atts,
    )
    assert ev == "agency_invoice", f"Expected agency_invoice, got: {ev}"
