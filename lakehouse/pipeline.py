"""Bronze -> silver -> gold for one landed batch, then reconciliation against the legacy system."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from legacy.extract import hash_columns
from . import transforms as T
from .store import Store

ROOT = Path(__file__).resolve().parent.parent
DEMO_SALT = "demo-salt-not-for-production"


def load_contracts(path: Path = ROOT / "config" / "tables.yml") -> Dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def salt(cfg: Dict[str, Any]) -> str:
    return os.environ.get(cfg.get("hash_salt_env", ""), DEMO_SALT)


def read_landing(spark: SparkSession, landing: str, table: str, batch_id: int, contract: Dict[str, Any]) -> DataFrame:
    path = f"{landing}/{table}/batch_id={batch_id:04d}"
    return (spark.read.option("header", True).option("escape", '"').option("multiLine", True)
            .schema(T.landing_schema(contract)).csv(path)
            .withColumn("_source_file", F.col("_metadata.file_path")))


class Pipeline:
    def __init__(self, spark: SparkSession, store: Store, landing: str, cfg: Optional[Dict[str, Any]] = None):
        self.spark = spark
        self.store = store
        self.landing = landing
        self.cfg = cfg or load_contracts()
        self.contracts = self.cfg["tables"]

    # ---------- one table, one batch ----------
    def process_table(self, table: str, batch_id: int) -> Dict[str, Any]:
        c = self.contracts[table]
        keys, wm = c["primary_key"], c["watermark"]
        delete_flag = "is_deleted" if "is_deleted" in c["columns"] else None
        t0 = time.perf_counter()
        raw = read_landing(self.spark, self.landing, table, batch_id, c)
        landed = raw.count()
        m: Dict[str, Any] = {"table": table, "batch_id": batch_id, "landed": landed, "quarantined": 0,
                             "inserted": 0, "updated": 0, "deleted": 0}
        if landed == 0:
            m["seconds"] = round(time.perf_counter() - t0, 2)
            m["silver_rows"] = self.store.read("silver", table).count() if self.store.exists("silver", table) else 0
            return m

        # Bronze: raw text exactly as landed, plus where and when it arrived.
        self.store.append(T.add_bronze_metadata(raw, batch_id, c.get("source", "legacy")), "bronze", table)

        # Silver: typed, validated, deduplicated, PII hashed, merged.
        typed = T.check_expectations(T.cast_to_contract(raw, c), c)
        pii = c.get("pii", [])
        bad = typed.filter(F.size("_failed_rules") > 0)
        n_bad = bad.count()
        if n_bad:
            q = T.hash_pii(bad, pii, salt(self.cfg)).select(
                F.lit(table).alias("table_name"), F.lit(batch_id).alias("batch_id"),
                F.concat_ws(", ", "_failed_rules").alias("failed_rules"),
                F.concat_ws("|", *[F.col(k).cast("string") for k in keys]).alias("primary_key"),
                F.to_json(F.struct(*[col for col in T.hash_pii(bad, pii, salt(self.cfg)).columns if col != "_failed_rules"])).alias("row_json"),
                F.current_timestamp().alias("quarantined_at"))
            self.store.append(q, "silver", "quarantine")
        m["quarantined"] = n_bad

        good = T.latest_per_key(typed.filter(F.size("_failed_rules") == 0).drop("_failed_rules"), keys, wm)
        if table in ("recalls", "complaints"):
            good = good.withColumn("component_group", T.component_group("component" if table == "recalls" else "components"))
        good = T.hash_pii(good, pii, salt(self.cfg))

        if self.store.exists("silver", table):
            existing = self.store.read("silver", table).select(*keys).withColumn("_exists", F.lit(True))
            flagged = good.join(existing, on=keys, how="left")
            deleted_cond = F.col(delete_flag) if delete_flag else F.lit(False)
            counts = flagged.select(
                F.sum(F.when(F.col("_exists") & ~deleted_cond, 1).otherwise(0)).alias("updated"),
                F.sum(F.when(F.col("_exists") & deleted_cond, 1).otherwise(0)).alias("deleted"),
                F.sum(F.when(F.col("_exists").isNull() & ~deleted_cond, 1).otherwise(0)).alias("inserted")).collect()[0]
            m.update({k: int(counts[k] or 0) for k in ("updated", "deleted", "inserted")})
        else:
            m["inserted"] = good.filter(~F.col(delete_flag)).count() if delete_flag else good.count()
        self.store.merge(good, "silver", table, keys, delete_flag)

        if "scd2" in c:
            hist = self.store.read("silver", f"{table}_history") if self.store.exists("silver", f"{table}_history") else None
            self.store.overwrite(T.scd2(hist, good, keys[0], c["scd2"], wm), "silver", f"{table}_history")

        m["silver_rows"] = self.store.read("silver", table).count()
        m["seconds"] = round(time.perf_counter() - t0, 2)
        return m

    # ---------- gold ----------
    def build_gold(self) -> Dict[str, int]:
        s = lambda t: self.store.read("silver", t)  # noqa: E731
        recalls = s("recalls").select("campaign_number", "make", "model", "model_year", "component_group", "park_it")
        owners = s("vehicle_owners").select("vin", "make", "model", "model_year", "preferred_dealer")
        dealers = s("dealers").select("dealer_code", "dealer_name", "city", "state", "region", "status")
        orders = s("repair_orders").filter("status = 'completed'").select("vin", "campaign_number").distinct() \
            .withColumn("repaired", F.lit(True))

        # Every owner vehicle covered by a recall, and whether the repair is done.
        exposure = (owners.join(F.broadcast(recalls), on=["make", "model", "model_year"])
                    .join(orders, on=["vin", "campaign_number"], how="left")
                    .withColumn("repaired", F.coalesce("repaired", F.lit(False))))
        by_campaign = (exposure.groupBy("campaign_number", "component_group", "park_it")
                       .agg(F.countDistinct("vin").alias("vehicles_affected"),
                            F.sum(F.col("repaired").cast("int")).alias("vehicles_repaired"),
                            F.concat_ws(", ", F.array_sort(F.collect_set(F.concat_ws(" ", "make", "model")))).alias("vehicles"))
                       .withColumn("completion_rate", F.round(F.col("vehicles_repaired") / F.col("vehicles_affected"), 4)))
        by_dealer = (exposure.groupBy(F.col("preferred_dealer").alias("dealer_code"))
                     .agg(F.count("*").alias("open_recall_repairs_needed"),
                          F.sum(F.col("repaired").cast("int")).alias("repairs_completed"))
                     .join(F.broadcast(dealers), on="dealer_code", how="left")
                     .withColumn("completion_rate", F.round(F.col("repairs_completed") / F.col("open_recall_repairs_needed"), 4)))
        trend = (s("complaints").withColumn("month", F.date_format("filed_date", "yyyy-MM"))
                 .groupBy("make", "model", "component_group", "month")
                 .agg(F.count("*").alias("complaints"), F.sum(F.col("crash").cast("int")).alias("crashes"),
                      F.sum("injuries").alias("injuries")))
        out = {}
        for name, df in (("recall_completion_by_campaign", by_campaign), ("recall_completion_by_dealer", by_dealer),
                         ("complaint_trend_monthly", trend)):
            self.store.overwrite(df, "gold", name)
            out[name] = self.store.read("gold", name).count()
        return out

    # ---------- reconciliation ----------
    def reconcile(self, table: str, batch_id: int, manifest: Dict[str, Any]) -> Dict[str, Any]:
        c = self.contracts[table]
        keys = c["primary_key"]
        legacy = (self.spark.read.option("header", True).option("escape", '"').option("multiLine", True)
                  .csv(f"{self.landing}/_reconciliation/{table}/batch_id={batch_id:04d}")
                  .withColumnRenamed("row_hash", "legacy_hash"))
        lake = T.row_hash(self.store.read("silver", table), hash_columns(c))
        lake = lake.select(*[F.col(k).cast("string").alias(k) for k in keys], F.col("row_hash").alias("lake_hash"))
        both = legacy.join(lake, on=keys, how="full_outer")
        key_str = F.concat_ws("|", *[F.col(k) for k in keys])
        stats = both.select(
            F.sum(F.when(F.col("legacy_hash").isNotNull(), 1).otherwise(0)).alias("legacy_rows"),
            F.sum(F.when(F.col("lake_hash").isNotNull(), 1).otherwise(0)).alias("lakehouse_rows"),
            F.sum(F.when(F.col("lake_hash").isNull(), 1).otherwise(0)).alias("missing"),
            F.sum(F.when(F.col("legacy_hash").isNull(), 1).otherwise(0)).alias("extra"),
            F.sum(F.when(F.col("legacy_hash").isNotNull() & F.col("lake_hash").isNotNull()
                         & (F.col("legacy_hash") != F.col("lake_hash")), 1).otherwise(0)).alias("changed")).collect()[0]
        res = {k: int(stats[k] or 0) for k in ("legacy_rows", "lakehouse_rows", "missing", "extra", "changed")}
        samples = {}
        for kind, cond in (("missing", F.col("lake_hash").isNull()), ("extra", F.col("legacy_hash").isNull()),
                           ("changed", F.col("legacy_hash") != F.col("lake_hash"))):
            if res[kind]:
                samples[kind] = [r[0] for r in both.filter(cond).select(key_str).orderBy(key_str).limit(5).collect()]
        reasons: List[Dict[str, Any]] = []
        if res["missing"] and self.store.exists("silver", "quarantine"):
            q = (self.store.read("silver", "quarantine").filter(F.col("table_name") == table)
                 .groupBy("failed_rules").agg(F.countDistinct("primary_key").alias("rows")).orderBy(F.desc("rows")).collect())
            reasons = [{"rule": r["failed_rules"], "rows": int(r["rows"])} for r in q]
        res.update({"table": table, "primary_key": keys, "samples": samples, "quarantine_reasons": reasons,
                    "watermark": manifest["tables"][table]["watermark_to"],
                    "status": "ready" if not (res["missing"] or res["extra"] or res["changed"]) else "blocked",
                    "matched_rows": res["lakehouse_rows"] - res["extra"] - res["changed"]})
        return res

    def run_batch(self, batch_id: int, manifest: Dict[str, Any], reconcile: bool = True) -> Dict[str, Any]:
        t0 = time.perf_counter()
        tables = [self.process_table(t, batch_id) for t in self.contracts]
        gold = self.build_gold()
        t1 = time.perf_counter()
        recon = [self.reconcile(t, batch_id, manifest) for t in self.contracts] if reconcile else []
        return {"batch_id": batch_id, "mode": manifest["mode"], "tables": tables, "gold": gold,
                "reconciliation": recon, "load_seconds": round(t1 - t0, 2),
                "reconcile_seconds": round(time.perf_counter() - t1, 2),
                "rows_processed": sum(t["landed"] for t in tables)}


def save_json(obj: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, default=str))
