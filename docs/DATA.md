# Data layout

All files are daily partitions `data/<table>/YYYY-MM-DD.csv.gz`. The date is the **match date in Turkey time**, as shown in Mackolik's lists. Kickoffs are stored in both Turkey time (`kickoff_local`) and UTC (`kickoff_utc`). Times written by the pipeline (`*_utc`) are UTC.

Build a local database whenever you want one (it is not committed):
`PYTHONPATH=src python -m odds_analysis build-db --db odds.sqlite`

| Table | One row per | Written by | Notes |
|---|---|---|---|
| `matches` | match | snapshot, results | ids, league code, MBS, teams, kickoff, `first_seen_utc` |
| `odds` | selection × price change | snapshot, results | **Only changes are stored.** `snapshot_type`: `opening` (first price seen), `update` (price moved), `post_match` (price shown after full time, which is the pre-match closing price; used to backfill matches we did not snapshot). Closing = last pre-match row with `snapshot_utc` < kickoff. `source`: `popup` (odds popup B) or `morebets` (see below). |
| `snapshots` | popup fetch | snapshot | proves when a match was last checked (unchanged prices are not re-stored); `source` as in `odds` |
| `results` | match | results | `status` (`MS`, `Ert.`…), `result_type` (`final`/`void`), MS and İY from the match page (90-minute score), list scores, corners, referee/stadium, `events_complete`, `official_markets` |
| `events` | goal / card / sub | results | minute, team, type, detail (`penalty`, `own_goal`, `second_yellow`, `straight_red`), assist, running score |
| `stats` | match × source × stat | results | raw İstatistikler box: `opta` (page) or `rb` (fallback) |
| `official` | selection | results | Nesine's own result after full time: `highlight` = selection won; `market_decided` = Nesine marked at least one selection in that market |
| `settled` | selection | settle (after results) | `hit_official` (Nesine's mark), `hit_engine` (our rules), **`hit`** = official if Nesine marked the market, else engine; `void` for postponed/cancelled. `hit_source`: `official` / `engine` / `none` / `void`. `engine_only` = corners & cards (never officially marked). `agree` = official vs engine (1/0). `card_rule` = rule source for card markets |

Logs (`data/*.csv`): `runs`, `unmapped_markets`, `score_mismatches` (list vs match page), `event_score_mismatches` (goal events don't add up to the score, e.g. a disallowed goal still listed), `extra_time_matches`, `settlement_mismatches` (official ≠ engine, rebuilt on every settlement run).

## Market keys

Turkish names are kept in `market_tr` / `selection_tr`. `market_key` / `selection` are English, for example:
`1X2` (home/draw/away), `DC` (1X/12/X2), `OU_2.5` (under/over), `BTTS` (yes/no), `HT_1X2`, `2H_1X2`, `HT_FT` (draw/away…), `HANDICAP_-1` (= Hnd. MS (0:1): the away side gets +1 goal), `TEAM_OU_home_1.5`, `1X2_AND_OU_2.5` (home_over…), `CORNERS_OU_9.5`, `CARDS_OU_3.5` (Kart Puanı), `FIRST_GOAL` (home/none/away). Full mapping: `src/odds_analysis/markets.py`. `family` groups markets by how they are settled: `score`, `first_goal`, `corners`, `ht_corners`, `corner_timing`, `cards`, `penalty`, and official-only (`player`, `team_stats`, `special`).

## Odds popup pitfall (found in Phase 2)

For some event codes the odds popup (B) returns an **older match** that once had the same code. This happened for about 6% of upcoming matches and about 23% of finished ones. Every popup is therefore checked: its `iddaa_code` must equal the event code and its start time must match the kickoff (±6 h).
- **Snapshots:** if the check fails, the program's own "Tümü" data is used instead (`command=morebets&mac=<match_id>`, keyed by match id). Its prices are identical to B and the market names are mapped to B's, but it has fewer markets (no player or special markets) → `source = morebets`.
- **Results:** if the check fails, that match has no official marks and no post-match prices (`results.official_status = popup_other_match:<code>`). It is settled by the engine only.

## Exports (branch `exports`)

One row per match × market × selection:

| Column | Meaning |
|---|---|
| `opening_odds` / `opening_utc` | first price we saw (empty if we never snapshotted the match) |
| `closing_odds` / `closing_utc` | last price before kickoff; `closing_utc` = time of the last fetch before kickoff |
| `closing_min_before_ko` | how long before kickoff the closing price was taken |
| `closing_source` | `snapshot`, or `post_match` (price shown after full time, used for backfilled matches) |
| `odds_source` | `popup` or `morebets` |
| `odds_movement_pct` | closing / opening − 1, in % (negative = shortened) |
| `implied_prob` | 1 / closing price |
| `fair_prob` | implied probability with the margin removed proportionally, only for mutually exclusive markets with every selection priced (DC counts as 2 winners) |
| `market_margin` | overround of that market (sum of implied probabilities / winners − 1) |
| `hit`, `hit_source`, `hit_official`, `hit_engine`, `engine_only` | see `settled` above |
| `ht_*`, `ft_*`, `corners_*`, `card_pts_*` | match facts; card points use `config/card_rules.yaml` |
