import argparse
import sys

from .bubble_client import BubbleClient
from .config import Config

# Bubble backend workflow that recomputes bestball starter scores/positions
# from current TeamPlayer data. Runs entirely inside Bubble — this script's
# only job is to fire the trigger on a schedule.
WORKFLOW = "calculate_starter_score"


def run(live: bool) -> None:
    config = Config.from_env()

    if not live:
        print(f"dry run only — pass --live to actually trigger {WORKFLOW} in Bubble")
        return

    bubble = BubbleClient(config)
    print(f"triggering {WORKFLOW}...")
    result = bubble.trigger_workflow(WORKFLOW)
    print(f"workflow result: {result}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Trigger Bubble's calculate_starter_score backend workflow.")
    parser.add_argument("--live", action="store_true", help="actually trigger the workflow (default: dry run)")
    args = parser.parse_args()
    run(args.live)


if __name__ == "__main__":
    sys.exit(main())
