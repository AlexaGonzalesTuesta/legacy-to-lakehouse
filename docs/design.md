# Design decisions

**Watermark extracts instead of full copies.** Each table names a column that changes whenever a row
changes (`updated_at`). The extractor ships only rows newer than the last successful extract. Nightly
loads processed about 1% of the rows a full reload does. Trade-off: a row updated without touching
`updated_at` is missed. A production system would use database change data capture (CDC) instead.

**Bronze keeps raw text.** Landed files are stored exactly as received, plus batch id, file path and load
time, so any silver result can be rebuilt and audited. Bronze holds raw PII, so access is restricted.

**Silver uses MERGE.** On Databricks each night is one `MERGE INTO` per table: update changed rows,
insert new ones, and delete rows the legacy system soft-deleted (`is_deleted`). Locally the same
semantics run on Parquet so tests do not need a Databricks workspace.

**Bad rows are quarantined, not dropped.** Every contract has quality rules. A failing row goes to
`silver.quarantine` with the rule it broke, and reconciliation reports it as missing. Silently dropping
it would make the migration look complete when it is not.

**PII is hashed with a salt.** Owner name, email and phone become salted SHA-256 hashes in silver. Equal
values still match for joins and deduplication, but cannot be read. The salt comes from an environment
secret in production.

**Dealer history is SCD Type 2.** When a dealer changes region or status, the old row is closed and a new
one opened, so past recall reports still roll up to the region the dealer belonged to at the time.

**Reconciliation compares keys and hashes.** The legacy side writes every live primary key with a SHA-256
of its business columns. Spark computes the same hash from silver, and a full outer join finds missing,
extra and changed rows. PII and the watermark are excluded from the hash, because silver changes PII on
purpose.

**Gold is rebuilt each night.** At this size a full rebuild is simple and cheap. At scale, gold would be
updated incrementally from the silver change feed.
