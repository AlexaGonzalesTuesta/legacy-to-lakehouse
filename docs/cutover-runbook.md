# Cutover runbook

How a team uses this pipeline to retire a legacy table. One table at a time.

| Step | Done when | Owner |
|---|---|---|
| 1. Write the data contract in `config/tables.yml` | Primary key, watermark, PII columns and quality rules agreed | Data engineer and data owner |
| 2. Initial full load | Bronze, silver and gold built; quarantine reviewed | Data engineer |
| 3. Nightly incremental loads | Runs on schedule; rows processed stay a small share of the table | Data engineer |
| 4. Reconciliation is green three nights in a row | Missing, extra and changed are all 0 | Data engineer |
| 5. Fix or accept every quarantined row | Rows fixed in the legacy system, or rule changed with the data owner's approval | Data owner |
| 6. Business sign-off | Reports built on gold match the legacy reports | Business owner |
| 7. Switch readers to the lakehouse | Dashboards and jobs point at silver or gold | Data engineer |
| 8. Freeze legacy writes, run a final incremental load, reconcile | Reconciliation green after the freeze | Data engineer |
| 9. Decommission the legacy table | Storage and licences released | Platform team |

A table is never switched off while the board shows it as **Blocked**.
