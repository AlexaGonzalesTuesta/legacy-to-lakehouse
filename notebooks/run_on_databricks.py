# Databricks notebook source
# MAGIC %md
# MAGIC # Legacy to Lakehouse: run the migration on Databricks
# MAGIC
# MAGIC Builds the legacy recall operations database, lands an initial full extract and the nightly
# MAGIC incremental extracts in a Unity Catalog volume, and runs the PySpark pipeline into Delta tables:
# MAGIC
# MAGIC - `workspace.l2l_bronze.*` raw landed rows (restricted: contains raw PII)
# MAGIC - `workspace.l2l_silver.*` typed, validated, merged with `MERGE INTO`, PII hashed, plus `quarantine` and `dealers_history`
# MAGIC - `workspace.l2l_gold.*` recall completion and complaint trends
# MAGIC
# MAGIC Run it with **Run all**. It takes about 5 to 10 minutes on Free Edition serverless compute.

# COMMAND ----------

# MAGIC %pip install -q "PyYAML>=6.0,<7"

# COMMAND ----------

dbutils.widgets.text("catalog", "workspace", "Catalog")
dbutils.widgets.text("nights", "7", "Nightly loads to simulate")
catalog = dbutils.widgets.get("catalog")
nights = int(dbutils.widgets.get("nights"))

# COMMAND ----------

import os
import sys
from pathlib import Path

repo_root = os.path.abspath(os.path.join(os.getcwd(), ".."))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from lakehouse.demo import run_demo  # noqa: E402
from lakehouse.store import DeltaStore  # noqa: E402

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {catalog}.l2l COMMENT 'Landing zone for Legacy to Lakehouse'")
spark.sql(f"CREATE VOLUME IF NOT EXISTS {catalog}.l2l.landing COMMENT 'Nightly extracts from the legacy database'")
landing = f"/Volumes/{catalog}/l2l/landing/nightly"
full_landing = f"/Volumes/{catalog}/l2l/landing/full_reload"
for path in (landing, full_landing):
    dbutils.fs.rm(path, True)

# COMMAND ----------

store = DeltaStore(spark, catalog, "l2l")
full_store = DeltaStore(spark, catalog, "l2l_full")
run = run_demo(Path("/tmp/l2l"), days=nights, spark=spark, store=store, landing=landing,
               full_store=full_store, full_landing=full_landing, out=Path("/tmp/l2l/run.json"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Cutover readiness

# COMMAND ----------

display(spark.createDataFrame([
    (r["table"], r["legacy_rows"], r["lakehouse_rows"], r["missing"], r["extra"], r["changed"], r["status"])
    for r in run["reconciliation"]],
    "table string, legacy_rows long, lakehouse_rows long, missing long, extra long, changed long, status string"))

# COMMAND ----------

# MAGIC %sql
# MAGIC -- Why repair_orders is blocked
# MAGIC SELECT table_name, failed_rules, primary_key, batch_id FROM workspace.l2l_silver.quarantine ORDER BY table_name, primary_key

# COMMAND ----------

# MAGIC %sql
# MAGIC -- Recalls with the lowest repair completion
# MAGIC SELECT campaign_number, component_group, vehicles_affected, vehicles_repaired, completion_rate
# MAGIC FROM workspace.l2l_gold.recall_completion_by_campaign
# MAGIC WHERE vehicles_affected >= 20
# MAGIC ORDER BY completion_rate
# MAGIC LIMIT 10

# COMMAND ----------

# MAGIC %sql
# MAGIC -- Every change Delta recorded on the silver repair_orders table (one MERGE per night)
# MAGIC DESCRIBE HISTORY workspace.l2l_silver.repair_orders
