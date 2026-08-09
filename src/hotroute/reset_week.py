import argparse
import sys

from .bubble_client import BubbleClient
from .config import Config

# Fans a value out to every TeamPlayer.thisWeekScore by copying from each
# one's linked NFLPlayer.this_week_score — same workflow Track A uses to
# propagate real scores, reused here so backend and UI don't drift apart
# right after a reset.
SYNC_WORKFLOW = "sync_all_teamplayer_scores_beta"


def run(live: bool, limit: int | None) -> None:
    config = Config.from_env()
    bubble = BubbleClient(config)

    nfl_players = bubble.list_all("NFLPlayer")
    nonzero = [p for p in nfl_players if (p.get("this_week_score") or 0) != 0]
    print(f"{len(nfl_players)} NFLPlayer records, {len(nonzero)} currently non-zero")

    targets = nonzero[:limit] if limit else nonzero
    if limit:
        print(f"--limit {limit}: only resetting {len(targets)} of {len(nonzero)} non-zero records")

    for p in targets[:10]:
        print(f"  {p.get('name'):25s} {p.get('this_week_score')} -> 0")
    if len(targets) > 10:
        print(f"  ... and {len(targets) - 10} more")

    if not live:
        print(f"\ndry run only — would PATCH {len(targets)} NFLPlayer records to 0, "
              f"then trigger {SYNC_WORKFLOW} to cascade")
        print("pass --live to actually do it")
        return

    for p in targets:
        bubble.patch("NFLPlayer", p["_id"], {"this_week_score": 0})
    print(f"\npatched {len(targets)} NFLPlayer records to 0")

    print(f"triggering {SYNC_WORKFLOW} to cascade the zero to TeamPlayer...")
    result = bubble.trigger_workflow(SYNC_WORKFLOW)
    print(f"  result: {result}")
    print("(runs async in Bubble — allow a few seconds before verifying)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Reset this_week_score to 0 for all players and cascade to TeamPlayer, "
            "ahead of a new NFL week. Manual/on-demand only — no cron runs this."
        )
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="actually PATCH the reset + trigger the sync workflow (default: dry run, no Bubble writes)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="only reset the first N non-zero players — for testing, not real weekly use",
    )
    args = parser.parse_args()
    run(args.live, args.limit)


if __name__ == "__main__":
    sys.exit(main())
