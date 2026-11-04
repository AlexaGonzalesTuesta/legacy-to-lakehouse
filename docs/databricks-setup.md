# Run it on Databricks (Free Edition works)

About 15 minutes, most of it waiting for the run.

## 1. Clone the repo into your workspace

1. In Databricks, click **Workspace** in the left sidebar, then **Home**.
2. Click **Create > Git folder**.
3. Paste `https://github.com/AlexaGonzalesTuesta/legacy-to-lakehouse` as the Git repository URL and click **Create Git folder**.

## 2. Run the pipeline

1. Open the folder **legacy-to-lakehouse > notebooks > run_on_databricks**.
2. At the top right, connect to **Serverless**.
3. Click **Run all**. The defaults are catalog `workspace` and 7 nightly loads.

The notebook builds the legacy database on the driver, lands each nightly extract in the volume
`workspace.l2l.landing`, and runs bronze, silver and gold into Delta tables. Silver tables are
updated with `MERGE INTO`.

## 3. Look at what it built

- **Catalog > workspace > l2l_silver > repair_orders > History** shows one MERGE per night.
- **Catalog > workspace > l2l_silver > quarantine** shows the 8 bad legacy rows and the rule each one broke.
- **Catalog > workspace > l2l_silver > vehicle_owners > Sample data** shows the hashed PII columns.
- **Catalog > workspace > l2l_gold > recall_completion_by_campaign** is the business table.
- The last cells of the notebook show the cutover readiness table and the lowest-completion recalls.

To run again from scratch, click **Run all** again. The notebook drops and recreates the `l2l_*` schemas.
