# Hot Route — Engine Build Handoff

Streak-based fantasy football app (hot-route.app, built in Bubble). 1v1 weekly
matchups, best-ball, half-PPR, $200 salary cap. Win 7 in a row to take the pot
and end your season (streak resets to 0 on a loss, team keeps playing — no
elimination). Goal: live by Week 1, early September 2026.

## What we're building

An external Python script, on a GitHub Actions cron, that owns all the weekly
data-grind Bubble shouldn't do in-app. Three tracks:

- **Track A — weekly final scores (DONE, proven).** Pull scores from MFL,
  PATCH into Bubble, fan out to rosters.
- **Track A2 — MFL lineup backup (mechanics proven, needs 2026 data).**
  Submit a full-roster "lineup" to MFL once before the season, as a backup
  record — see below.
- **Track B — live in-game scoreboard (not started).** Next up.

Bubble stays in charge of: UI, best-ball optimization (who's the actual
starter each week), matchup display, streak computation — everything
user-facing. The script never decides who's a starter; that's Bubble's job,
always computed from raw scores after the fact.

## Repo state (as of 2026-08-07)

Already scaffolded and working, not "to be built":

```
src/hotroute/
  config.py          - loads .env (MFL + Bubble creds, host/year/league id)
  mfl_client.py       - MFL API client: scores, player dictionary, login, lineup import
  bubble_client.py    - Bubble Data API (GET/PATCH) + Workflow API (trigger)
  weekly_run.py        - Track A: python -m hotroute.weekly_run --week N [--live]
  lineup_setup.py      - Track A2: python -m hotroute.lineup_setup [--live] [--roster-csv PATH]
.env                  - real working creds for local testing (gitignored)
.env.example
requirements.txt       - requests, python-dotenv
NFLPlayers_with_MFL_IDs.csv    - old/partial MFL_PLAYER_ID mapping (2025-drafted players only, has at least one known-wrong id — see "MFL_PLAYER_ID backfill" below)
2025_franchise_rosters.csv      - full 36-franchise roster + MFL_PLAYER_ID dump, used for Track A2 testing only
```

Deeper technical detail beyond this doc lives in Claude's memory system
(project memory: "Hot Route MFL integration") — a fresh session doesn't need
that unless something here is unclear or seems out of date.

## Data model (confirmed against live app)

```
User → FantasyTeam → TeamPlayer (roster) → NFLPlayer
Matchup = weekly 1v1 between two FantasyTeams
admin.current_week = global week counter (record doesn't exist yet — must create)
```

Key fields:
- `NFLPlayer.this_week_score` — scoring source of truth, set by the script
- `NFLPlayer.MFL_PLAYER_ID` — join key to MFL's player IDs (permanent across
  seasons, format is a plain numeric string like `"13593"`)
- `TeamPlayer.thisWeekScore` — copied from `NFLPlayer.this_week_score` via the
  sync workflow (see below)
- `TeamPlayer.week_2_score`, `week_3_score`, `week_4_score`... — history
  archive fields, never reliably populated last season
- `FantasyTeam.currentStreak` — needed for weekly pairing logic
- `PlayerScore.is_starter` / `is_bench` — load-bearing for best-ball, don't touch

Full schema: swagger file in Claude project knowledge.

## Track A — weekly final scores (DONE)

`python -m hotroute.weekly_run --week N --live` does, end-to-end, verified
with a real zero-and-recover test:

1. Pull `TYPE=playerScores` from MFL for week N
2. Match against Bubble `NFLPlayer` via `MFL_PLAYER_ID`, PATCH `this_week_score`
3. Trigger `sync_all_teamplayer_scores_beta` (see workflow notes below) —
   fans the score out to every `TeamPlayer`

Tested against `hot-route.app/version-test` using 2025 season data (the 2026
MFL league hasn't been rolled over yet as of this writing — `.env` is
intentionally pointed at `MFL_YEAR=2025` for now; switch it once 2026 exists
and re-verify before relying on it for real).

## Track A2 — MFL lineup backup (mechanics proven)

**Design:** submit each franchise's **full roster** as `STARTERS`, for
**weeks 1–18, ONE TIME**, a day or two before the season starts — not
weekly, not post-hoc. This matters because MFL locks lineup submissions per
player once their game kicks off, and Bubble's best-ball picks aren't known
until after scores land — those two facts are incompatible with a "set it
after the fact" design. Submitting once, pre-season, sidesteps the lock
entirely. Bubble's own logic still determines actual weekly starters; MFL's
copy is just a full-roster audit trail/backup.

`python -m hotroute.lineup_setup [--live] [--roster-csv PATH]` — fully built
and mechanically proven against real 2025 data: login works, franchise
impersonation works, and a real full-roster submission produces **zero**
composition errors (position/count rules all satisfied) — the only error
seen was the expected "lineup deadline has passed," which won't occur when
run for real before 2026 kickoff.

