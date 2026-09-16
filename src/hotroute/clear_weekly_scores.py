import argparse
import re
import sys

from .bubble_client import BubbleClient
from .config import Config

# Discovered from real records rather than hardcoded (e.g. week_8_score) —
# only weeks that have actually had a field created in Bubble exist as keys
# at all, and Bubble's Data API omits a key entirely for a record where
# that field has never been set.
WEEK_SCORE_FIELD_RE = re.compile(r"^week_\d+_score$")


def is_stale(p: dict, week_fields: set[str]) -> bool:
    if p.get("list_weekly_scores"):
        return True
    if p.get("total_score") not in (None, "", 0):
        return True
    return any(p.get(f) not in (None, "", 0) for f in week_fields)


def run(live: bool) -> None:
    config = Config.from_env()
    bubble = BubbleClient(config)

    nfl_players = bubble.list_all("NFLPlayer")

    week_fields: set[str] = set()
    for p in nfl_players:
        week_fields.update(k for k in p if WEEK_SCORE_FIELD_RE.match(k))

    stale = [p for p in nfl_players if is_stale(p, week_fields)]
    field_list = ", ".join(["list_weekly_scores", "total_score", *sorted(week_fields)])
    print(f"{len(nfl_players)} NFLPlayer records, {len(stale)} with stale data in: {field_list}")

    if not live:
        print(f"\ndry run only — would clear {field_list} on {len(stale)} NFLPlayer records")
        print("pass --live to actually do it")
        return

    for p in stale:
        patch = {"list_weekly_scores": [], "total_score": None}
        patch.update({f: None for f in week_fields})
        bubble.patch("NFLPlayer", p["_id"], patch)
    print(f"\ncleared {field_list} on {len(stale)} NFLPlayer records")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "One-time wipe of NFLPlayer.list_weekly_scores, week_<N>_score fields, and "
            "total_score back to empty — for clearing stale test data ahead of a fresh "
            "season. Manual/on-demand only."
        )
    )
    parser.add_argument("--live", action="store_true", help="actually PATCH the clear (default: dry run)")
    args = parser.parse_args()
    run(args.live)


if __name__ == "__main__":
    sys.exit(main())
