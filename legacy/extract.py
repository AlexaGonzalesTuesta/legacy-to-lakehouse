"""Nightly extract from the legacy database to the cloud landing zone.

For each table, only rows whose watermark (updated_at) is newer than the last successful
extract are written, as CSV, with a manifest. A reconciliation file with every live primary
key and a hash of its business columns is written too, so the lakehouse can prove it matches.
"""
from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

BOOL_COLUMNS = {"park_it", "crash", "fire", "is_deleted"}


def fmt(column: str, value: Any) -> str:
    """Canonical text form shared by the extract and the Spark side of reconciliation."""
    if value is None:
        return ""
    if column in BOOL_COLUMNS:
        return "true" if int(value) else "false"
    return str(value).strip()


def row_hash(values: List[str]) -> str:
    return hashlib.sha256("|".join(values).encode("utf-8")).hexdigest()


def hash_columns(contract: Dict[str, Any]) -> List[str]:
    """Business columns compared between legacy and lakehouse: everything except PII,
    the delete flag and the watermark (which the lakehouse does not change)."""
    skip = set(contract.get("pii", [])) | {"is_deleted", contract["watermark"]}
    return [c for c in contract["columns"] if c not in skip]


def extract_batch(db: Path, landing: Path, contracts: Dict[str, Dict[str, Any]], batch_id: int,
                  state_path: Path, full: bool = False) -> Dict[str, Any]:
    state = json.loads(state_path.read_text()) if state_path.exists() and not full else {}
    con = sqlite3.connect(db)
    manifest: Dict[str, Any] = {"batch_id": batch_id, "mode": "full" if full or not state else "incremental",
                                "extracted_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "tables": {}}
    for table, c in contracts.items():
        cols = list(c["columns"])
        wm_col = c["watermark"]
        since: Optional[str] = state.get(table)
        sql = f"SELECT {', '.join(cols)} FROM {table}"
        params: List[Any] = []
        if since:
            sql += f" WHERE {wm_col} > ?"
            params.append(since)
        rows = con.execute(sql + f" ORDER BY {wm_col}", params).fetchall()
        out = landing / table / f"batch_id={batch_id:04d}"
        out.mkdir(parents=True, exist_ok=True)
        with open(out / "part-0000.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(cols)
            for r in rows:
                w.writerow([fmt(col, v) for col, v in zip(cols, r)])
        new_wm = max((r[cols.index(wm_col)] for r in rows), default=since)
        manifest["tables"][table] = {"rows": len(rows), "watermark_from": since, "watermark_to": new_wm}
        if new_wm:
            state[table] = new_wm

        # Reconciliation snapshot: every live row in the legacy system, as key + hash
        hcols = hash_columns(c)
        pk = c["primary_key"]
        live = " WHERE is_deleted = 0" if "is_deleted" in c["columns"] else ""
        recon = landing / "_reconciliation" / table / f"batch_id={batch_id:04d}"
        recon.mkdir(parents=True, exist_ok=True)
        with open(recon / "part-0000.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(pk + ["row_hash"])
            for r in con.execute(f"SELECT {', '.join(pk + hcols)} FROM {table}{live}"):
                key = [fmt(k, v) for k, v in zip(pk, r[:len(pk)])]
                w.writerow(key + [row_hash([fmt(h, v) for h, v in zip(hcols, r[len(pk):])])])
    con.close()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2))
    (landing / "_manifests").mkdir(parents=True, exist_ok=True)
    (landing / "_manifests" / f"batch_id={batch_id:04d}.json").write_text(json.dumps(manifest, indent=2))
    return manifest
