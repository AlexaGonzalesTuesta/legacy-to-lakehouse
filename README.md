# Legacy to Lakehouse

[![CI](https://github.com/AlexaGonzalesTuesta/legacy-to-lakehouse/actions/workflows/ci.yml/badge.svg)](https://github.com/AlexaGonzalesTuesta/legacy-to-lakehouse/actions/workflows/ci.yml)

A PySpark pipeline that migrates a legacy recall operations database into a Databricks lakehouse with nightly incremental loads, and proves, table by table, that the lakehouse copy matches the source before the legacy system is switched off.

**[Open the cutover readiness board](https://alexagonzalestuesta.github.io/legacy-to-lakehouse/)**: rebuilt by GitHub Actions on every push from a full run of the pipeline.

![Cutover readiness board: blocked table, nightly loads, recall completion, pipeline layers](https://alexagonzalestuesta.github.io/legacy-to-lakehouse/demo.gif)

## Why this exists

Most on-prem to cloud migrations do not fail on the copy. They fail on trust. Nobody can show that the new tables hold exactly what the old ones did, so the legacy database keeps running next to the cloud platform, and the company pays for both. This project builds the pipeline a migration team runs every night, and the check a business owner needs before signing off:

1. **Extract** only rows that changed since the last night (watermark on `updated_at`).
2. **Bronze:** land raw rows with batch id, source file and load time.
3. **Silver:** type, validate, deduplicate, hash personal data, and `MERGE` into Delta tables, with soft deletes, a quarantine table for bad rows, and SCD Type 2 history for dealers.
4. **Gold:** recall repair completion by campaign and by dealer, and complaint trends by model and component.
5. **Reconcile:** compare every legacy primary key and row hash with the lakehouse, and mark each table **Ready** or **Blocked** with the reason.

## What's different

- **It answers the cutover question.** The board shows missing, extra and changed rows per table, and why. In the demo, `repair_orders` is blocked by 8 bad legacy rows (planted on purpose), and the board names the two rules they broke.
- **Real data where it matters.** 234 NHTSA recall records and 11,107 NHTSA owner complaints for GM vehicles move through the pipeline. Dealer, owner and repair tables are synthetic, so no real person's data is in the repo.
- **Privacy built in.** Owner name, email and phone are salted SHA-256 hashes from silver onward. Quarantined rows are hashed too.
- **Cost measured, not claimed.** Each nightly load is compared with a full reload of the same data.
- **Same code on Databricks and in CI.** The notebook runs on serverless compute with Delta `MERGE INTO`; GitHub Actions runs the same pipeline on local Spark with Parquet.

## 2-minute tour

1. Open the [board](https://alexagonzalestuesta.github.io/legacy-to-lakehouse/). Four of five tables are ready for cutover.
2. The blocked **repair_orders** row opens on its own. Eight legacy rows were quarantined: 5 with an invalid status, 3 completed before they were opened. The panel gives example keys and the query to see them.
3. Open **Nightly loads** in the left menu. Each night processes about 216 rows instead of 19,840.
4. Open **Recall completion**. The gold table ranks real GM recall campaigns by how many affected vehicles have been repaired; switch to **Dealers** for the dealers furthest behind.
5. Open **Pipeline** to see row counts in every layer and the dealer history kept by SCD Type 2.

## Results

From the run the board shows (`python -m lakehouse --days 7`):

| Measure | Result |
|---|---|
| Tables ready for cutover | 4 of 5 (`repair_orders` blocked by the 8 planted rows) |
| Legacy rows matched in the lakehouse | 19,797 of 19,805 (the 8 missing are exactly the quarantined rows) |
| Rows processed per nightly load | 216 on average, 98.9% fewer than a full reload (19,840) |
| Load time per night vs. full reload, local Spark | 7.7 s vs. 9.8 s (fixed Spark overhead dominates at this size) |
| Reconciliation time per night | About 3 s for all five tables |
| PII columns hashed before silver | 3 of 3 |
| Tests | 11, including an end-to-end migration run |

## How it works

```
legacy SQLite database ──nightly──► landing zone (CSV + manifest + key/hash snapshot)
        (on-prem)                            │
                                             ▼
                          bronze ──► silver (MERGE, quarantine, PII hash, SCD2) ──► gold
                                             │
                               reconciliation vs. legacy snapshot ──► cutover board
```

| Path | What it does |
|---|---|
| `config/tables.yml` | Data contract per table: primary key, watermark, PII, SCD2 columns, quality rules |
| `legacy/` | The on-prem side: database builder, nightly change simulator, watermark extractor |
| `lakehouse/transforms.py` | Pure PySpark transformations: typing, expectations, dedupe, PII hashing, SCD2, row hash |
| `lakehouse/pipeline.py` | Bronze, silver, gold and reconciliation for one batch |
| `lakehouse/store.py` | Delta (MERGE INTO) and Parquet storage with the same interface |
| `notebooks/run_on_databricks.py` | Runs everything on Databricks into Unity Catalog Delta tables |
| `site/` | The cutover readiness board |
| `docs/` | Databricks setup, cutover runbook, design decisions |

## Run it

**On Databricks (recommended):** follow [docs/databricks-setup.md](docs/databricks-setup.md). Clone the repo as a Git folder, open `notebooks/run_on_databricks`, and click **Run all**.

**Locally:** needs Python 3.10+ and Java 17. On Windows, local Spark also needs Hadoop's `winutils.exe`, so Databricks or WSL is easier.

```
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest -q
python -m lakehouse --days 7
python -m http.server -d site 8000
```

Then open http://localhost:8000.

## Limitations and next steps

- **Watermarks miss silent updates.** A legacy row changed without touching `updated_at` is never extracted. Production would read the database's change data capture (CDC) log.
- **The legacy database is SQLite.** It stands in for SQL Server or Oracle. The extractor would use a JDBC or ODBC connection in practice.
- **Gold is rebuilt each night.** Fine at this size; at scale it would update incrementally from the Delta change data feed.
- **Local runs use Parquet, not Delta.** The MERGE semantics are the same and tested, but Delta features (time travel, `DESCRIBE HISTORY`) only exist in the Databricks run.
- **Timing is from a small dataset.** Rows processed is the reliable cost signal here; the seconds are dominated by Spark start-up work.
- **Synthetic tables.** Dealers, owners and repair orders are generated, and the 8 bad rows were planted to prove the quarantine and cutover checks work.

## Why I built this

During my IT Business Analyst internship at Abbott, I built a Power BI dashboard on Azure Synapse query logs so the team could decide which BI views to migrate to Databricks. That work showed me that the hardest part of a migration is not moving the data. It is proving the new copy is complete and right, so people trust it enough to turn the old system off. I built this to practice the data engineering side of that problem in PySpark on Databricks, using real recall and complaint data from the automotive industry.

## How I built it

I started from the checklist a migration team works through, then wrote one data contract per table in YAML so every rule is in one reviewable place. I kept every PySpark transformation a pure function so it could be tested on its own, and put storage behind one interface, so the same pipeline runs on Delta in Databricks and on Parquet in GitHub Actions. I planted known bad rows in the legacy data to prove the quarantine and reconciliation catch them, and I report load times honestly, including where Spark overhead hides the savings at small scale.
