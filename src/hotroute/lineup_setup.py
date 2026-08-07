import argparse
import csv
import sys
import time

from .config import Config
from .mfl_client import MFLClient

TOTAL_WEEKS = 18
# MFL's own guidance: space import requests out to avoid throttling.
REQUEST_DELAY_SECONDS = 1
DEFAULT_ROSTER_CSV = "2025_franchise_rosters.csv"


def load_franchise_rosters(csv_path: str) -> dict[str, list[str]]:
    """Franchise ID -> list of MFL player ids, from a roster export CSV
    (columns: Franchise ID, MFL_ID, ...). Rows with a blank MFL_ID (a
    player MFL has no id for) are skipped. MFL's own TYPE=rosters export
    is unreliable for this league — see project memory — so roster data
    comes from this CSV instead."""
    rosters: dict[str, list[str]] = {}
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            franchise_id = row["Franchise ID"].strip()
            mfl_id = row["MFL_ID"].strip()
            if not mfl_id:
                continue
            rosters.setdefault(franchise_id, []).append(mfl_id)
    return rosters


def run(live: bool, roster_csv: str) -> None:
    config = Config.from_env()
    mfl = MFLClient(config)

    rosters = load_franchise_rosters(roster_csv)
    print(f"loaded rosters for {len(rosters)} franchises from {roster_csv}")

    total_calls = len(rosters) * TOTAL_WEEKS
    print(f"will submit {total_calls} lineups (each franchise's full roster, weeks 1-{TOTAL_WEEKS})")
    for franchise_id, roster in rosters.items():
        print(f"  {franchise_id}: {len(roster)} players")

    if not live:
        print("\ndry run only — pass --live to actually submit these lineups to MFL")
        return

    mfl.login()
    print("logged in")

    submitted, failed = 0, 0
    for franchise_id, roster in rosters.items():
        for week in range(1, TOTAL_WEEKS + 1):
            try:
                mfl.import_lineup(franchise_id, week, roster)
                submitted += 1
            except Exception as e:
                failed += 1
                print(f"  failed for franchise {franchise_id} week {week}: {e}")
            time.sleep(REQUEST_DELAY_SECONDS)

    print(f"\nsubmitted {submitted} / {total_calls} lineups ({failed} failed)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Submit each franchise's full roster as the starting lineup for weeks 1-18. "
        "Run once, a day or two before the season starts, before any player's lineup deadline passes."
    )
    parser.add_argument("--live", action="store_true", help="actually submit to MFL (default: dry run)")
    parser.add_argument("--roster-csv", default=DEFAULT_ROSTER_CSV, help="Franchise ID -> MFL_ID roster CSV")
    args = parser.parse_args()
    run(args.live, args.roster_csv)


if __name__ == "__main__":
    sys.exit(main())
