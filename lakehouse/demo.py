"""Run the whole migration: build the legacy database, do the initial full load, then N nightly
incremental loads, then a full reload for comparison. Writes site/data/run.json for the board."""
from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from legacy.build_legacy import PLANTED, build
from legacy.extract import extract_batch
from legacy.simulate import simulate_day
from .pipeline import ROOT, Pipeline, load_contracts, save_json
from .store import ParquetStore, Store


def local_spark(app: str = "legacy-to-lakehouse") -> SparkSession:
    return (SparkSession.builder.master("local[2]").appName(app)
            .config("spark.ui.enabled", "false")
            .config("spark.sql.shuffle.partitions", "4")
            .config("spark.sql.session.timeZone", "UTC")
            .config("spark.ui.showConsoleProgress", "false")
            .getOrCreate())


def _rows(df) -> List[Dict[str, Any]]:
    return [r.asDict() for r in df.collect()]


def run_demo(work: Path, days: int = 7, spark: Optional[SparkSession] = None, store: Optional[Store] = None,
             landing: Optional[str] = None, full_store: Optional[Store] = None, full_landing: Optional[str] = None,
             out: Optional[Path] = ROOT / "site" / "data" / "run.json", log=print) -> Dict[str, Any]:
    spark = spark or local_spark()
    if (work / "legacy").exists():
        shutil.rmtree(work / "legacy")
    landing = landing or str(work / "landing")
    for p in (landing, full_landing or str(work / "landing_full")):
        if not p.startswith("/Volumes") and Path(p).exists():
            shutil.rmtree(p)
    store = store or ParquetStore(spark, str(work / "lakehouse"))
    store.reset()
    cfg = load_contracts()
    db = work / "legacy" / "recall_ops.db"
    state = work / "legacy" / "extract_state.json"

    counts = build(db)
    log(f"Legacy database built: {counts}")
    pipe = Pipeline(spark, store, landing, cfg)
    batches, simulated = [], []
    for day in range(0, days + 1):
        if day:
            simulated.append({"day": day, **simulate_day(db, day)})
        manifest = extract_batch(db, Path(landing), cfg["tables"], day, state, full=(day == 0))
        res = pipe.run_batch(day, manifest)
        res["extracted"] = manifest["tables"]
        batches.append(res)
        ready = sum(r["status"] == "ready" for r in res["reconciliation"])
        log(f"Batch {day} ({res['mode']}): {res['rows_processed']:,} rows loaded in {res['load_seconds']}s, "
            f"{ready} of {len(res['reconciliation'])} tables match the legacy system")

    # Full reload of the same final legacy state, for the cost comparison.
    full_landing = full_landing or str(work / "landing_full")
    full_store = full_store or ParquetStore(spark, str(work / "lakehouse_full"))
    full_store.reset()
    manifest = extract_batch(db, Path(full_landing), cfg["tables"], 0, work / "legacy" / "full_state.json", full=True)
    full = Pipeline(spark, full_store, full_landing, cfg).run_batch(0, manifest, reconcile=False)
    full_seconds = full["load_seconds"]
    log(f"Full reload for comparison: {full['rows_processed']:,} rows in {full_seconds}s")

    snapshot = summarize(spark, store, cfg, batches, simulated, full, full_seconds, counts)
    if out:
        save_json(snapshot, out)
        log(f"Wrote {out}")
    return snapshot


def summarize(spark, store: Store, cfg, batches, simulated, full, full_seconds, counts) -> Dict[str, Any]:
    last = batches[-1]
    incr = [b for b in batches if b["mode"] == "incremental"]
    avg_incr_rows = round(sum(b["rows_processed"] for b in incr) / len(incr)) if incr else 0
    avg_incr_secs = round(sum(b["load_seconds"] for b in incr) / len(incr), 2) if incr else 0
    avg_recon_secs = round(sum(b["reconcile_seconds"] for b in incr) / len(incr), 2) if incr else 0
    s = lambda t: store.read("silver", t)  # noqa: E731
    g = lambda t: store.read("gold", t)  # noqa: E731
    campaigns = _rows(g("recall_completion_by_campaign").filter("vehicles_affected >= 20")
                      .orderBy("completion_rate", F.desc("vehicles_affected")).limit(12))
    recall_text = {r["campaign_number"]: r for r in _rows(
        s("recalls").groupBy("campaign_number").agg(F.first("summary").alias("summary"),
                                                    F.first("report_received_date").alias("reported")))}
    for c in campaigns:
        info = recall_text.get(c["campaign_number"], {})
        c["summary"] = (info.get("summary") or "")[:240]
        c["reported"] = str(info.get("reported") or "")
    dealers = _rows(g("recall_completion_by_dealer").orderBy("completion_rate").limit(10))
    totals = g("recall_completion_by_campaign").agg(F.sum("vehicles_affected").alias("a"),
                                                   F.sum("vehicles_repaired").alias("r")).collect()[0]
    history = _rows(s("dealers_history").join(
        s("dealers_history").groupBy("dealer_code").count().filter("count > 1").select("dealer_code"), "dealer_code")
        .orderBy("dealer_code", "valid_from"))
    pii_cols = sum(len(c.get("pii", [])) for c in cfg["tables"].values())
    layers = {layer: {} for layer in ("bronze", "silver", "gold")}
    for t in cfg["tables"]:
        layers["bronze"][t] = store.read("bronze", t).count()
        layers["silver"][t] = s(t).count()
    layers["silver"]["dealers_history"] = s("dealers_history").count()
    layers["silver"]["quarantine"] = s("quarantine").count() if store.exists("silver", "quarantine") else 0
    for t in last["gold"]:
        layers["gold"][t] = last["gold"][t]
    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "spark_version": spark.version,
        "legacy_counts": counts, "planted_problems": PLANTED,
        "summary": {
            "tables": len(last["reconciliation"]),
            "tables_ready": sum(r["status"] == "ready" for r in last["reconciliation"]),
            "rows_matched": sum(r["matched_rows"] for r in last["reconciliation"]),
            "rows_legacy": sum(r["legacy_rows"] for r in last["reconciliation"]),
            "nightly_rows_avg": avg_incr_rows, "nightly_load_seconds_avg": avg_incr_secs,
            "nightly_reconcile_seconds_avg": avg_recon_secs,
            "full_reload_rows": full["rows_processed"], "full_reload_seconds": full_seconds,
            "rows_saved_pct": round(100 * (1 - avg_incr_rows / full["rows_processed"]), 1) if full["rows_processed"] else 0,
            "pii_columns_hashed": pii_cols, "nights": len(incr),
            "recall_vehicles": int(totals["a"] or 0), "recall_repairs_done": int(totals["r"] or 0),
        },
        "reconciliation": last["reconciliation"],
        "batches": [{k: b[k] for k in ("batch_id", "mode", "rows_processed", "load_seconds", "reconcile_seconds", "tables",
                                        "extracted")} for b in batches],
        "simulated_changes": simulated,
        "layers": layers,
        "gold": {"lowest_completion_campaigns": campaigns, "lowest_completion_dealers": dealers},
        "dealer_history": history[:12],
        "contracts": {t: {"primary_key": c["primary_key"], "watermark": c["watermark"], "pii": c.get("pii", []),
                          "scd2": c.get("scd2", []), "expectations": [e["name"] for e in c.get("expectations", [])],
                          "source": c.get("source", "")} for t, c in cfg["tables"].items()},
    }