**What's still needed:** an equivalent Franchise ID → MFL_PLAYER_ID roster
CSV for the *2026* season, once that draft/rosters are finalized (same shape
as `2025_franchise_rosters.csv`, which was only for testing). MFL's own
`TYPE=rosters` export is unreliable for this league (confirmed — showed 0
players for franchises that demonstrably had real rosters) so don't fall
back to it; use a CSV or pull straight from Bubble's live `TeamPlayer` data
once dev/live are the same data.

MFL API notes specific to this track:
- Login/write operations need real `MFL_USERNAME`/`MFL_PASSWORD` — the
  APIKEY parameter does **not** work for imports or commissioner
  impersonation, only for reads (confirmed against MFL's own docs twice)
- Login goes through `api.myfantasyleague.com` (generic host), not the
  league-specific one, and returns XML with `MFL_USER_ID` as a root
  attribute — manually set as a cookie afterward, no real Set-Cookie flow
- `import?TYPE=lineup` always responds XML regardless of the `JSON` param
- MFL's server has a 1-second Keep-Alive timeout that causes occasional
  `RemoteDisconnected` errors on reused connections — `mfl_client.py`
  mounts a `urllib3.Retry`-backed adapter to handle this transparently

## Track B — live in-game scoreboard (NEXT, not started)

**Goal:** a "close to live, not quite" scoreboard during games, not a
minute-by-minute ticker.

**Constraints already agreed:**
- Poll every 30–60 minutes (not continuous) during game windows only —
  Thursday night, Sunday, Monday night. Framed to users as an intentional
  design choice, not a technical limitation.
- Bubble budget: **175,000 WU/month**, 50GB storage. Only ~1,376 WU used in
  the last 30 days (basically just this session's testing) — real headroom,
  but Track B needs to be much leaner per-poll than Track A's testing was
  (a single full Track A test run PATCHing 138 players + syncing 205
  TeamPlayers is not a sustainable per-poll cost at ~35 polls/week during
  season).
- `TYPE=liveScoring` (not `playerScores`) is the right MFL endpoint — it
  returns both team totals AND individual player scores in one call
  (contrary to an early, wrong assumption from a web search — verified live
  against real data), nested `matchup → franchise → players`, plus live
  game state (`gameSecondsRemaining`, `playersCurrentlyPlaying`).
- **Never trust MFL's per-player `status` field (starter/nonstarter) or its
  team-level `score` total** — both reflect MFL's own manually-set lineup
  concept, which has nothing to do with Hot Route's best-ball logic (Bubble
  picks the actual best-scoring lineup automatically, and that pick can
  change *during* a game as scores update). Only use the raw per-player
  scores from `liveScoring`; let Bubble compute the live best-ball total
  itself from those.
- For `liveScoring` to return anything, MFL needs to know the matchup
  schedule (which franchise plays which). Whether that's already usable
  as-is from last year's schedule or needs pushing weekly was explicitly
  left as "don't worry about it yet, get back on track in general" —
  revisit this before assuming it just works.

**Not yet designed:**
- Exact GitHub Actions cron windows (need real Thu/Sun/Mon NFL kickoff
  time ranges in UTC)
- What exactly gets written to Bubble each poll, and how cheaply (probably:
  raw per-player live scores only for players whose games are in progress,
  not a full-league PATCH+sync every time)
- Whether Bubble's frontend can compute "current best-ball total so far"
  live from partial in-progress scores, or whether that needs new backend
  logic too — user said "I might have an idea" but it wasn't confirmed
- How this interacts with Track A2's matchup-schedule question above

## Existing Bubble workflows

**`sync_all_teamplayer_scores_beta`** — the one Track A actually calls.
Built this session. API Event, no required params, exposed publicly,
"ignore privacy rules" ON. Internally: "Schedule API Workflow on a list"
(Search for TeamPlayers → calls `sync_teamplayer_this_week_score_2025` once
per TeamPlayer with `teamPlayer: This TeamPlayer`). Runs async — allow a few
seconds after calling before verifying results.

**`sync_teamplayer_this_week_score_2025`** — single-record workflow (takes
one `teamPlayer` param), the thing `sync_all_teamplayer_scores_beta` fans
out to. NOT directly what Track A calls anymore, but still the underlying
per-record logic. Sets `TeamPlayer.thisWeekScore = teamPlayer's player's
this_week_score`. "Ignore privacy rules" ON — required.

**`sync_teamplayer_this_week_score`** (no suffix) — referenced in earlier
planning docs as if it ran on a full list with zero params. **That workflow
either doesn't exist or isn't exposed in the test version** — don't assume
it's there without checking again.

**`reset_this_week_score`** — API Event, sets `NFLPlayer.this_week_score = 0`.
Used at end of week, before next week's scores come in. Not yet wired into
the script.

**`changing_week_x_score_nflplayer`** — BROKEN, do not reuse. Orphaned, 0
triggers, hardcoded to `week_2_score` only. **Decision: scrap this. Script
owns archiving from scratch, parameterized by week number, not yet built.**

## Open items to verify in Bubble (not yet confirmed)

- Does `admin.current_week` need a record created from scratch? (Yes — dev
  and live app data are both empty)
- Any other page workflows referencing `current_week`? (Not found yet)

## MFL_PLAYER_ID backfill (open, not yet built)

`NFLPlayers_with_MFL_IDs.csv` (the original mapping, ~138-250 players) has
**at least one confirmed wrong ID**: Lamar Jackson is mapped to `13122`,
which doesn't exist in MFL's system at all — his real ID is `13593`. Found
by comparing against MFL's authoritative player dictionary
(`api.myfantasyleague.com` — must go through the generic host, not the
league-specific one, confirmed live). That dictionary uses `"Last, First"`
name format (e.g. `"Jackson, Lamar"`), ~2,395 real players after filtering
out team-defense/coach placeholder entries.

**Recommended fix, not yet built:** re-derive `MFL_PLAYER_ID` for all of
Bubble's existing `NFLPlayer` records by name-matching against MFL's
dictionary, rather than trusting the old CSV — this fixes wrong entries
like Lamar Jackson's too, not just gaps. Watch for name-format conversion
(Last,First → First Last) and suffix/hyphen edge cases (Jr./II/III,
hyphenated last names).

## Schedule/pairing design (agreed, not yet built)

- Weeks 1–3: random matchups (existing logic, keep as-is)
- Week 4+: sort all `FantasyTeam`s by `currentStreak` descending, pair
  adjacent teams down the list (1v2, 3v4, 5v6...)
- No bye logic needed — team count is always kept even by design
- Rematch avoidance — explicitly out of scope for v1
- Lives in the Python script, not a Bubble workflow

## API references

- MFL scores (final): `export?TYPE=playerScores&L={league}&W={week}&JSON=1`
- MFL live scores: `export?TYPE=liveScoring&L={league}&W={week}&DETAILS=1&JSON=1`
- MFL player dictionary: `export?TYPE=players&DETAILS=1&JSON=1` — **must go
  through `api.myfantasyleague.com`**, not the league-specific host
- MFL rosters export: unreliable for this league, don't use — see Track A2
- MFL host: league-specific (e.g. `www45.myfantasyleague.com` for league
  15952) for league-scoped reads; generic `api.myfantasyleague.com` for the
  player dictionary and for login. Get the real host from the league's own
  URL, don't assume the generic front door redirects correctly (it doesn't
  always — returns "Invalid league ID" instead)
