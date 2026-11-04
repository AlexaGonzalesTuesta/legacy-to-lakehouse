"""Build the legacy recall operations database.

Real tables: NHTSA recalls and complaints for GM vehicles.
Synthetic tables: dealers, vehicle owners and repair orders. Every person is fictional
(example.com emails, 555-01xx phone numbers). A few known bad rows are planted so the
pipeline's quarantine and the cutover check have something real to catch.
"""
from __future__ import annotations

import csv
import random
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
BASE_DAY = date(2026, 10, 26)  # day 1 of the simulated nightly loads

FIRST = ["Maria", "James", "Aaliyah", "Wei", "Carlos", "Emily", "Jamal", "Sofia", "Daniel", "Grace", "Luis", "Hannah",
         "Omar", "Chloe", "Ethan", "Mei", "Andre", "Olivia", "Rahul", "Zoe", "Diego", "Nora", "Tyler", "Fatima"]
LAST = ["Garcia", "Johnson", "Nguyen", "Smith", "Patel", "Brown", "Lopez", "Kim", "Williams", "Martinez", "Davis",
        "Chen", "Wilson", "Anderson", "Thomas", "Hernandez", "Moore", "Jackson", "Lee", "Walker", "Young", "Allen"]
CITIES = [("Detroit", "MI", "Great Lakes"), ("Warren", "MI", "Great Lakes"), ("Grand Rapids", "MI", "Great Lakes"),
          ("Toledo", "OH", "Great Lakes"), ("Columbus", "OH", "Great Lakes"), ("Indianapolis", "IN", "Central"),
          ("Chicago", "IL", "Central"), ("Austin", "TX", "South"), ("Dallas", "TX", "South"), ("Houston", "TX", "South"),
          ("Seattle", "WA", "West"), ("Phoenix", "AZ", "West")]
VIN_CHARS = "ABCDEFGHJKLMNPRSTUVWXYZ0123456789"
_TRANSLIT = {**{str(d): d for d in range(10)}, **dict(zip("ABCDEFGH", range(1, 9))), **dict(zip("JKLMN", range(1, 6))),
             "P": 7, "R": 9, **dict(zip("STUVWXYZ", range(2, 10)))}
_WEIGHTS = [8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2]
WMI = {"CHEVROLET": "1GN", "GMC": "1GK", "BUICK": "5GA", "CADILLAC": "1GY"}
YEAR_CODE = {2021: "M", 2022: "N", 2023: "P", 2024: "R", 2025: "S"}

# Planted problems the cutover check must catch (counted in tests)
PLANTED = {"repair_orders_invalid_status": 5, "repair_orders_completed_before_opened": 3}

SCHEMA = """
CREATE TABLE recalls (campaign_number TEXT, make TEXT, model TEXT, model_year INTEGER, component TEXT, summary TEXT,
  remedy TEXT, report_received_date TEXT, park_it INTEGER, updated_at TEXT,
  PRIMARY KEY (campaign_number, make, model, model_year));
CREATE TABLE complaints (odi_number TEXT, make TEXT, model TEXT, model_year INTEGER, components TEXT, crash INTEGER,
  fire INTEGER, injuries INTEGER, filed_date TEXT, summary TEXT, updated_at TEXT,
  PRIMARY KEY (odi_number, make, model, model_year));
CREATE TABLE dealers (dealer_code TEXT PRIMARY KEY, dealer_name TEXT, city TEXT, state TEXT, region TEXT, status TEXT,
  updated_at TEXT);
CREATE TABLE vehicle_owners (vin TEXT PRIMARY KEY, make TEXT, model TEXT, model_year INTEGER, owner_name TEXT,
  email TEXT, phone TEXT, preferred_dealer TEXT, updated_at TEXT, is_deleted INTEGER DEFAULT 0);
CREATE TABLE repair_orders (repair_order_id TEXT PRIMARY KEY, vin TEXT, dealer_code TEXT, campaign_number TEXT,
  status TEXT, opened_at TEXT, completed_at TEXT, updated_at TEXT, is_deleted INTEGER DEFAULT 0);
CREATE INDEX ix_ro_updated ON repair_orders(updated_at);
CREATE INDEX ix_vo_updated ON vehicle_owners(updated_at);
"""


def vin_check_digit(vin: str) -> str:
    r = sum(_TRANSLIT[c] * w for c, w in zip(vin, _WEIGHTS)) % 11
    return "X" if r == 10 else str(r)


def make_vin(rng: random.Random, make: str, year: int) -> str:
    body = WMI[make] + "".join(rng.choice(VIN_CHARS) for _ in range(5))
    tail = YEAR_CODE[year] + rng.choice("0123456789ABCDEFGH") + "".join(rng.choice("0123456789") for _ in range(6))
    return body + vin_check_digit(body + "0" + tail) + tail


