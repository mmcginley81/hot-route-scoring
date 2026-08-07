import argparse
import sys

from .bubble_client import BubbleClient
from .config import Config
from .mfl_client import MFLClient

# Hot Route only rosters these positions (confirmed against live Bubble
# data — no K/DST records exist), so the MFL dictionary is filtered the
# same way to avoid noise/ambiguity from placeholder and other-position
# entries.
SKILL_POSITIONS = {"QB", "RB", "WR", "TE"}

SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}


def mfl_name_to_first_last(mfl_name: str) -> str:
    """MFL's dictionary uses 'Last, First' (suffix stays with the last
    name, e.g. 'Walker III, Kenneth') — convert to Bubble's 'First Last'."""
    last, _, first = mfl_name.partition(", ")
    return f"{first} {last}".strip()


def normalize(name: str) -> str:
    return " ".join(name.replace(".", "").split()).lower()


def strip_suffix(name: str) -> str:
    parts = name.split()
    if parts and parts[-1].lower().strip(".") in SUFFIXES:
        return " ".join(parts[:-1])
    return name


def last_name(name: str) -> str:
    parts = strip_suffix(name).split()
    return normalize(parts[-1]) if parts else ""


def build_indexes(mfl_players: dict) -> tuple[dict, dict, dict]:
    """Three lookup indexes, tried in order: exact-normalized-name (periods
    stripped so 'DJ Moore' matches 'D.J. Moore'), a suffix-stripped
    fallback for Jr./Sr./II/III/IV disagreements, and a last-name-only
    fallback for nickname cases (e.g. Bubble's 'Chig' vs MFL's formal
    'Chigoziem') — only usable when the last name is unique in the pool."""
    exact, stripped, by_last = {}, {}, {}
    for mfl_id, p in mfl_players.items():
        if p.get("position") not in SKILL_POSITIONS:
            continue
        full_name = mfl_name_to_first_last(p["name"])
        exact.setdefault(normalize(full_name), []).append(mfl_id)
        stripped.setdefault(normalize(strip_suffix(full_name)), []).append(mfl_id)
        by_last.setdefault(last_name(full_name), []).append(mfl_id)
    return exact, stripped, by_last


def match(name: str, exact: dict, stripped: dict, by_last: dict) -> tuple[str | None, str]:
    """Returns (mfl_id or None, reason): 'exact', 'suffix-fallback',
    'last-name-fallback', 'ambiguous', or 'unmatched'."""
    for candidates, reason in (
        (exact.get(normalize(name)), "exact"),
        (stripped.get(normalize(strip_suffix(name))), "suffix-fallback"),
        (by_last.get(last_name(name)), "last-name-fallback"),
    ):
        if not candidates:
            continue
        if len(candidates) > 1:
            return None, "ambiguous"
        return candidates[0], reason
    return None, "unmatched"


def run(live: bool) -> None:
    config = Config.from_env()
    mfl = MFLClient(config)
    bubble = BubbleClient(config)

    mfl_players = mfl.get_player_dictionary()
    exact, stripped, by_last = build_indexes(mfl_players)
    print(f"MFL dictionary: {len(mfl_players)} total entries, "
          f"{sum(len(v) for v in exact.values())} skill-position entries indexed")

    nfl_players = bubble.list_all("NFLPlayer")
    print(f"Bubble NFLPlayer: {len(nfl_players)} records")

    fill, fix, correct, unmatched, ambiguous = [], [], [], [], []
    for p in nfl_players:
        name = p.get("name")
        current_id = p.get("MFL_PLAYER_ID")
        mfl_id, reason = match(name, exact, stripped, by_last)

        if mfl_id is None:
            (ambiguous if reason == "ambiguous" else unmatched).append(p)
            continue
        if not current_id:
            fill.append((p, mfl_id, reason))
        elif current_id != mfl_id:
            fix.append((p, current_id, mfl_id, reason))
        else:
            correct.append(p)

    print(f"\n{len(correct)} already correct")
    print(f"{len(fill)} missing MFL_PLAYER_ID, match found -> fill")
    for p, mfl_id, reason in fill[:20]:
        print(f"  {p['name']:25s} -> {mfl_id:>8s}  ({reason})")
    if len(fill) > 20:
        print(f"  ... and {len(fill) - 20} more")

    print(f"\n{len(fix)} WRONG MFL_PLAYER_ID, needs correction -> fix")
    for p, old_id, new_id, reason in fix:
        print(f"  {p['name']:25s} {old_id:>8s} -> {new_id:>8s}  ({reason})")

    print(f"\n{len(unmatched)} unmatched (no name match in MFL dictionary, left alone)")
    for p in unmatched:
        print(f"  {p['name']}")

    print(f"\n{len(ambiguous)} ambiguous (multiple MFL candidates for the same name, left alone)")
    for p in ambiguous:
        print(f"  {p['name']}")

    if not live:
        print("\ndry run only — pass --live to PATCH the fill + fix lists into Bubble")
        return

    for p, mfl_id, _ in fill:
        bubble.patch("NFLPlayer", p["_id"], {"MFL_PLAYER_ID": mfl_id})
    for p, _, new_id, _ in fix:
        bubble.patch("NFLPlayer", p["_id"], {"MFL_PLAYER_ID": new_id})
    print(f"\npatched {len(fill) + len(fix)} NFLPlayer records ({len(fill)} filled, {len(fix)} corrected)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Re-derive NFLPlayer.MFL_PLAYER_ID from MFL's player dictionary by name match."
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="actually PATCH fills and corrections into Bubble (default: dry run, report only)",
    )
    args = parser.parse_args()
    run(args.live)


if __name__ == "__main__":
    sys.exit(main())
