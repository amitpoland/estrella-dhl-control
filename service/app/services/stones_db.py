"""stones_db.py — Local gemstone catalog (Phase 3).

Storage: <storage_root>/stones.sqlite

Authority: LOCAL catalog. Certification data (cert_type/id/lab) is reference
only — does not validate against an external GIA/IGI registry.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional


STONE_TYPES = ("diamond", "ruby", "emerald", "sapphire", "semi_precious", "other")
SHAPES = ("round", "princess", "oval", "emerald", "pear", "marquise",
          "cushion", "radiant", "heart", "baguette", "other")
CERT_TYPES = ("GIA", "IGI", "HRD", "SGL", "none", "other")

_CODE_RE = re.compile(r"^[A-Z0-9_-]{2,40}$")


@dataclass
class Stone:
    code:           str
    stone_type:     Optional[str] = None
    name:           Optional[str] = None
    shape:          Optional[str] = None
    carat_weight:   Optional[str] = None      # Decimal-as-string, no float
    color_grade:    Optional[str] = None
    clarity_grade:  Optional[str] = None
    cut_grade:      Optional[str] = None
    cert_type:      Optional[str] = None
    cert_id:        Optional[str] = None
    cert_lab:       Optional[str] = None
    active:         bool          = True
    notes:          Optional[str] = None
    created_at:     Optional[str] = None
    updated_at:     Optional[str] = None
    deleted_at:     Optional[str] = None      # Phase 4A — soft-delete timestamp


def stone_to_dict(s: Stone) -> Dict[str, Any]:
    return asdict(s)


# ── Schema ──────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS stones (
    code           TEXT PRIMARY KEY,
    stone_type     TEXT,
    name           TEXT,
    shape          TEXT,
    carat_weight   TEXT,                       -- Decimal-as-string
    color_grade    TEXT,
    clarity_grade  TEXT,
    cut_grade      TEXT,
    cert_type      TEXT,
    cert_id        TEXT,
    cert_lab       TEXT,
    active         INTEGER NOT NULL DEFAULT 1,
    notes          TEXT,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    deleted_at     TEXT
);
CREATE INDEX IF NOT EXISTS ix_stones_type    ON stones (stone_type);
CREATE INDEX IF NOT EXISTS ix_stones_cert_id ON stones (cert_id);
CREATE INDEX IF NOT EXISTS ix_stones_cert_lab ON stones (cert_lab);
CREATE INDEX IF NOT EXISTS ix_stones_active  ON stones (active);
"""


def _migrate_add_deleted_at(cx: sqlite3.Connection) -> None:
    try:
        cx.execute("ALTER TABLE stones ADD COLUMN deleted_at TEXT")
    except sqlite3.OperationalError as exc:
        if "duplicate column" not in str(exc).lower():
            raise


def init_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as cx:
        cx.executescript(_SCHEMA)
        _migrate_add_deleted_at(cx)


# ── Validation ──────────────────────────────────────────────────────────────

def validate_stone(data: Dict[str, Any]) -> List[str]:
    errs: List[str] = []
    code = (data.get("code") or "").strip()
    if not code:
        errs.append("code is required")
    elif not _CODE_RE.match(code):
        errs.append("code must match ^[A-Z0-9_-]{2,40}$ (uppercase)")
    st = data.get("stone_type")
    if st is not None and st != "" and st not in STONE_TYPES:
        errs.append(f"stone_type must be one of {list(STONE_TYPES)}")
    sh = data.get("shape")
    if sh is not None and sh != "" and sh not in SHAPES:
        errs.append(f"shape must be one of {list(SHAPES)}")
    ct = data.get("cert_type")
    if ct is not None and ct != "" and ct not in CERT_TYPES:
        errs.append(f"cert_type must be one of {list(CERT_TYPES)}")
    cw = data.get("carat_weight")
    if cw is not None and cw != "":
        if isinstance(cw, float):
            errs.append("carat_weight must be Decimal-as-string, not float")
        else:
            try:
                d = Decimal(str(cw))
            except (InvalidOperation, ValueError):
                errs.append("carat_weight must parse as Decimal")
            else:
                if d < 0:
                    errs.append("carat_weight must be >= 0")
    return errs


# ── Read ────────────────────────────────────────────────────────────────────

