"""
test_carrier_label_store.py — On-disk label store tests.

Required coverage:
  1. ``init_store`` creates ``_attachments``, ``_by_awb`` and an empty
     ``_index.json``.
  2. ``save_attachment`` returns a ``LabelArtefact`` with sha256, path
     and size; the file lives under ``_attachments/<sha>.<ext>``.
  3. Saving the same content twice does not duplicate the file (same
     path, same sha256).
  4. ``write_manifest`` / ``read_manifest`` round-trip; ``updated_at``
     is stamped on every write.
  5. ``append_message`` writes one file per call under
     ``_by_awb/<awb>/messages/<id>.json`` and returns the message id.
  6. ``index_awb`` updates ``_index.json`` and ``write_manifest`` calls
     it transparently.
  7. AWB sanitization: characters outside [A-Za-z0-9-_] are stripped.
"""
from __future__ import annotations

import hashlib
import json

import pytest

from app.services.carrier import carrier_label_store as cls


@pytest.fixture()
def store(tmp_path):
    cls.init_store(tmp_path / "carrier_labels")
    return tmp_path / "carrier_labels"


# ── 1. Init creates expected layout ─────────────────────────────────────────

def test_init_creates_dirs_and_index(store):
    assert (store / "_attachments").is_dir()
    assert (store / "_by_awb").is_dir()
    idx = store / "_index.json"
    assert idx.is_file()
    assert json.loads(idx.read_text(encoding="utf-8")) == {}


# ── 2. save_attachment returns a content-addressed artefact ─────────────────

def test_save_attachment_returns_artefact(store):
    payload = b"%PDF-1.4 fake label bytes"
    art = cls.save_attachment(payload, suffix="pdf")
    assert art.sha256 == hashlib.sha256(payload).hexdigest()
    assert art.label_format == "pdf"
    assert art.size == len(payload)
    p = store / "_attachments" / f"{art.sha256}.pdf"
    assert p.is_file()
    assert p.read_bytes() == payload


# ── 3. Same content saves only once ─────────────────────────────────────────

def test_save_attachment_dedupes_same_content(store):
    payload = b"identical bytes"
    a1 = cls.save_attachment(payload, suffix="pdf")
    a2 = cls.save_attachment(payload, suffix="pdf")
    assert a1.sha256 == a2.sha256
    assert a1.path == a2.path
    # Only one file exists in _attachments
    pdfs = list((store / "_attachments").glob(f"{a1.sha256}*"))
    assert len(pdfs) == 1


def test_save_attachment_no_suffix(store):
    art = cls.save_attachment(b"raw")
    assert art.label_format == ""
    assert (store / "_attachments" / art.sha256).is_file()


# ── 4. Manifest round-trip ──────────────────────────────────────────────────

def test_write_and_read_manifest(store):
    awb = "1234567890"
    written = cls.write_manifest(awb, {"carrier": "dhl", "state": "label_created"})
    assert written.name == "manifest.json"

    payload = cls.read_manifest(awb)
    assert payload["carrier"] == "dhl"
    assert payload["state"] == "label_created"
    assert payload["awb"] == awb
    assert "updated_at" in payload and payload["updated_at"]


def test_read_manifest_missing_returns_empty(store):
    assert cls.read_manifest("never-written") == {}


def test_write_manifest_requires_awb(store):
    with pytest.raises(ValueError):
        cls.write_manifest("", {"x": 1})


# ── 5. Append-only messages ─────────────────────────────────────────────────

def test_append_message_writes_one_file(store):
    awb = "1112223333"
    mid = cls.append_message(awb, {"event_code": "label_created"})
    assert mid
    msgdir = store / "_by_awb" / awb / "messages"
    files = list(msgdir.glob("*.json"))
    assert len(files) == 1
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert payload["message_id"] == mid
    assert payload["awb"] == awb
    assert payload["event_code"] == "label_created"


def test_append_message_each_call_new_file(store):
    awb = "9998887777"
    mids = [cls.append_message(awb, {"i": i}) for i in range(3)]
    assert len(set(mids)) == 3
    files = list((store / "_by_awb" / awb / "messages").glob("*.json"))
    assert len(files) == 3


def test_append_message_requires_awb(store):
    with pytest.raises(ValueError):
        cls.append_message("", {"event_code": "x"})


# ── 6. index_awb / get_index ────────────────────────────────────────────────

def test_write_manifest_updates_index(store):
    cls.write_manifest("AWB1", {"carrier": "dhl"})
    cls.write_manifest("AWB2", {"carrier": "dhl"})
    idx = cls.get_index()
    assert "AWB1" in idx
    assert "AWB2" in idx
    assert idx["AWB1"].endswith("manifest.json")


# ── 7. AWB sanitization ─────────────────────────────────────────────────────

def test_awb_sanitization(store):
    # Strange characters get stripped — but the manifest still gets written.
    cls.write_manifest("AWB/../etc/passwd", {"carrier": "dhl"})
    idx = cls.get_index()
    keys = list(idx.keys())
    assert any("etcpasswd" in k or "AWBetcpasswd" in k for k in keys), (
        f"unexpected sanitised AWB keys: {keys!r}"
    )


# ── Init guard ──────────────────────────────────────────────────────────────

def test_save_attachment_without_init_raises(tmp_path, monkeypatch):
    # Reset module state so we can prove init is required.
    monkeypatch.setattr(cls, "_store_root", None, raising=False)
    with pytest.raises(RuntimeError):
        cls.save_attachment(b"x")
