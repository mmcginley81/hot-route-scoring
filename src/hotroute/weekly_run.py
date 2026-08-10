import argparse
import csv
import sys

from .bubble_client import BubbleClient
from .config import Config
from .mfl_client import MFLClient, normalize_mfl_id

SYNC_WORKFLOW = "sync_all_teamplayer_scores_beta"


def load_mfl_id_map(csv_path: str) -> dict:
    """MFL_PLAYER_ID -> row, from the NFLPlayers_with_MFL_IDs.csv mapping
    file. normalize_mfl_id() here matters more than it looks — this CSV is
    hand-edited/exported from a spreadsheet, exactly the kind of file where
    a leading zero or accidental numeric formatting could sneak in."""
    with open(csv_path, newline="", encoding="utf-8") as f:
        return {normalize_mfl_id(row["MFL_PLAYER_ID"]): row for row in csv.DictReader(f)}


def run(week: int, live: bool) -> None:
    config = Config.from_env()
    mfl = MFLClient(config)
    id_map = load_mfl_id_map(config.mfl_player_id_csv)

    scores = mfl.get_player_scores(week)
    print(f"MFL returned {len(scores)} player scores for week {week}")

    matched, unmatched = [], []
    for entry in scores:
        mfl_id = normalize_mfl_id(entry["id"])
        if mfl_id in id_map:
            matched.append((mfl_id, id_map[mfl_id]["name"], entry["score"]))
        else:
            unmatched.append(mfl_id)

    print(f"matched {len(matched)} / {len(scores)} against {config.mfl_player_id_csv}")
    if unmatched:
        print(f"unmatched MFL ids (not in CSV): {unmatched[:20]}{'...' if len(unmatched) > 20 else ''}")

    print("sample:")
    for mfl_id, name, score in matched[:10]:
        print(f"  {name:25s} mfl_id={mfl_id:>8s} score={score}")

    if not live:
        print("\ndry run only — pass --live to PATCH these into Bubble and trigger the sync workflow")
        return

    bubble = BubbleClient(config)
    patched = 0
    for mfl_id, name, score in matched:
        player = bubble.find_one("NFLPlayer", [{"key": "MFL_PLAYER_ID", "constraint_type": "equals", "value": mfl_id}])
        if not player:
            print(f"  no Bubble NFLPlayer found for {name} (mfl_id={mfl_id}), skipping")
            continue
        bubble.patch("NFLPlayer", player["_id"], {"this_week_score": float(score)})
        patched += 1

    print(f"patched {patched} NFLPlayer records")
    print(f"triggering {SYNC_WORKFLOW}...")
    result = bubble.trigger_workflow(SYNC_WORKFLOW)
    print(f"workflow result: {result}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Pull one week of MFL scores and (optionally) push them into Bubble.")
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--live", action="store_true", help="actually PATCH Bubble and trigger the sync workflow (default: dry run)")
    args = parser.parse_args()
    run(args.week, args.live)


if __name__ == "__main__":
    sys.exit(main())