def _row_to_stone(r: sqlite3.Row) -> Stone:
    keys = r.keys() if hasattr(r, "keys") else []
    return Stone(
        code=r["code"], stone_type=r["stone_type"], name=r["name"],
        shape=r["shape"], carat_weight=r["carat_weight"],
        color_grade=r["color_grade"], clarity_grade=r["clarity_grade"],
        cut_grade=r["cut_grade"], cert_type=r["cert_type"],
        cert_id=r["cert_id"], cert_lab=r["cert_lab"],
        active=bool(r["active"]), notes=r["notes"],
        created_at=r["created_at"], updated_at=r["updated_at"],
        deleted_at=(r["deleted_at"] if "deleted_at" in keys else None),
    )


def get_stone(path: Path, code: str) -> Optional[Stone]:
    with sqlite3.connect(path) as cx:
        cx.row_factory = sqlite3.Row
        r = cx.execute("SELECT * FROM stones WHERE code = ?", (code,)).fetchone()
    return _row_to_stone(r) if r else None


def list_stones(path: Path, *, active: Optional[bool] = None,
                stone_type: Optional[str] = None,
                limit: int = 500) -> List[Stone]:
    where: List[str] = []
    args:  List[Any] = []
    if active is not None:
        where.append("active = ?")
        args.append(1 if active else 0)
    if stone_type:
        where.append("stone_type = ?")
        args.append(stone_type)
    sql = "SELECT * FROM stones"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY code LIMIT ?"
    args.append(limit)
    with sqlite3.connect(path) as cx:
        cx.row_factory = sqlite3.Row
        rows = cx.execute(sql, args).fetchall()
    return [_row_to_stone(r) for r in rows]


# ── Write ───────────────────────────────────────────────────────────────────

def upsert_stone(path: Path, data: Dict[str, Any]) -> Stone:
    errs = validate_stone(data)
    if errs:
        raise ValueError("; ".join(errs))
    code = data["code"].strip()
    now  = datetime.now(timezone.utc).isoformat()
    active = data.get("active", True)
    active = 1 if (active is True or str(active).lower() in ("true","1","yes")) else 0
    cw = data.get("carat_weight")
    if cw is not None and cw != "":
        # Preserve incoming string form exactly (Decimal-as-string discipline).
        cw = str(cw)
    else:
        cw = None
    with sqlite3.connect(path) as cx:
        cx.execute("BEGIN IMMEDIATE")
        cur = cx.execute("SELECT created_at FROM stones WHERE code = ?", (code,))
        existing = cur.fetchone()
        if existing:
            cx.execute(
                """UPDATE stones SET stone_type=?, name=?, shape=?, carat_weight=?,
                       color_grade=?, clarity_grade=?, cut_grade=?,
                       cert_type=?, cert_id=?, cert_lab=?,
                       active=?, notes=?, updated_at=?
                   WHERE code = ?""",
                (data.get("stone_type"), data.get("name"), data.get("shape"),
                 cw, data.get("color_grade"), data.get("clarity_grade"),
                 data.get("cut_grade"), data.get("cert_type"),
                 data.get("cert_id"), data.get("cert_lab"),
                 active, data.get("notes"), now, code),
            )
        else:
            cx.execute(
                """INSERT INTO stones
                   (code, stone_type, name, shape, carat_weight,
                    color_grade, clarity_grade, cut_grade,
                    cert_type, cert_id, cert_lab,
                    active, notes, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (code, data.get("stone_type"), data.get("name"), data.get("shape"),
                 cw, data.get("color_grade"), data.get("clarity_grade"),
                 data.get("cut_grade"), data.get("cert_type"),
                 data.get("cert_id"), data.get("cert_lab"),
                 active, data.get("notes"), now, now),
            )
        cx.commit()
    rec = get_stone(path, code)
    assert rec is not None
    return rec


def delete_stone(path: Path, code: str) -> bool:
    """Phase 3 alias kept for backwards compatibility. HARD delete."""
    with sqlite3.connect(path) as cx:
        cur = cx.execute("DELETE FROM stones WHERE code = ?", (code,))
        cx.commit()
        return cur.rowcount > 0


# ── Phase 4A — soft-delete + restore ────────────────────────────────────────

def soft_delete_stone(path: Path, code: str) -> bool:
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(path) as cx:
        cur = cx.execute(
            "UPDATE stones SET active = 0, deleted_at = ?, updated_at = ? "
            "WHERE code = ?",
            (now, now, code),
        )
        cx.commit()
        return cur.rowcount > 0


def restore_stone(path: Path, code: str) -> bool:
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(path) as cx:
        cur = cx.execute(
            "UPDATE stones SET active = 1, deleted_at = NULL, updated_at = ? "
            "WHERE code = ?",
            (now, code),
        )
        cx.commit()
        return cur.rowcount > 0


def hard_delete_stone(path: Path, code: str) -> bool:
    return delete_stone(path, code)
