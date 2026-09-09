import argparse
import sys

from .bubble_client import BubbleClient
from .config import Config

# Fans this_week_score out to every TeamPlayer.thisWeekScore linked to an
# NFLPlayer, same workflow reset_week.py uses after its own reset PATCHes —
# reused here so backend and UI don't drift apart after this cleanup either.
SYNC_WORKFLOW = "sync_all_teamplayer_scores_beta"


def run(live: bool) -> None:
    config = Config.from_env()
    bubble = BubbleClient(config)

    nfl_players = bubble.list_all("NFLPlayer")
    stale = [p for p in nfl_players if (p.get("this_week_score") or 0) != 0]
    print(f"{len(nfl_players)} NFLPlayer records, {len(stale)} with a nonzero this_week_score")
    for p in sorted(stale, key=lambda p: p.get("name") or ""):
        print(f"  {p.get('name'):25s} this_week_score={p.get('this_week_score')}")

    if not live:
        print(f"\ndry run only — would PATCH this_week_score to 0 on {len(stale)} NFLPlayer records, then trigger {SYNC_WORKFLOW}")
        print("pass --live to actually do it")
        return

    if not stale:
        print("\nnothing to clear, done")
        return

    for p in stale:
        bubble.patch("NFLPlayer", p["_id"], {"this_week_score": 0})
    print(f"\ncleared this_week_score on {len(stale)} NFLPlayer records")

    print(f"triggering {SYNC_WORKFLOW} to cascade the zero to TeamPlayer...")
    result = bubble.trigger_workflow(SYNC_WORKFLOW)
    print(f"  result: {result}")
    print("(runs async in Bubble — allow a few seconds before verifying)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "One-time wipe of stale nonzero NFLPlayer.this_week_score values left over from "
            "pre-season testing, then cascade the zero to TeamPlayer. Manual/on-demand only — "
            "live_poll.py can't self-correct these because MFL's liveScoring feed omits players "
            "whose games haven't started yet, so a stale score just sits there untouched."
        )
    )
    parser.add_argument("--live", action="store_true", help="actually PATCH the clear + trigger the sync (default: dry run)")
    args = parser.parse_args()
    run(args.live)


if __name__ == "__main__":
    sys.exit(main())