def ts(d: date, rng: random.Random) -> str:
    return datetime(d.year, d.month, d.day, rng.randint(0, 23), rng.randint(0, 59), rng.randint(0, 59)).strftime(
        "%Y-%m-%d %H:%M:%S")


def phone(rng: random.Random) -> str:
    return f"({rng.choice(['313', '586', '248', '317', '614', '312'])}) 555-01{rng.randint(0, 99):02d}"


def _read(name: str) -> List[Dict[str, str]]:
    with open(RAW / name, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _flag(v: str) -> int:
    return 1 if str(v).lower() == "true" else 0


def build(path: Path, seed: int = 20261104) -> Dict[str, int]:
    rng = random.Random(seed)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)

    recalls = _read("nhtsa_recalls.csv")
    rows = [(r["campaign_number"], r["make"], r["model"], int(r["model_year"]), r["component"], r["summary"],
             r["remedy"], r["report_received_date"], _flag(r["park_it"]), r["report_received_date"] + " 00:00:00")
            for r in recalls if r["report_received_date"]]
    con.executemany("INSERT OR IGNORE INTO recalls VALUES (?,?,?,?,?,?,?,?,?,?)", rows)

    complaints = _read("nhtsa_complaints.csv")
    rows = [(c["odi_number"], c["make"], c["model"], int(c["model_year"]), c["components"], _flag(c["crash"]),
             _flag(c["fire"]), int(c["injuries"] or 0), c["filed_date"], c["summary"], c["filed_date"] + " 00:00:00")
            for c in complaints if c["filed_date"]]
    con.executemany("INSERT OR IGNORE INTO complaints VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)

    dealers = []
    for i in range(40):
        city, state, region = CITIES[i % len(CITIES)]
        dealers.append((f"D{1000 + i * 37}", f"{rng.choice(LAST)} {rng.choice(['Chevrolet', 'Buick GMC', 'Cadillac', 'Auto Group'])}",
                        city, state, region, "active", ts(date(2024, 1, 1) + timedelta(days=rng.randint(0, 600)), rng)))
    con.executemany("INSERT INTO dealers VALUES (?,?,?,?,?,?,?)", dealers)
    dealer_codes = [d[0] for d in dealers]

    # Vehicles come from the real recall population so recall exposure joins are meaningful.
    vehicles = sorted({(r["make"], r["model"], int(r["model_year"])) for r in recalls
                       if r["make"] in WMI and int(r["model_year"]) in YEAR_CODE})
    owners = []
    for _ in range(3000):
        make, model, year = rng.choice(vehicles)
        first, last = rng.choice(FIRST), rng.choice(LAST)
        owners.append((make_vin(rng, make, year), make, model, year, f"{first} {last}",
                       f"{first.lower()}.{last.lower()}{rng.randint(1, 999)}@example.com", phone(rng),
                       rng.choice(dealer_codes), ts(date(2024, 6, 1) + timedelta(days=rng.randint(0, 500)), rng), 0))
    con.executemany("INSERT OR IGNORE INTO vehicle_owners VALUES (?,?,?,?,?,?,?,?,?,?)", owners)

    campaigns: Dict[Tuple[str, str, int], List[str]] = {}
    for r in recalls:
        campaigns.setdefault((r["make"], r["model"], int(r["model_year"])), []).append(r["campaign_number"])
    orders, n = [], 0
    for o in owners:
        for camp in campaigns.get((o[1], o[2], o[3]), []):
            if rng.random() < 0.55:
                n += 1
                opened = date(2025, 1, 1) + timedelta(days=rng.randint(0, 640))
                status = rng.choices(["completed", "open", "scheduled", "cancelled"], [0.62, 0.18, 0.14, 0.06])[0]
                done = (opened + timedelta(days=rng.randint(0, 9))).isoformat() if status == "completed" else None
                last_touch = date.fromisoformat(done) if done else opened
                orders.append((f"RO{n:07d}", o[0], o[7], camp, status, opened.isoformat(), done,
                               ts(min(last_touch, BASE_DAY - timedelta(days=1)), rng), 0))
    bad_status = rng.sample([i for i, r in enumerate(orders) if r[4] == "open"], PLANTED["repair_orders_invalid_status"])
    for i in bad_status:
        orders[i] = orders[i][:4] + ("Done",) + orders[i][5:]
    completed = [i for i, r in enumerate(orders) if r[4] == "completed" and i not in bad_status]
    for i in rng.sample(completed, PLANTED["repair_orders_completed_before_opened"]):
        r = orders[i]
        orders[i] = r[:6] + ((date.fromisoformat(r[5]) - timedelta(days=4)).isoformat(),) + r[7:]
    con.executemany("INSERT INTO repair_orders VALUES (?,?,?,?,?,?,?,?,?)", orders)
    con.commit()
    counts = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("recalls", "complaints", "dealers", "vehicle_owners", "repair_orders")}
    con.close()
    return counts
