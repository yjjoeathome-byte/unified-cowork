#!/usr/bin/env python3
"""
discover-idb.py -- IndexedDB schema discovery for Claude Desktop.

Reads a Chromium LevelDB snapshot (as produced by the canonized
robocopy recipe) and enumerates all databases, their object stores,
and a sample of records per store so we can identify which store
holds Cowork session transcripts.

Usage:
    python discover-idb.py <leveldb-snapshot-dir> [--records-per-store N] [--out path.json]

Outputs:
    - stdout: human-readable summary
    - <snapshot-dir>/../schema-<timestamp>.json by default

Dependency:
    pip install ccl_chromium_reader
    (Pure-Python. Package ships ccl_chromium_indexeddb submodule.)
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path


# -- ccl import: try both known package layouts -----------------------
_idb = None
_import_err = None
for _modpath in (
    "ccl_chromium_reader.ccl_chromium_indexeddb",  # current pypi layout
    "ccl_chromium_indexeddb",                       # legacy / direct clone
):
    try:
        _idb = __import__(_modpath, fromlist=["*"])
        break
    except ImportError as _e:
        _import_err = _e

if _idb is None:
    sys.stderr.write(
        "ERROR: ccl_chromium_indexeddb not importable.\n"
        f"Last import error: {_import_err!r}\n"
        "Install with: pip install ccl_chromium_reader\n"
    )
    sys.exit(2)


# -- helpers ----------------------------------------------------------
def _preview(value, max_len: int = 400) -> str:
    """Return a bounded, JSON-safe preview of a record value."""
    try:
        s = json.dumps(value, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        s = repr(value)
    if len(s) > max_len:
        return s[:max_len] + f"...(+{len(s) - max_len} chars)"
    return s


def _safe(v):
    """Coerce anything to a JSON-serializable form."""
    try:
        json.dumps(v)
        return v
    except (TypeError, ValueError):
        return repr(v)


def _value_summary(value) -> dict:
    """Shallow structural summary of a record value."""
    summary = {"py_type": type(value).__name__}
    if isinstance(value, dict):
        summary["keys"] = sorted(list(value.keys()))[:50]
        summary["key_count"] = len(value)
    elif isinstance(value, (list, tuple)):
        summary["length"] = len(value)
        if value:
            summary["elem_type"] = type(value[0]).__name__
    elif isinstance(value, (str, bytes)):
        summary["length"] = len(value)
    return summary


# -- main enumeration -------------------------------------------------
def discover(snapshot_dir: Path, records_per_store: int) -> dict:
    if not snapshot_dir.is_dir():
        raise SystemExit(f"not a directory: {snapshot_dir}")

    print(f"[*] Opening LevelDB: {snapshot_dir}")
    wrapped = _idb.WrappedIndexDB(str(snapshot_dir))

    # API across versions: .database_ids yields DatabaseId-like objects
    db_ids = list(getattr(wrapped, "database_ids", None) or wrapped.databases)
    print(f"[*] Databases found: {len(db_ids)}\n")

    report = {
        "snapshot_path": str(snapshot_dir),
        "discovered_at_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "library_module": _idb.__name__,
        "database_count": len(db_ids),
        "databases": [],
    }

    for dbi in db_ids:
        dbid = getattr(dbi, "dbid_no", None) or getattr(dbi, "id", None)
        name = getattr(dbi, "name", None) or getattr(dbi, "dbname", None) or "?"
        origin = getattr(dbi, "origin", None) or "?"

        print(f"== DB #{dbid}: name={name!r} origin={origin!r}")

        try:
            database = wrapped[dbid]
        except Exception:
            database = wrapped.get_database_by_id(dbid)

        store_names = list(database.object_store_names)
        db_entry = {
            "id": _safe(dbid),
            "name": name,
            "origin": origin,
            "object_store_count": len(store_names),
            "object_stores": [],
        }

        for os_name in store_names:
            try:
                store = database[os_name]
            except Exception:
                store = database.get_object_store_by_name(os_name)

            sample = []
            count = 0
            err = None
            try:
                for record in store.iterate_records():
                    count += 1
                    if len(sample) < records_per_store:
                        sample.append({
                            "key": _safe(record.key),
                            "value_summary": _value_summary(record.value),
                            "value_preview": _preview(record.value),
                        })
            except Exception as e:
                err = repr(e)

            store_entry = {
                "name": os_name,
                "record_count": count,
                "iterate_error": err,
                "sample_records": sample,
            }
            db_entry["object_stores"].append(store_entry)

            print(f"   -- store={os_name!r}  records={count}"
                  + (f"  ERROR={err}" if err else ""))
            for i, r in enumerate(sample):
                print(f"      [{i}] key={r['key']!r}")
                print(f"          summary={r['value_summary']}")
                print(f"          preview={r['value_preview']}")

        report["databases"].append(db_entry)
        print()

    return report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("snapshot_dir", help="path to leveldb snapshot directory")
    ap.add_argument("--records-per-store", type=int, default=3,
                    help="how many records to sample per store (default: 3)")
    ap.add_argument("--out", default=None,
                    help="output JSON path (default: alongside snapshot dir)")
    args = ap.parse_args()

    snap = Path(args.snapshot_dir).resolve()
    report = discover(snap, args.records_per_store)

    if args.out:
        out_path = Path(args.out)
    else:
        ts = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        out_path = snap.parent / f"schema-{ts}.json"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    print(f"[+] Report written to: {out_path}")


if __name__ == "__main__":
    main()
