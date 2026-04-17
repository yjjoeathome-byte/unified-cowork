#!/usr/bin/env python3
"""
discover-idb.py -- IndexedDB schema discovery for Claude Desktop.

Reads a Chromium LevelDB + blob snapshot (as produced by the canonized
robocopy recipe) and enumerates all databases, their object stores,
and a sample of records per store so we can identify which store
holds Cowork session transcripts.

Snapshot layout convention (canonized):
    <snapshot-dir>/
        leveldb/    -- contents of *.indexeddb.leveldb
        blob/       -- contents of *.indexeddb.blob (may contain binary blobs
                        referenced by IndexedDB values; required for records
                        that include Blob values, otherwise iterate_records
                        raises ValueError)

Legacy fallback: if <snapshot-dir> contains CURRENT/MANIFEST-* directly,
treat it as the leveldb dir and look for a sibling *.blob dir.

Usage:
    python discover-idb.py <snapshot-dir> [--records-per-store N]
                                          [--blob-dir PATH]
                                          [--out PATH]

Dependency:
    pip install git+https://github.com/cclgroupltd/ccl_chrome_indexeddb.git
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path


# -- ccl import: try both known module paths --------------------------
_idb = None
_import_err = None
for _modpath in (
    "ccl_chromium_reader.ccl_chromium_indexeddb",
    "ccl_chromium_indexeddb",
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
        "Install with:\n"
        "  pip install git+https://github.com/cclgroupltd/ccl_chrome_indexeddb.git\n"
    )
    sys.exit(2)


# -- snapshot path resolution -----------------------------------------
def _resolve_paths(snapshot_dir: Path, explicit_blob: Path | None):
    """
    Return (leveldb_dir, blob_dir_or_None) given the user-provided path.

    Accepts:
      1. Canonized layout: <snapshot-dir>/leveldb + <snapshot-dir>/blob
      2. Direct leveldb dir (contains CURRENT file) -- look for sibling
         *.blob dir via naming convention, or --blob-dir override.
    """
    if not snapshot_dir.is_dir():
        raise SystemExit(f"not a directory: {snapshot_dir}")

    # Case 1: canonized layout
    canon_ldb = snapshot_dir / "leveldb"
    canon_blob = snapshot_dir / "blob"
    if canon_ldb.is_dir() and (canon_ldb / "CURRENT").exists():
        return canon_ldb, (canon_blob if canon_blob.is_dir() else None)

    # Case 2: raw leveldb dir
    if (snapshot_dir / "CURRENT").exists():
        leveldb_dir = snapshot_dir
        if explicit_blob:
            return leveldb_dir, explicit_blob
        # Auto-detect sibling blob dir by Chromium naming convention
        name = snapshot_dir.name
        if name.endswith(".indexeddb.leveldb"):
            base = name[: -len(".indexeddb.leveldb")]
            sib = snapshot_dir.parent / f"{base}.indexeddb.blob"
            if sib.is_dir():
                return leveldb_dir, sib
        return leveldb_dir, None

    raise SystemExit(
        f"snapshot layout not recognized at {snapshot_dir}\n"
        "Expected either:\n"
        "  <dir>/leveldb/CURRENT + <dir>/blob/  (canonized), or\n"
        "  <dir>/CURRENT                        (raw leveldb)"
    )


# -- helpers ----------------------------------------------------------
def _preview(value, max_len: int = 400) -> str:
    try:
        s = json.dumps(value, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        s = repr(value)
    if len(s) > max_len:
        return s[:max_len] + f"...(+{len(s) - max_len} chars)"
    return s


def _safe(v):
    try:
        json.dumps(v)
        return v
    except (TypeError, ValueError):
        return repr(v)


def _value_summary(value) -> dict:
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


def _open_wrapped(leveldb_dir: Path, blob_dir: Path | None):
    """
    Defensive WrappedIndexDB construction across library versions.
    Newer versions accept (leveldb_path, blob_path); older may not.
    """
    args_variants = []
    if blob_dir is not None:
        args_variants.append({"args": (str(leveldb_dir), str(blob_dir)), "kwargs": {}})
        args_variants.append({"args": (str(leveldb_dir),), "kwargs": {"blob_dir": str(blob_dir)}})
        args_variants.append({"args": (str(leveldb_dir),), "kwargs": {"blob_folder_path": str(blob_dir)}})
    args_variants.append({"args": (str(leveldb_dir),), "kwargs": {}})

    last_err = None
    for v in args_variants:
        try:
            return _idb.WrappedIndexDB(*v["args"], **v["kwargs"])
        except TypeError as e:
            last_err = e
            continue
    raise SystemExit(
        f"Failed to construct WrappedIndexDB with any known signature.\n"
        f"Last error: {last_err!r}"
    )


# -- main enumeration -------------------------------------------------
def discover(snapshot_dir: Path, records_per_store: int, explicit_blob: Path | None) -> dict:
    leveldb_dir, blob_dir = _resolve_paths(snapshot_dir, explicit_blob)
    print(f"[*] Opening LevelDB: {leveldb_dir}")
    print(f"[*] Blob dir:        {blob_dir if blob_dir else '(none - blob records will error)'}")

    wrapped = _open_wrapped(leveldb_dir, blob_dir)

    db_ids = list(getattr(wrapped, "database_ids", None) or wrapped.databases)
    print(f"[*] Databases found: {len(db_ids)}\n")

    report = {
        "snapshot_path": str(snapshot_dir),
        "leveldb_path": str(leveldb_dir),
        "blob_path": str(blob_dir) if blob_dir else None,
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
    ap.add_argument("snapshot_dir", help="path to snapshot (see module docstring for layout)")
    ap.add_argument("--records-per-store", type=int, default=3)
    ap.add_argument("--blob-dir", default=None,
                    help="explicit blob directory (overrides auto-detection)")
    ap.add_argument("--out", default=None, help="output JSON path")
    args = ap.parse_args()

    snap = Path(args.snapshot_dir).resolve()
    explicit_blob = Path(args.blob_dir).resolve() if args.blob_dir else None
    report = discover(snap, args.records_per_store, explicit_blob)

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