- MFL defaults to XML — add `JSON=1`, except login and `import?TYPE=lineup`
  which always respond XML regardless
- MFL rate limiting: registered API client (`HOTROUTE_01`, validated
  through Sep 11 2026) gets a higher limit — `mfl_client.py` sends a
  matching `User-Agent` header
- Bubble Data API root: `/api/1.1/obj/{type}`
- Bubble Workflow API: same base, `/api/1.1/wf/{workflow_name}`

## Security — non-negotiable

- Never put the Bubble API token, MFL API creds, or MFL login credentials
  in code or chat
- `.env` now holds: `MFL_LEAGUE_ID`, `MFL_YEAR`, `MFL_HOST`,
  `MFL_USERNAME`, `MFL_PASSWORD`, `BUBBLE_APP_URL`, `BUBBLE_API_TOKEN`
- Use `.env` locally, GitHub Actions secrets in CI
- If a secret leaks: regenerate it immediately, don't wait

## Known tech debt (don't build on these without asking first)

- `weeklyPlayerScore` table — likely dead, don't use
- Two lineup systems exist — confirm which is live before touching lineup
  logic
- Duplicate roster/budget/payment fields — flag before relying on any
  specific one
- `PlayerScore.is_starter`/`is_bench` is the **exception** — this one is
  confirmed load-bearing, keep it

## Still not decided / not needed yet

- Team count this season — explicitly left loose/backburner
- Player pricing refresh — queued after the engine is working
- Player blurbs, UI cleanup — post-launch nice-to-haves

## Immediate next step

**Track B.** Start by nailing down: (1) real NFL kickoff time windows for
Thu/Sun/Mon in UTC for the cron schedule, (2) what a single poll actually
writes to Bubble and how to keep it cheap, (3) whether MFL's matchup
schedule needs to be pushed weekly for `liveScoring` to return real data, or
whether it's already usable. Don't assume — verify live, same as everything
else in this doc.
