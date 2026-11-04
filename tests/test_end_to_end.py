import csv
import json

from legacy.build_legacy import PLANTED, build
from legacy.extract import extract_batch
from legacy.simulate import simulate_day
from lakehouse.demo import run_demo
from lakehouse.pipeline import load_contracts
from lakehouse.store import ParquetStore


def test_incremental_extract_only_ships_changed_rows(tmp_path):
    cfg = load_contracts()["tables"]
    db = tmp_path / "legacy.db"
    build(db)
    full = extract_batch(db, tmp_path / "landing", cfg, 0, tmp_path / "state.json")
    simulate_day(db, 1)
    night = extract_batch(db, tmp_path / "landing", cfg, 1, tmp_path / "state.json")
    assert full["mode"] == "full" and night["mode"] == "incremental"
    assert night["tables"]["complaints"]["rows"] == 0
    assert 0 < night["tables"]["repair_orders"]["rows"] < full["tables"]["repair_orders"]["rows"] / 10


def test_full_migration_run(spark, tmp_path):
    run = run_demo(tmp_path, days=2, spark=spark, out=tmp_path / "run.json", log=lambda *_: None)
    rec = {r["table"]: r for r in run["reconciliation"]}
    # The planted bad repair orders are quarantined, so that table is blocked, and only that table.
    assert rec["repair_orders"]["status"] == "blocked"
    assert rec["repair_orders"]["missing"] == sum(PLANTED.values())
    assert {r["rule"] for r in rec["repair_orders"]["quarantine_reasons"]} == {"status_values", "completed_after_opened"}
    assert all(rec[t]["status"] == "ready" for t in ("recalls", "complaints", "dealers", "vehicle_owners"))
    assert rec["complaints"]["legacy_rows"] > 10000  # the real NHTSA complaints made it across
    # Nightly loads are a small fraction of a full reload
    assert run["summary"]["rows_saved_pct"] > 95
    # Raw PII never reaches silver
    owners = ParquetStore(spark, str(tmp_path / "lakehouse")).read("silver", "vehicle_owners")
    assert not {"owner_name", "email", "phone"} & set(owners.columns)
    assert {"owner_name_sha256", "email_sha256", "phone_sha256"} <= set(owners.columns)
    assert json.loads((tmp_path / "run.json").read_text())["summary"]["tables"] == 5


def test_real_source_files_are_present():
    from lakehouse.pipeline import ROOT
    with open(ROOT / "data" / "raw" / "nhtsa_recalls.csv", encoding="utf-8") as f:
        assert len(list(csv.DictReader(f))) > 100
