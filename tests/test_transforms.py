from datetime import datetime

from pyspark.sql import functions as F

from lakehouse import transforms as T
from lakehouse.store import ParquetStore, merge_sql
from legacy.extract import fmt, row_hash

CONTRACT = {"columns": {"id": "string", "n": "int", "d": "date", "ok": "boolean", "u": "timestamp"},
            "expectations": [{"name": "n_positive", "rule": "n > 0"}, {"name": "d_present", "rule": "d IS NOT NULL"}]}


def test_cast_and_expectations(spark):
    df = spark.createDataFrame([(" a ", "3", "2026-10-01", "true", "2026-10-01 08:00:00"),
                                ("b", "-1", "", "false", "2026-10-02 08:00:00")], list(CONTRACT["columns"]))
    out = {r["id"]: r for r in T.check_expectations(T.cast_to_contract(df, CONTRACT), CONTRACT).collect()}
    assert out["a"]["n"] == 3 and out["a"]["ok"] is True and out["a"]["_failed_rules"] == []
    assert out["b"]["d"] is None and out["b"]["_failed_rules"] == ["n_positive", "d_present"]


def test_latest_per_key_keeps_newest(spark):
    df = spark.createDataFrame([("x", datetime(2026, 1, 1), "old"), ("x", datetime(2026, 1, 2), "new")], ["k", "u", "v"])
    assert [r["v"] for r in T.latest_per_key(df, ["k"], "u").collect()] == ["new"]


def test_pii_is_hashed_and_raw_column_removed(spark):
    df = spark.createDataFrame([("1GN123", "maria@example.com")], ["vin", "email"])
    out = T.hash_pii(df, ["email"], "salt")
    assert "email" not in out.columns and len(out.collect()[0]["email_sha256"]) == 64
    again = T.hash_pii(df, ["email"], "salt").collect()[0]["email_sha256"]
    assert again == out.collect()[0]["email_sha256"]


def test_spark_row_hash_matches_legacy_extract_hash(spark):
    """Reconciliation only works if both sides hash a row identically."""
    df = spark.createDataFrame([("RO1", 2024, None, True)], "id string, year int, note string, flag boolean")
    spark_hash = T.row_hash(df, ["id", "year", "note", "flag"]).collect()[0]["row_hash"]
    legacy = row_hash([fmt("id", "RO1"), fmt("year", 2024), fmt("note", None), fmt("is_deleted", 1)])
    assert spark_hash == legacy


def test_component_groups_conform_recall_and_complaint_names(spark):
    df = spark.createDataFrame([("ENGINE AND ENGINE COOLING:ENGINE:HARD PARTS",), ("POWER TRAIN,ENGINE",),
                                ("SEAT BELTS:CRITICAL FASTENERS",), ("ELECTRICAL SYSTEM:PROPULSION SYSTEM:TRACTION BATTERY",),
                                ("SERVICE BRAKES, HYDRAULIC:BRAKE FLUID",), ("UNKNOWN OR OTHER",)], ["c"])
    got = [r[0] for r in df.select(T.component_group("c")).collect()]
    assert got == ["Engine", "Powertrain", "Seat belts", "Electrical", "Brakes", "Unknown"]


def test_scd2_closes_old_row_and_opens_new_one(spark):
    first = spark.createDataFrame([("D1", "Central", "active", datetime(2025, 1, 1))], ["dealer_code", "region", "status", "u"])
    hist = T.scd2(None, first, "dealer_code", ["region", "status"], "u")
    change = spark.createDataFrame([("D1", "West", "active", datetime(2026, 1, 1))], ["dealer_code", "region", "status", "u"])
    hist = T.scd2(hist, change, "dealer_code", ["region", "status"], "u").orderBy("valid_from").collect()
    assert [(r["region"], r["is_current"]) for r in hist] == [("Central", False), ("West", True)]
    assert hist[0]["valid_to"] == datetime(2026, 1, 1)
    same = T.scd2(spark.createDataFrame(hist), change, "dealer_code", ["region", "status"], "u")
    assert same.count() == 2  # no change, no new version


def test_parquet_merge_inserts_updates_and_deletes(spark, tmp_path):
    store = ParquetStore(spark, str(tmp_path))
    schema = "id string, v string, is_deleted boolean"
    store.merge(spark.createDataFrame([("a", "1", False), ("b", "1", False)], schema), "silver", "t", ["id"], "is_deleted")
    store.merge(spark.createDataFrame([("a", "2", False), ("b", "1", True), ("c", "1", False)], schema),
                "silver", "t", ["id"], "is_deleted")
    assert sorted((r["id"], r["v"]) for r in store.read("silver", "t").collect()) == [("a", "2"), ("c", "1")]


def test_merge_sql_handles_soft_deletes():
    sql = merge_sql("w.s.t", "v", ["id"], ["id", "v", "is_deleted"], "is_deleted")
    assert "WHEN MATCHED AND s.`is_deleted` = true THEN DELETE" in sql
    assert sql.index("DELETE") < sql.index("UPDATE SET")
    assert "WHEN NOT MATCHED AND (s.`is_deleted` IS NULL OR s.`is_deleted` = false) THEN INSERT" in sql
