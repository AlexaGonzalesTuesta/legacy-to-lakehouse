"""Pure DataFrame transformations. No I/O, so each one is unit-tested on its own."""
from __future__ import annotations

from typing import Any, Dict, List

from pyspark.sql import DataFrame, Window
from pyspark.sql import functions as F
from pyspark.sql.types import StringType, StructField, StructType

# NHTSA uses different component names in recalls ("ENGINE AND ENGINE COOLING:ENGINE:...") and
# complaints ("ENGINE"). Silver conforms both to one component group so they can be joined.
COMPONENT_GROUPS = [
    ("AIR BAG", "Air bags"), ("SEAT BELT", "Seat belts"), ("SEAT", "Seats"), ("PARKING BRAKE", "Brakes"),
    ("BRAKE", "Brakes"), ("STEERING", "Steering"), ("SUSPENSION", "Suspension"), ("TRACTION BATTERY", "Electrical"),
    ("POWER TRAIN", "Powertrain"), ("ENGINE", "Engine"), ("FUEL", "Fuel and propulsion"),
    ("PROPULSION", "Fuel and propulsion"), ("ELECTRICAL", "Electrical"), ("LIGHTING", "Lighting"),
    ("BACK OVER", "Rear camera"), ("VISIBILITY", "Visibility"), ("STRUCTURE", "Structure"), ("WHEEL", "Wheels and tires"),
    ("TIRE", "Wheels and tires"), ("LATCH", "Latches and locks"), ("FORWARD COLLISION", "Driver assistance"),
    ("LANE", "Driver assistance"), ("VEHICLE SPEED", "Driver assistance"), ("EQUIPMENT", "Equipment"),
]


def landing_schema(contract: Dict[str, Any]) -> StructType:
    """Landing files are read as text with the contract's column order; typing happens in silver."""
    return StructType([StructField(c, StringType(), True) for c in contract["columns"]])


def add_bronze_metadata(df: DataFrame, batch_id: int, source: str) -> DataFrame:
    return (df.withColumn("_batch_id", F.lit(batch_id))
              .withColumn("_ingested_at", F.current_timestamp())
              .withColumn("_source", F.lit(source)))


def cast_to_contract(df: DataFrame, contract: Dict[str, Any]) -> DataFrame:
    cols = []
    for name, typ in contract["columns"].items():
        c = F.trim(F.col(name))
        c = F.when(c == "", None).otherwise(c)
        if typ == "int":
            c = c.cast("int")
        elif typ == "date":
            c = F.to_date(c, "yyyy-MM-dd")
        elif typ == "timestamp":
            c = F.to_timestamp(c, "yyyy-MM-dd HH:mm:ss")
        elif typ == "boolean":
            c = F.lower(c) == F.lit("true")
        cols.append(c.alias(name))
    return df.select(*cols)


def component_group(col: str) -> F.Column:
    first = F.upper(F.split(F.coalesce(F.col(col), F.lit("")), ",").getItem(0))
    expr = F.lit("Other")
    for needle, group in reversed(COMPONENT_GROUPS):
        expr = F.when(first.contains(needle), F.lit(group)).otherwise(expr)
    return F.when(first.contains("UNKNOWN"), F.lit("Unknown")).otherwise(expr)


def check_expectations(df: DataFrame, contract: Dict[str, Any]) -> DataFrame:
    """Add _failed_rules: the names of every expectation the row breaks (a null result counts as a failure)."""
    rules = contract.get("expectations", [])
    if not rules:
        return df.withColumn("_failed_rules", F.array().cast("array<string>"))
    checks = [F.when(F.coalesce(F.expr(r["rule"]), F.lit(False)), F.lit(None)).otherwise(F.lit(r["name"])) for r in rules]
    return df.withColumn("_failed_rules", F.filter(F.array(*checks), lambda x: x.isNotNull()))


def latest_per_key(df: DataFrame, keys: List[str], watermark: str) -> DataFrame:
    """Keep the newest version of each row in a batch (a row can change several times a day)."""
    w = Window.partitionBy(*keys).orderBy(F.col(watermark).desc())
    return df.withColumn("_rn", F.row_number().over(w)).filter("_rn = 1").drop("_rn")


def hash_pii(df: DataFrame, pii: List[str], salt: str) -> DataFrame:
    """Replace each PII column with a salted SHA-256 hash, renamed <col>_sha256.
    Equal values still match (for joins and dedupe) but cannot be read back."""
    for c in pii:
        df = df.withColumn(f"{c}_sha256", F.sha2(F.concat(F.lit(salt), F.coalesce(F.col(c), F.lit(""))), 256)).drop(c)
    return df


def row_hash(df: DataFrame, columns: List[str]) -> DataFrame:
    """Same canonical form as legacy/extract.py: text values joined by '|', nulls as ''."""
    parts = [F.coalesce(F.col(c).cast("string"), F.lit("")) for c in columns]
    return df.withColumn("row_hash", F.sha2(F.concat_ws("|", *parts), 256))


def scd2(history: DataFrame, incoming: DataFrame, key: str, tracked: List[str], effective: str) -> DataFrame:
    """Slowly changing dimension, Type 2. A change to a tracked column closes the current row
    (valid_to, is_current = false) and opens a new one, so past reports keep their region."""
    inc = incoming.select(key, *tracked, F.col(effective).alias("valid_from"))
    if history is None:
        return inc.withColumn("valid_to", F.lit(None).cast("timestamp")).withColumn("is_current", F.lit(True))
    current = history.filter("is_current")
    joined = inc.alias("i").join(current.alias("c"), on=key, how="left")
    differs = F.lit(False)
    for col in tracked:
        differs = differs | ~F.col(f"i.{col}").eqNullSafe(F.col(f"c.{col}"))
    changed = joined.filter(F.col("c.valid_from").isNull() | differs).select(key, *[F.col(f"i.{c}") for c in tracked],
                                                                              F.col("i.valid_from"))
    changed_keys = changed.select(key)
    to_close = current.join(changed_keys, on=key, how="left_semi")
    closed = to_close.alias("c").join(changed.alias("n"), on=key).select(
        key, *[F.col(f"c.{c}") for c in tracked], F.col("c.valid_from"), F.col("n.valid_from").alias("valid_to"),
        F.lit(False).alias("is_current"))
    untouched = history.join(to_close.select(key, "valid_from"), on=[key, "valid_from"], how="left_anti")
    opened = changed.withColumn("valid_to", F.lit(None).cast("timestamp")).withColumn("is_current", F.lit(True))
    cols = [key, *tracked, "valid_from", "valid_to", "is_current"]
    return untouched.select(*cols).unionByName(closed.select(*cols)).unionByName(opened.select(*cols))
