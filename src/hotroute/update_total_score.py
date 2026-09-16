import argparse
import sys

from .bubble_client import BubbleClient
from .config import Config

# Bubble backend workflow: adds this Matchup's team_1_score/team_2_score onto
# each team's FantasyTeam.totalScore. Single "Matchup" param, gated on
# Matchup.totalScoreApplied == no — see .github/workflows/update_total_score.yml.
WORKFLOW = "update_total_score_for_matchup_after_matchup_ends"

# Same statuses update_streaks.py treats as "decided" — Week 1 games have
# final scores but matchup_status stays "live" until Wednesday-noon-Pacific
# turnover (see live_poll.week_turnover()).
WINNER_STATUSES = {"live", "completed"}


def run(live: bool) -> None:
    config = Config.from_env()
    bubble = BubbleClient(config)

    matchups = bubble.list_all("Matchup")
    decided = [m for m in matchups if m.get("matchup_status") in WINNER_STATUSES]
    # totalScoreApplied is the double-count guard — the Bubble workflow
    # itself re-checks this too, but filtering here avoids paying for a
    # workflow call that would just no-op.
    pending = [m for m in decided if not m.get("totalScoreApplied")]
    print(f"{len(matchups)} Matchup records total, {len(decided)} decided, "
          f"{len(pending)} still need {WORKFLOW} triggered")
    for m in sorted(pending, key=lambda m: m.get("week") or 0):
        t1, t2 = m.get("team_1_score"), m.get("team_2_score")
        print(f"  week {m.get('week'):>2}: matchup {m['_id']}  team_1_score={t1}  team_2_score={t2}")

    if not live:
        print(f"\ndry run only — would trigger {WORKFLOW} for {len(pending)} matchup(s)")
        print("pass --live to actually do it")
        return

    if not pending:
        print("\nnothing to do")
        return

    for m in pending:
        print(f"triggering {WORKFLOW} for matchup {m['_id']} (week {m.get('week')})...")
        result = bubble.trigger_workflow(WORKFLOW, {"Matchup": m["_id"]})
        print(f"  result: {result}")

    print(f"\ndone — triggered {WORKFLOW} for {len(pending)} matchup(s)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            f"Trigger Bubble's {WORKFLOW} backend workflow for every decided Matchup that "
            "hasn't had its score applied to totalScore yet."
        )
    )
    parser.add_argument("--live", action="store_true", help="actually trigger the workflow (default: dry run)")
    args = parser.parse_args()
    run(args.live)


if __name__ == "__main__":
    sys.exit(main())
