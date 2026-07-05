"""verify_sync.py — 2a-v deployment sync verification gate (wave12, SHA 84c292de).

Prints MISSING / DIFF counts and MATCH status for the three critical files.
Prints exactly `SYNC VERIFIED` and exits 0 ONLY if every condition passes:
MISSING = 0, DIFF = 0, main.py MATCH, reservation_db.py MATCH,
routes_proforma.py MATCH. Otherwise exits 1.
"""
import hashlib
import os
import sys

SRC = r"C:\PZ-deploy-w12\service\app"
DST = r"C:\PZ\app"
NAMED = [
    "main.py",
    os.path.join("services", "reservation_db.py"),
    os.path.join("api", "routes_proforma.py"),
]


def norm(path):
    try:
        with open(path, "rb") as fh:
            return hashlib.sha1(fh.read().replace(b"\r\n", b"\n")).hexdigest()
    except OSError:
        return None


def main():
    missing, diff, total = [], [], 0
    for dirpath, dirnames, filenames in os.walk(SRC):
        dirnames[:] = [d for d in dirnames
                       if d not in ("__pycache__", ".pytest_cache", "storage")]
        for f in filenames:
            if f.endswith((".pyc", ".pyo", ".zip")):
                continue
            sp = os.path.join(dirpath, f)
            rel = os.path.relpath(sp, SRC)
            total += 1
            h_src, h_dst = norm(sp), norm(os.path.join(DST, rel))
            if h_dst is None:
                missing.append(rel)
            elif h_src != h_dst:
                diff.append(rel)

    print(f"total={total} MISSING={len(missing)} DIFF={len(diff)}")
    for rel in missing:
        print(f"  MISSING: {rel}")
    for rel in diff:
        print(f"  DIFF:    {rel}")

    named_ok = True
    for rel in NAMED:
        match = norm(os.path.join(SRC, rel)) == norm(os.path.join(DST, rel))
        named_ok &= match
        print(f"  {rel}: {'MATCH' if match else 'MISMATCH'}")

    if not missing and not diff and named_ok:
        print("SYNC VERIFIED")
        return 0
    print("SYNC INCOMPLETE - re-run the robocopy; do NOT proceed to migrations")
    return 1


if __name__ == "__main__":
    sys.exit(main())
