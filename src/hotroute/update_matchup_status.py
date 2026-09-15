import argparse
import sys
from datetime import datetime

from .bubble_client import BubbleClient
from .config import Config
from .live_poll import PACIFIC, week_turnover


def compute_status(week: int, now: datetime) -> str:
    if now < week_turnover(week):
        return "upcoming"
    if now >= week_turnover(week + 1):
        return "completed"
    return "live"


def run(live: bool, now: datetime | None = None) -> None:
    now = now or datetime.now(PACIFIC)
    config = Config.from_env()
    bubble = BubbleClient(config)

    matchups = bubble.list_all("Matchup")
    print(f"loaded {len(matchups)} Matchup records")

    changed = []  # (matchup_id, week, old_status, new_status)
    skipped = 0
    for m in matchups:
        week = m.get("week")
        if week is None:
            skipped += 1
            continue
        new_status = compute_status(week, now)
        old_status = m.get("matchup_status")
        if old_status != new_status:
            changed.append((m["_id"], week, old_status, new_status))

    if skipped:
        print(f"{skipped} Matchup records have no week set — skipped")

    print(f"{len(changed)} matchups need a status change")
    for _, week, old_status, new_status in sorted(changed, key=lambda c: c[1]):
        print(f"  week {week:>2d}: {old_status or '(none)'} -> {new_status}")

    if not live:
        print("\ndry run only — pass --live to PATCH these into Bubble")
        return

    if not changed:
        print("nothing to write, done")
        return

    for matchup_id, _, _, new_status in changed:
        bubble.patch("Matchup", matchup_id, {"matchup_status": new_status})
    print(f"\npatched {len(changed)} Matchup records")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Set each Matchup's matchup_status (upcoming/live/completed) from today's date."
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="actually PATCH changes into Bubble (default: dry run)",
    )
    args = parser.parse_args()
    run(args.live)


if __name__ == "__main__":
    sys.exit(main())
