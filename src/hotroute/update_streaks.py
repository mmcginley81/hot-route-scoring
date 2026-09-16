import argparse
import sys

from .bubble_client import BubbleClient
from .config import Config

# Bubble field confirmed live via a real PATCH + read-back (2026-09-15):
# display name is "Current Streak" but its API key is "currentStreak"
# (Bubble's API name differs from the display name here). Null for every
# FantasyTeam before this script runs.
STREAK_FIELD = "currentStreak"

# Two backend workflows, each taking "Matchup" and "week" params (confirmed
# live via a 400 MISSING_DATA probe, 2026-09-15). Both must be triggered for
# every matchup being scored — each presumably only acts on the side
# (team_1 vs team_2) that actually won, so calling both per matchup covers
# whichever team took it.
WORKFLOW_1 = "updateStreaksForMatchup"
WORKFLOW_2 = "updateStreaksForMatchup_2"

# Matchups with a decided winner right now. Week 1 games have final scores
# but matchup_status is still "live" until this week's Wednesday-noon-Pacific
# turnover — see live_poll.week_turnover().
WINNER_STATUSES = {"live", "completed"}


def run(live: bool) -> None:
    config = Config.from_env()
    bubble = BubbleClient(config)

    teams = bubble.list_all("FantasyTeam")
    print(f"{len(teams)} FantasyTeam record(s) to reset {STREAK_FIELD!r} -> 0")

    matchups = bubble.list_all("Matchup")
    decided = [m for m in matchups if m.get("matchup_status") in WINNER_STATUSES]
    print(f"{len(matchups)} Matchup records total, {len(decided)} with a decided winner "
          f"(status in {sorted(WINNER_STATUSES)})")
    for m in sorted(decided, key=lambda m: m.get("week") or 0):
        t1, t2 = m.get("team_1_score"), m.get("team_2_score")
        print(f"  week {m.get('week'):>2}: matchup {m['_id']}  team_1_score={t1}  team_2_score={t2}")

    if not live:
        print(f"\ndry run only — would PATCH {STREAK_FIELD!r}=0 on {len(teams)} FantasyTeam records, "
              f"then trigger {WORKFLOW_1} and {WORKFLOW_2} for each of the {len(decided)} decided matchups")
        print("pass --live to actually do it")
        return

    for t in teams:
        bubble.patch("FantasyTeam", t["_id"], {STREAK_FIELD: 0})
    print(f"\ncleared {STREAK_FIELD!r} on {len(teams)} FantasyTeam records")

    for m in decided:
        params = {"Matchup": m["_id"], "week": m.get("week")}
        print(f"triggering {WORKFLOW_1} + {WORKFLOW_2} for matchup {m['_id']} (week {m.get('week')})...")
        r1 = bubble.trigger_workflow(WORKFLOW_1, params)
        print(f"  {WORKFLOW_1}: {r1}")
        r2 = bubble.trigger_workflow(WORKFLOW_2, params)
        print(f"  {WORKFLOW_2}: {r2}")

    print(f"\ndone — reset {len(teams)} teams, updated streaks for {len(decided)} matchups")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            f"Reset every FantasyTeam.{STREAK_FIELD!r} to 0, then trigger {WORKFLOW_1} and "
            f"{WORKFLOW_2} for every Matchup with a decided winner so winners get their new streak."
        )
    )
    parser.add_argument("--live", action="store_true", help="actually PATCH + trigger the workflows (default: dry run)")
    args = parser.parse_args()
    run(args.live)


if __name__ == "__main__":
    sys.exit(main())
