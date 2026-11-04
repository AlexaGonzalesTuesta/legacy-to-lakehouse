"""python -m lakehouse --days 7 [--work work]"""
import argparse
import sys
from pathlib import Path

from .demo import run_demo


def main() -> int:
    p = argparse.ArgumentParser(prog="python -m lakehouse",
                                description="Migrate the legacy recall database to a lakehouse and check cutover readiness.")
    p.add_argument("--days", type=int, default=7, help="nightly incremental loads after the initial full load")
    p.add_argument("--work", default="work", help="local folder for the legacy database, landing zone and lakehouse")
    args = p.parse_args()
    run_demo(Path(args.work).resolve(), days=args.days)
    return 0


sys.exit(main())
