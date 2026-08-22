import argparse
import sys

from .bubble_client import BubbleClient
from .config import Config


def run(live: bool) -> None:
    config = Config.from_env()
    bubble = BubbleClient(config)

    nfl_players = bubble.list_all("NFLPlayer")
    nonempty = [p for p in nfl_players if p.get("list_weekly_scores")]
    print(f"{len(nfl_players)} NFLPlayer records, {len(nonempty)} with a non-empty list_weekly_scores")

    if not live:
        print(f"\ndry run only — would PATCH {len(nonempty)} NFLPlayer records' list_weekly_scores to []")
        print("pass --live to actually do it")
        return

    for p in nonempty:
        bubble.patch("NFLPlayer", p["_id"], {"list_weekly_scores": []})
    print(f"\ncleared list_weekly_scores on {len(nonempty)} NFLPlayer records")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "One-time wipe of NFLPlayer.list_weekly_scores back to empty — for clearing stale "
            "test data ahead of a fresh season. Manual/on-demand only."
        )
    )
    parser.add_argument("--live", action="store_true", help="actually PATCH the clear (default: dry run)")
    args = parser.parse_args()
    run(args.live)


if __name__ == "__main__":
    sys.exit(main())
