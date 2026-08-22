import argparse
import sys
from datetime import date

from .bubble_client import BubbleClient
from .config import Config
from .mfl_client import MFLClient, normalize_mfl_id

# MFL scores come back as strings parsed to float; ignore sub-tolerance
# "changes" that are really just float noise, not a real score update.
SCORE_TOLERANCE = 0.05

# Cap on how many player ids go into a single Bubble "in" constraint per
# request — untested at higher counts, chunk defensively.
CHUNK_SIZE = 100

# The Tuesday immediately before 2026 week 1's slate (confirmed from the
# real MFL/NFL schedule: week 1 runs Wed Sep 9 - Mon Sep 14, week 2 starts
# Thu Sep 17). NFL weeks turn over on Tuesday, not on the week's own first
# game, so anchoring here — not on Sep 9 — keeps the boundary aligned with
# that even though week 1 itself has an odd one-off Wednesday opener.
SEASON_WEEK_1_START = date(2026, 9, 8)


def current_nfl_week(today: date | None = None) -> int | None:
    """No dependency on Bubble's admin.current_week (doesn't exist yet, and
    is Bubble's own concern) — the cron needs to self-determine the week
    from the calendar, so this is Track B's own copy of that logic.

    Returns None before the season starts. Floor division on a negative
    day-count silently rounds up to a false "week 1" otherwise — confirmed
    live: the cron ran unattended every ~30 min for 11 days during the
    2026 preseason and kept re-patching real 2025 week-1 test data into
    this_week_score, since it always looked "different" from whatever a
    manual test had just reset it to. An explicit --week still overrides
    this (see main()) — this only gates the cron's own auto-computed default."""
    today = today or date.today()
    days_since_start = (today - SEASON_WEEK_1_START).days
    if days_since_start < 0:
        return None
    return days_since_start // 7 + 1


def _chunks(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def run(week: int, live: bool) -> None:
    config = Config.from_env()
    mfl = MFLClient(config)

    live_scores = mfl.get_live_scores(week)
    print(f"MFL liveScoring returned {len(live_scores)} player entries for week {week}")

    if not live:
        for mfl_id, info in list(live_scores.items())[:10]:
            print(f"  mfl_id={mfl_id:>8s} score={info['score']}")
        print("\ndry run only — pass --live to diff against Bubble and PATCH changes")
        return

    bubble = BubbleClient(config)

    nfl_players = bubble.list_all("NFLPlayer")
    # normalize_mfl_id() here guards against Bubble ever holding a stray
    # leading zero or similar formatting drift, not just a type mismatch.
    by_mfl_id = {normalize_mfl_id(p["MFL_PLAYER_ID"]): p for p in nfl_players if p.get("MFL_PLAYER_ID")}
    print(f"loaded {len(nfl_players)} NFLPlayer records ({len(by_mfl_id)} with MFL_PLAYER_ID set)")

    changed = []  # (nflplayer_bubble_id, mfl_id, name, new_score)
    for mfl_id, info in live_scores.items():
        player = by_mfl_id.get(normalize_mfl_id(mfl_id))
        if not player:
            continue
        new_score = info["score"]
        current_score = player.get("this_week_score") or 0.0
        if abs(new_score - current_score) < SCORE_TOLERANCE:
            continue
        changed.append((player["_id"], mfl_id, player.get("name"), new_score))

    print(f"{len(changed)} players changed since last poll")
    for _, mfl_id, name, new_score in changed:
        print(f"  {name:25s} mfl_id={mfl_id:>8s} -> {new_score}")

    if not changed:
        print("nothing to write, done")
        return

    for nflplayer_id, _, _, new_score in changed:
        bubble.patch("NFLPlayer", nflplayer_id, {"this_week_score": new_score})
    print(f"patched {len(changed)} NFLPlayer records")

    score_by_nflplayer_id = {nflplayer_id: new_score for nflplayer_id, _, _, new_score in changed}
    changed_ids = list(score_by_nflplayer_id.keys())

    team_players = []
    for chunk in _chunks(changed_ids, CHUNK_SIZE):
        team_players.extend(
            bubble.list_all(
                "TeamPlayer",
                constraints=[{"key": "player", "constraint_type": "in", "value": chunk}],
            )
        )

    for tp in team_players:
        bubble.patch("TeamPlayer", tp["_id"], {"thisWeekScore": score_by_nflplayer_id[tp["player"]]})
    print(f"patched {len(team_players)} TeamPlayer records")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Poll MFL liveScoring and push only-changed scores into Bubble."
    )
    parser.add_argument(
        "--week",
        type=int,
        default=None,
        help="defaults to the current NFL week, computed from today's date",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="actually diff against Bubble and PATCH changes (default: dry run, MFL only)",
    )
    args = parser.parse_args()
    if args.week is not None:
        week = args.week
    else:
        week = current_nfl_week()
        if week is None:
            print(f"season hasn't started yet (starts {SEASON_WEEK_1_START.isoformat()}) — nothing to poll, exiting")
            return
    run(week, args.live)


if __name__ == "__main__":
    sys.exit(main())
