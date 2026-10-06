# Data layout

All files are daily partitions `data/<table>/YYYY-MM-DD.csv.gz`. The date is the **match date in Turkey time**, as shown in Mackolik's lists. Kickoffs are stored in both Turkey time (`kickoff_local`) and UTC (`kickoff_utc`). Times written by the pipeline (`*_utc`) are UTC.

Build a local database whenever you want one (it is not committed):
`PYTHONPATH=src python -m odds_analysis build-db --db odds.sqlite`

| Table | One row per | Written by | Notes |
|---|---|---|---|
| `matches` | match | snapshot, results | ids, league code, MBS, teams, kickoff, `first_seen_utc` |
| `odds` | selection × price change | snapshot, results | **Only changes are stored.** `snapshot_type`: `opening` (first price seen), `update` (price moved), `post_match` (price shown after full time, which is the pre-match closing price; used to backfill matches we did not snapshot). Closing = last pre-match row with `snapshot_utc` < kickoff. |
| `snapshots` | popup fetch | snapshot | proves when a match was last checked (unchanged prices are not re-stored) |
| `results` | match | results | `status` (`MS`, `Ert.`…), `result_type` (`final`/`void`), MS and İY from the match page (90-minute score), list scores, corners, referee/stadium, `events_complete`, `official_markets` |
| `events` | goal / card / sub | results | minute, team, type, detail (`penalty`, `own_goal`, `second_yellow`, `straight_red`), assist, running score |
| `stats` | match × source × stat | results | raw İstatistikler box: `opta` (page) or `rb` (fallback) |
| `official` | selection | results | Nesine's own result after full time: `highlight` = selection won; `market_decided` = Nesine marked at least one selection in that market |
| `settled` | selection | settlement (Phase 2) | hit / miss |

Logs (`data/*.csv`): `runs`, `unmapped_markets`, `score_mismatches` (list vs match page), `event_score_mismatches` (goal events don't add up to the score, e.g. a disallowed goal still listed), `extra_time_matches`, `settlement_mismatches` (Phase 2).

## Market keys

Turkish names are kept in `market_tr` / `selection_tr`. `market_key` / `selection` are English, for example:
`1X2` (home/draw/away), `DC` (1X/12/X2), `OU_2.5` (under/over), `BTTS` (yes/no), `HT_1X2`, `2H_1X2`, `HT_FT` (draw/away…), `HANDICAP_-1` (= Hnd. MS (0:1): the away side gets +1 goal), `TEAM_OU_home_1.5`, `1X2_AND_OU_2.5` (home_over…), `CORNERS_OU_9.5`, `CARDS_OU_3.5` (Kart Puanı), `FIRST_GOAL` (home/none/away). Full mapping: `src/odds_analysis/markets.py`. `family` groups markets by how they are settled: `score`, `first_goal`, `corners`, `ht_corners`, `corner_timing`, `cards`, `penalty`, and official-only (`player`, `team_stats`, `special`).
