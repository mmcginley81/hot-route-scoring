import argparse
import sys

from .bubble_client import BubbleClient
from .config import Config

# Bubble backend workflow that recomputes bestball starter scores for one
# Matchup (required "matchup" param). Its own steps already gate on
# "Only when matchup's matchup_status is live", so this script only calls
# it for matchups that are actually live — no point paying Bubble workload
# for matchups nothing is scoring against.
#
# This script is now a manual/occasional full-sweep tool, not the primary
# driver — live_poll.py triggers this same workflow itself on every poll,
# scoped to only matchups with an actual score change, which is far cheaper
# in Workflow Units than this script's "every live matchup, unconditionally"
# approach. Run this by hand (gh workflow run calculate_starter_score.yml)
# if you suspect a matchup's starter score is stale and want to force a
# full recompute across every live matchup.
WORKFLOW = "calculate_starter_score_for_matchup"


def run(live: bool) -> None:
    config = Config.from_env()
    bubble = BubbleClient(config)

    live_matchups = bubble.list_all(
        "Matchup", constraints=[{"key": "matchup_status", "constraint_type": "equals", "value": "live"}]
    )
    print(f"{len(live_matchups)} live Matchup record(s) found")

    if not live:
        for m in live_matchups:
            print(f"  would trigger {WORKFLOW} for matchup {m['_id']} (week {m.get('week')})")
        print(f"\ndry run only — pass --live to actually trigger {WORKFLOW} for each")
        return

    if not live_matchups:
        print("nothing to do")
        return

    for m in live_matchups:
        print(f"triggering {WORKFLOW} for matchup {m['_id']} (week {m.get('week')})...")
        result = bubble.trigger_workflow(WORKFLOW, {"matchup": m["_id"]})
        print(f"  result: {result}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Trigger Bubble's calculate_starter_score backend workflow.")
    parser.add_argument("--live", action="store_true", help="actually trigger the workflow (default: dry run)")
    args = parser.parse_args()
    run(args.live)


if __name__ == "__main__":
    sys.exit(main())
