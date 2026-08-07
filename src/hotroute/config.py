import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"missing required env var: {name}")
    return value


@dataclass(frozen=True)
class Config:
    mfl_league_id: str
    mfl_year: str
    mfl_host: str
    mfl_player_id_csv: str
    mfl_username: str | None
    mfl_password: str | None
    bubble_app_url: str | None
    bubble_api_token: str | None

    @classmethod
    def from_env(cls) -> "Config":
        # Bubble creds are only needed for --live runs, so they're not required
        # here — BubbleClient checks for them itself when it's actually used.
        bubble_app_url = os.environ.get("BUBBLE_APP_URL")
        return cls(
            mfl_league_id=_require("MFL_LEAGUE_ID"),
            mfl_year=os.environ.get("MFL_YEAR", "2026"),
            mfl_host=os.environ.get("MFL_HOST", "api.myfantasyleague.com"),
            mfl_player_id_csv=os.environ.get(
                "MFL_PLAYER_ID_CSV", "NFLPlayers_with_MFL_IDs.csv"
            ),
            # Only needed for write operations (e.g. setting lineups), so not
            # required here — MFLClient.login() checks for them itself.
            mfl_username=os.environ.get("MFL_USERNAME"),
            mfl_password=os.environ.get("MFL_PASSWORD"),
            bubble_app_url=bubble_app_url.rstrip("/") if bubble_app_url else None,
            bubble_api_token=os.environ.get("BUBBLE_API_TOKEN"),
        )
