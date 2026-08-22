import argparse
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .bubble_client import BubbleClient
from .config import Config
from .live_poll import SEASON_WEEK_1_START

# Fans a value out to every TeamPlayer.thisWeekScore by copying from each
# one's linked NFLPlayer.this_week_score — same workflow Track A uses to
# propagate real scores, reused here so backend and UI don't drift apart
# right after a reset.
SYNC_WORKFLOW = "sync_all_teamplayer_scores_beta"

PACIFIC = ZoneInfo("America/Los_Angeles")
# Monday Night Football typically wraps up around 9pm Pacific — the earliest
# it's safe to close out a week without risking baking in a false 0 for a
# player whose game just hasn't happened yet.
MNF_CUTOFF_HOUR = 21


def week_close_cutoff(week: int) -> datetime:
    """Monday night of `week`'s slate at 9pm Pacific. Reuses live_poll.py's
    SEASON_WEEK_1_START anchor (the Tuesday before week 1) as the single
    source of truth for the season calendar rather than duplicating it."""
    monday = SEASON_WEEK_1_START + timedelta(days=7 * week - 1)
    return datetime(monday.year, monday.month, monday.day, MNF_CUTOFF_HOUR, tzinfo=PACIFIC)


def classify_players(nfl_players: list[dict], week: int) -> dict[str, list[dict]]:
    """Bucket players by how their list_weekly_scores length compares to
    the week being closed out: 'ok' needs this week's entry appended,
    'already_done' is a double-run (skip, already has it), 'behind' is
    missing more than one week (flag, don't guess a value)."""
    buckets: dict[str, list[dict]] = {"ok": [], "already_done": [], "behind": []}
    for p in nfl_players:
        length = len(p.get("list_weekly_scores") or [])
        if length == week - 1:
            buckets["ok"].append(p)
        elif length >= week:
            buckets["already_done"].append(p)
        else:
            buckets["behind"].append(p)
    return buckets


def run(week: int, live: bool, limit: int | None, now: datetime | None = None) -> None:
    # `now` is only overridable by direct Python calls (not the CLI) — for
    # testing against past/future weeks without waiting on the real clock.
    now = now or datetime.now(PACIFIC)
    cutoff = week_close_cutoff(week)
    if now < cutoff:
        message = (
            f"week {week} isn't over yet — earliest safe close-out is "
            f"{cutoff.strftime('%a %b %d, %I:%M %p %Z')} (Monday Night Football), "
            f"it's currently {now.strftime('%a %b %d, %I:%M %p %Z')}"
        )
        if live:
            print(f"{message}.")
            print("aborting --live to avoid baking a false 0 into list_weekly_scores for anyone whose game hasn't happened yet.")
            return
        print(f"note: {message} (dry run only, not blocking).\n")

    config = Config.from_env()
    bubble = BubbleClient(config)

    nfl_players = bubble.list_all("NFLPlayer")
    buckets = classify_players(nfl_players, week)
    print(
        f"{len(nfl_players)} NFLPlayer records for week {week} close-out: "
        f"{len(buckets['ok'])} ready to append, "
        f"{len(buckets['already_done'])} already appended (possible double-run), "
        f"{len(buckets['behind'])} behind (missing an earlier week)"
    )

    if buckets["behind"]:
        print(f"\n{len(buckets['behind'])} players are behind by more than one week — list_weekly_scores")
        print(f"won't be touched for them (would misalign the index). Fix directly (e.g. from MFL), then re-run:")
        for p in buckets["behind"]:
            print(f"  {p.get('name'):25s} list_weekly_scores has {len(p.get('list_weekly_scores') or [])} entries, expected {week - 1}")

    to_append = buckets["ok"]

    if not live:
        print(f"\ndry run only — would append this_week_score into list_weekly_scores for {len(to_append)} players")
        print("would then reset this_week_score to 0 for all players and cascade via", SYNC_WORKFLOW)
        print("pass --live to actually do it")
        return

    if to_append:
        print(f"\nappending this_week_score into list_weekly_scores for {len(to_append)} players...")
        for p in to_append:
            new_list = (p.get("list_weekly_scores") or []) + [p.get("this_week_score") or 0]
            bubble.patch("NFLPlayer", p["_id"], {"list_weekly_scores": new_list})
        print(f"appended for {len(to_append)} players")
    else:
        print("\nno players need an append this week — already up to date")

    # PATCH every player, not just currently-nonzero ones: a player whose
    # this_week_score has never been set (still Bubble-empty/None, not a
    # real 0 — e.g. never active) would otherwise stay None forever, and
    # the append step above needs a real number to add to list_weekly_scores.
    nfl_players = bubble.list_all("NFLPlayer")
    print(f"\nresetting this_week_score to 0 for all {len(nfl_players)} NFLPlayer records")

    targets = nfl_players[:limit] if limit else nfl_players
    if limit:
        print(f"--limit {limit}: only resetting {len(targets)} of {len(nfl_players)}")

    for p in targets:
        bubble.patch("NFLPlayer", p["_id"], {"this_week_score": 0})
    print(f"patched {len(targets)} NFLPlayer records to 0")

    print(f"triggering {SYNC_WORKFLOW} to cascade the zero to TeamPlayer...")
    result = bubble.trigger_workflow(SYNC_WORKFLOW)
    print(f"  result: {result}")
    print("(runs async in Bubble — allow a few seconds before verifying)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Close out an NFL week: append this_week_score into list_weekly_scores for "
            "every NFLPlayer directly via the Data API, then reset this_week_score to 0 "
            "and cascade to TeamPlayer. Manual/on-demand only — no cron runs this."
        )
    )
    parser.add_argument("--week", type=int, required=True, help="the NFL week being closed out")
    parser.add_argument(
        "--live",
        action="store_true",
        help="actually append + PATCH the reset + trigger the sync workflow (default: dry run, no Bubble writes)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="only reset the first N players — for testing, not real weekly use. "
             "Does not affect the append step, which always covers every eligible player.",
    )
    args = parser.parse_args()
    run(args.week, args.live, args.limit)


if __name__ == "__main__":
    sys.exit(main())
