import xml.etree.ElementTree as ET

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import Config

# Matches the registered HOTROUTE_01 API client's "Client User Agent" value
# in MFL's Developer's Program — unregistered/mismatched clients get
# throttled starting from the 2020 season onward.
USER_AGENT = "Upload scores and get scores potentially/1.0"


def normalize_mfl_id(raw) -> str:
    """MFL_PLAYER_ID gets joined across MFL's API, Bubble, and hand-edited
    CSV files with no shared canonical format — normalize defensively so a
    stray leading zero (e.g. from a CSV reformatted by Excel/Sheets), a
    float-like ".0" suffix (from an accidental numeric type somewhere), or
    incidental whitespace doesn't cause a silent join mismatch. Real MFL
    player ids are unpadded plain digit strings (e.g. "17071", "5848") in
    every response seen in this project — never zero-padded like MFL's
    franchise ids sometimes are, so stripping leading zeros is safe here."""
    s = str(raw).strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s.lstrip("0") or "0"


class MFLClient:
    def __init__(self, config: Config):
        self._config = config
        self._league_id = config.mfl_league_id
        self._host = config.mfl_host
        self._year = config.mfl_year
        self._league_base_url = f"https://{config.mfl_host}/{config.mfl_year}/export"
        # The full player dictionary isn't league-scoped and MFL requires it
        # to go through the generic front door, not a league-specific host.
        self._global_base_url = f"https://api.myfantasyleague.com/{config.mfl_year}/export"
        self._import_base_url = f"https://{config.mfl_host}/{config.mfl_year}/import"
        self._session = requests.Session()
        self._session.headers["User-Agent"] = USER_AGENT
        # MFL's server sets Keep-Alive: timeout=1s, so reused connections
        # occasionally get closed out from under us — retry transparently.
        retry = Retry(total=3, backoff_factor=0.5, allowed_methods=frozenset(["GET", "POST"]))
        adapter = HTTPAdapter(max_retries=retry)
        self._session.mount("https://", adapter)

    def _get(self, base_url: str, params: dict) -> dict:
        params = {**params, "JSON": 1}
        response = self._session.get(base_url, params=params, timeout=30)
        response.raise_for_status()
        return response.json()

    def login(self) -> None:
        """POST /login (generic host, XML response, credentials as query
        params per MFL's own client) — required before any import_* method,
        since writes need a real login, not an API key. Sets MFL_USER_ID as
        a cookie on self._session for subsequent import calls."""
        if not self._config.mfl_username or not self._config.mfl_password:
            raise RuntimeError("MFL_USERNAME and MFL_PASSWORD must be set in .env to log in")
        response = self._session.post(
            f"https://api.myfantasyleague.com/{self._year}/login",
            params={
                "USERNAME": self._config.mfl_username,
                "PASSWORD": self._config.mfl_password,
                "XML": 1,
            },
            timeout=30,
        )
        response.raise_for_status()
        root = ET.fromstring(response.content)
        user_id = root.get("MFL_USER_ID")
        if not user_id:
            raise RuntimeError(f"MFL login failed: {response.text}")
        self._session.cookies.set("MFL_USER_ID", user_id)
        self._session.cookies.set("MFL_LAST_LEAGUE_ID", self._league_id)

    def get_player_scores(self, week: int) -> dict:
        """TYPE=playerScores — one week's scores, keyed by MFL player id."""
        data = self._get(self._league_base_url, {"TYPE": "playerScores", "L": self._league_id, "W": week})
        entries = data["playerScores"]["playerScore"]
        # Every caller joins this against Bubble/CSV data by id — normalize
        # here so a silent format mismatch can't cause a lookup to just
        # quietly fail. See normalize_mfl_id() above for why.
        for entry in entries:
            entry["id"] = normalize_mfl_id(entry["id"])
        return entries

    def get_live_scores(self, week: int) -> dict:
        """TYPE=liveScoring — in-progress per-player scores for a week,
        flattened from matchup -> franchise -> players into a single dict
        keyed by MFL player id. Deliberately drops MFL's own per-player
        'status' (starter/nonstarter) — that reflects MFL's manually-set
        lineup, not Hot Route's best-ball logic, and isn't meaningful here."""
        data = self._get(
            self._league_base_url,
            {"TYPE": "liveScoring", "L": self._league_id, "W": week, "DETAILS": 1},
        )
        matchups = data["liveScoring"].get("matchup", [])
        if isinstance(matchups, dict):
            matchups = [matchups]

        scores = {}
        for matchup in matchups:
            franchises = matchup.get("franchise", [])
            if isinstance(franchises, dict):
                franchises = [franchises]
            for franchise in franchises:
                players = franchise.get("players", {}).get("player", [])
                if isinstance(players, dict):
                    players = [players]
                for p in players:
                    # Same normalize_mfl_id() reasoning as get_player_scores
                    # — this dict is joined against Bubble by key.
                    scores[normalize_mfl_id(p["id"])] = {
                        "score": float(p["score"]),
                        "gameSecondsRemaining": p.get("gameSecondsRemaining"),
                    }
        return scores

    def get_player_dictionary(self) -> dict:
        """TYPE=players&DETAILS=1 — full player list, keyed by MFL player id."""
        data = self._get(self._global_base_url, {"TYPE": "players", "DETAILS": 1})
        players = data["players"]["player"]
        # Same normalize_mfl_id() reasoning as get_player_scores/
        # get_live_scores — this is the dictionary backfill_mfl_ids.py
        # joins against Bubble by key.
        return {normalize_mfl_id(p["id"]): p for p in players}

    def get_franchise_ids(self) -> list[str]:
        """TYPE=league — every franchise id in the league."""
        data = self._get(self._league_base_url, {"TYPE": "league", "L": self._league_id})
        return [f["id"] for f in data["league"]["franchises"]["franchise"]]

    def get_roster(self, franchise_id: str, week: int) -> list[str]:
        """TYPE=rosters — a franchise's rostered MFL player ids for a week."""
        data = self._get(
            self._league_base_url,
            {"TYPE": "rosters", "L": self._league_id, "FRANCHISE": franchise_id, "W": week},
        )
        # MFL omits the "player" key entirely for an empty roster, and
        # collapses a single-player roster to a dict instead of a list.
        players = data["rosters"]["franchise"].get("player", [])
        if isinstance(players, dict):
            players = [players]
        return [p["id"] for p in players]

    def import_lineup(self, franchise_id: str, week: int, starter_ids: list[str]) -> None:
        """import?TYPE=lineup — sets a franchise's starters for a week.
        Requires login() first. FRANCHISE_ID lets a commissioner set lineups
        for any franchise, not just their own. Response is always XML
        regardless of JSON param."""
        response = self._session.post(
            self._import_base_url,
            params={
                "TYPE": "lineup",
                "L": self._league_id,
                "W": week,
                "FRANCHISE_ID": franchise_id,
                "STARTERS": ",".join(starter_ids),
            },
            timeout=30,
        )
        response.raise_for_status()
        root = ET.fromstring(response.content)
        if root.tag == "error":
            raise RuntimeError(root.text)
