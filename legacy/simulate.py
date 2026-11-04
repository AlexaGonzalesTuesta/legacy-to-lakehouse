"""One night of activity in the legacy system: new repair orders, status changes, owner updates,
dealer changes and a few deletes. Deterministic per day so runs are reproducible."""
from __future__ import annotations

import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from typing import Dict

from .build_legacy import BASE_DAY, FIRST, LAST, WMI, YEAR_CODE, make_vin, phone, ts


def simulate_day(path: Path, day: int, seed: int = 7) -> Dict[str, int]:
    """Apply day `day` (1-based) of changes. Every changed row gets updated_at on that day."""
    rng = random.Random(seed * 1000 + day)
    d = BASE_DAY + timedelta(days=day - 1)
    con = sqlite3.connect(path)
    changes = {"repair_orders_new": 0, "repair_orders_updated": 0, "repair_orders_deleted": 0,
               "owners_new": 0, "owners_updated": 0, "owners_deleted": 0, "dealers_updated": 0}

    owners = con.execute("SELECT vin, make, model, model_year, preferred_dealer FROM vehicle_owners WHERE is_deleted = 0").fetchall()
    campaigns = {}
    for c, mk, md, yr in con.execute("SELECT campaign_number, make, model, model_year FROM recalls"):
        campaigns.setdefault((mk, md, yr), []).append(c)
    next_id = con.execute("SELECT COUNT(*) FROM repair_orders").fetchone()[0] + 1

    # New recall repair orders opened today
    for _ in range(60):
        vin, mk, md, yr, dealer = rng.choice(owners)
        camps = campaigns.get((mk, md, yr))
        if not camps:
            continue
        con.execute("INSERT INTO repair_orders VALUES (?,?,?,?,?,?,?,?,0)",
                    (f"RO{next_id:07d}", vin, dealer, rng.choice(camps), "open", d.isoformat(), None, ts(d, rng)))
        next_id += 1
        changes["repair_orders_new"] += 1

    # Open and scheduled orders move forward
    active = con.execute("SELECT repair_order_id, status FROM repair_orders WHERE status IN ('open','scheduled') "
                         "AND is_deleted = 0 ORDER BY repair_order_id").fetchall()
    for ro, status in rng.sample(active, min(120, len(active))):
        if status == "open":
            con.execute("UPDATE repair_orders SET status='scheduled', updated_at=? WHERE repair_order_id=?", (ts(d, rng), ro))
        else:
            con.execute("UPDATE repair_orders SET status='completed', completed_at=?, updated_at=? WHERE repair_order_id=?",
                        (d.isoformat(), ts(d, rng), ro))
        changes["repair_orders_updated"] += 1

    # Orders entered by mistake are soft-deleted
    for ro, _ in rng.sample(active, 3):
        con.execute("UPDATE repair_orders SET is_deleted=1, updated_at=? WHERE repair_order_id=?", (ts(d, rng), ro))
        changes["repair_orders_deleted"] += 1

    # New owners register, some change their email, a few sell the car and are removed
    vehicles = sorted(campaigns)
    dealers = [r[0] for r in con.execute("SELECT dealer_code FROM dealers")]
    for _ in range(25):
        mk, md, yr = rng.choice(vehicles)
        if mk not in WMI or yr not in YEAR_CODE:
            continue
        first, last = rng.choice(FIRST), rng.choice(LAST)
        con.execute("INSERT OR IGNORE INTO vehicle_owners VALUES (?,?,?,?,?,?,?,?,?,0)",
                    (make_vin(rng, mk, yr), mk, md, yr, f"{first} {last}",
                     f"{first.lower()}.{last.lower()}{rng.randint(1, 999)}@example.com", phone(rng),
                     rng.choice(dealers), ts(d, rng)))
        changes["owners_new"] += 1
    for vin, *_ in rng.sample(owners, 10):
        con.execute("UPDATE vehicle_owners SET email = 'updated.' || email, updated_at=? WHERE vin=?", (ts(d, rng), vin))
        changes["owners_updated"] += 1
    for vin, *_ in rng.sample(owners, 2):
        con.execute("UPDATE vehicle_owners SET is_deleted=1, updated_at=? WHERE vin=?", (ts(d, rng), vin))
        changes["owners_deleted"] += 1

    # Dealer master changes that silver must keep history for (SCD Type 2)
    if day % 3 == 0:
        code = rng.choice(dealers)
        con.execute("UPDATE dealers SET region = CASE region WHEN 'Central' THEN 'Great Lakes' ELSE 'Central' END, "
                    "updated_at=? WHERE dealer_code=?", (ts(d, rng), code))
        changes["dealers_updated"] += 1
    if day == 5:
        code = rng.choice(dealers)
        con.execute("UPDATE dealers SET status='suspended', updated_at=? WHERE dealer_code=?", (ts(d, rng), code))
        changes["dealers_updated"] += 1
    con.commit()
    con.close()
    return changes
