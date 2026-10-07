# Data structure (SCHEMA.md)

The agreed structure for all stored data. Every phase and the backfill write through
`src/odds_analysis/store.py`, which checks each row against `src/odds_analysis/schema.py` (the same tables in
code). Change both together and raise `SCHEMA_VERSION`. **Schema version: 1.**

Open points where your spec could not be followed exactly are listed under [Decisions needed](#decisions-needed);
nothing there was changed without asking.

## General rules

| Rule | How it is implemented |
|---|---|
| Parquet, zstd | `pyarrow`, zstd compression, one schema per table (exact column order and types) |
| Partitions | history tables: `data/<table>/season=<season>/league=<league_id>/part-0000.parquet`; our own odds snapshots additionally `.../date=YYYY-MM-DD/` (capture date, UTC); small tables (leagues, teams, markets, runs): `data/<table>/part-0000.parquet` |
| Season in folder names | `2024/25` is written `season=2024-25` (a `/` can't be part of a folder name); the column value stays `2024/25` |
| No file over 50 MB | files are split into `part-0000`, `part-0001`, … (each ≤ 45 MB) |
| Times in UTC | every `*_utc` column is a UTC timestamp; `matches.kickoff_local_tr` is the Turkey time as text with offset (`2025-10-18T14:30:00+03:00`) |
| Decimals | dot decimals; odds float rounded to 2 decimals (`"2,051"` → `2.05`) |
| Missing = NULL | `"-"`, `""` are rejected; zero means a real zero |
| IDs are strings | `match_id`, `market_type_id`, `iddaa_event_code`, … stored as text |
| Turkish next to English | `name_tr` / `selection_name_tr` / `market_name_tr` next to English keys |
| `schema_version`, `ingested_at_utc` | in every table; `ingested_at_utc` = when the row was first written, kept while the row is unchanged (so unchanged data gives no git change) |
| Season label | `"2024/25"` split-year leagues, `"2024"` calendar-year leagues (Norway, MLS, Brazil, Japan, Argentina) |
| Writes | upsert by key: an unchanged row is kept as it is, a changed row replaces the old one; rows are sorted by key |

Types used below: `string`, `int`, `float`, `bool`, `ts` (UTC timestamp), `list` (list of strings).
**Bold** = NOT NULL. Key columns are listed under each table.

## Tables

### 1. leagues — `data/leagues/`
From `config/leagues.yaml` (26 leagues). Key: `league_id`.

| Column | Type | Notes |
|---|---|---|
| **league_id** | string | ours: `<country>-<tier>`, e.g. `TUR-1`, `ENG-2`, `NED-2` |
| **name_en** / **name_tr** | string | e.g. `England Premier League` / `İngiltere Premier Lig` |
| **country** | string | |
| **tier** | int | |
| **mackolik_new_id** | string | competition id on www.mackolik.com |
| arsiv_code, arsiv_league_id | string | arsiv iddaa list code/id; NULL until seen (filled automatically, never guessed) |
| **season_format** | string | `split` \| `calendar` |
| **active** | bool | |

### 2. teams — `data/teams/`
Key: `team_id`.

| Column | Type | Notes |
|---|---|---|
| **team_id** | string | ours: `<country of the league>-<ASCII slug of the Mackolik name>`, e.g. `TUR-FENERBAHCE`, `ENG-NOT_FOREST`; never reused |
| **name_tr** | string | Mackolik's name (e.g. `Not. Forest`) |
| name_en | string | see [Decisions needed](#decisions-needed) – NULL for now |
| mackolik_new_id | string | team id on www.mackolik.com |
| arsiv_team_id | string | from the arsiv popup (`homeTeamOcId`) |
| country | string | |
| aliases | list | other names Mackolik used for the same team |

### 3. matches — `data/matches/season=…/league=…/`
Key: `match_id`.

| Column | Type | Notes |
|---|---|---|
| **match_id** | string | www.mackolik.com match uuid (the arsiv popup carries it too) |
| iddaa_event_code | string | Nesine event code |
| arsiv_match_id | string | arsiv match id |
| **league_id**, **season** | string | |
| **season_type** | string | `regular` \| `playoff` \| `special`. Playoff = promotion/relegation/European play-offs, play-outs, knock-out rounds; championship/relegation *groups* are `regular`; Japan's 2026 "J1 100 Year Vision League" is `special` |
| round | string | Mackolik's stage name (e.g. `Yükselme Play-off - Final`); NULL when Mackolik has none (most regular-season matches) |
| **kickoff_utc** | ts | |
| **kickoff_local_tr** | string | Turkey time with offset |
| **home_team_id**, **away_team_id** | string | |
| **status** | string | `scheduled` \| `finished` \| `postponed` \| `cancelled` \| `abandoned` \| `pending` |
| ht_home, ht_away, ft_home, ft_away | int | FT = after 90 minutes |
| et_home, et_away | int | after extra time (only if played) |
| pen_home, pen_away | int | shoot-out |
| referee | string | NULL in history (the new site has no referee); filled for matches we collect daily |
| stadium | string | from the statistics page |

### 4. markets — `data/markets/`
One row per Nesine market type. Key: `market_type_id`.

| Column | Type | Notes |
|---|---|---|
| **market_type_id** | string | Nesine's id. Some types are one line each (goals O/U 1.5 = 11, 2.5 = 12, 3.5 = 13), some cover several lines (corners O/U 8.5/9.5/10.5 = 216, card points = 301, handicap = 268) – the line is always in the odds row |
| market_key | string | English, without the line: `1X2`, `DC`, `OU`, `HT_OU`, `TEAM_OU_HOME`, `HANDICAP`, `HT_FT`, `CORRECT_SCORE`, `1X2_AND_OU`, `CORNERS_OU`, `CARD_POINTS_OU`, `PLAYER_TO_SCORE`, … NULL = not mapped yet (logged, never guessed) |
| **name_tr** | string | Nesine's name; for a type covering several lines the line is removed (`Korner Alt/Üst`) |
| family | string | `result` \| `goals` \| `halves` \| `handicap` \| `combo` \| `corners` \| `cards` \| `player` \| `special` |
| **has_line** | bool | |
| **settle_source** | string | `official` (Nesine marks winners) \| `engine` (we compute it) \| `none` (can't be settled from Mackolik data) |
| first_seen_season | string | |

### 5. odds — `data/odds/season=…/league=…/` (+ `date=…/` for our snapshots)
One row per selection and price. Key: `match_id, market_type_id, line, handicap_home, handicap_away, selection_key, price_type, captured_at_utc`.

| Column | Type | Notes |
|---|---|---|
| **match_id**, **market_type_id** | string | |
| market_key | string | |
| line | float | NULL if none |
| handicap_home, handicap_away | int | iddaa `Hnd. MS (0:1)` → 0 and 1 |
| **selection_key** | string | `1` `X` `2` `OVER` `UNDER` `YES` `NO` `1X` `12` `X2` `ODD` `EVEN` `1H` `2H` `EQUAL` `NONE` (no goal/corner), HT/FT `1/X`, scores `2-1` / `OTHER`, ranges `2-3` `6+`, combos `1&OVER` `X&YES` `UNDER&NO`, winning margin `1_2` `2_3+`, player/special: ASCII name in upper case (`ALEJANDRO_GARNACHO`, `HOME_GERIDEN_GELIP_KAZANIR`), `UNNAMED` for Nesine's empty `-` placeholder |
| selection_name_tr | string | Nesine's text; NULL only for the `-` placeholder |
| odds | float | NULL = offered without a price |
| mbs | int | minimum number of events in a coupon |
| **price_type** | string | `closing_history` \| `opening_snapshot` \| `intraday_snapshot` \| `closing_snapshot` |
| captured_at_utc | ts | when we read the price; NULL for `closing_history` (Nesine's last pre-kickoff price, time of last change unknown) |
| minutes_before_kickoff | int | NULL for `closing_history` |
| **source** | string | `arsiv` \| `new` |

Price types:
- `closing_history`: the backfill. One price per selection, the last pre-kickoff price. No opening price, no line movement.
- `opening_snapshot`: the first time our snapshot saw the selection.
- `intraday_snapshot`: a later snapshot whose price differs from the previous one (unchanged prices are not stored again).
- `closing_snapshot`: a full copy of the last snapshot taken before kickoff, all selections, changed or not. If a later pre-kickoff snapshot arrives, the earlier closing rows become `intraday_snapshot`.

### 6. settlements — `data/settlements/season=…/league=…/`
Key: `match_id, market_type_id, line, handicap_home, handicap_away, selection_key`.

| Column | Type | Notes |
|---|---|---|
| **match_id**, **market_type_id**, line, handicap_home, handicap_away, **selection_key** | | as in odds |
| hit_official | bool | Nesine's winner mark (popup highlight); only for `official` markets where Nesine marked a winner |
| hit_engine | bool | our engine (scores, events, statistics) |
| hit | bool | `hit_official` if present, else `hit_engine` |
| **status** | string | `settled` \| `void` (match postponed/cancelled/abandoned) \| `pending` \| `unsettleable` \| `unverified` |
| settle_basis | string | `official` \| `engine` (NULL when not settled) |
| **settled_at_utc** | ts | |

Settlement rules (`config/pipeline.yaml` → `settlement`):
- **Official:** goal and result markets use Nesine's winner marks. The engine still computes `hit_engine` as a cross-check: in the example below it agreed on 380 of 380 selections.
- **Engine:** markets with no winner marks from Nesine:
  - corners (from the statistics page);
  - card points;
  - red card, penalty, first goal, 2nd-half BTTS (from the key events).
- **Unsettleable:**
  - player and special markets (Mackolik has no data for them);
  - half-time corner markets (the new site's statistics have no first-half corner count);
  - Belgium 2019/20 corner markets (no corner statistics for that season).
- **Unverified:** card-point markets (`CARD_POINTS_OU`, `HT_CARD_POINTS_OU`, `MOST_CARD_POINTS`). They are computed with the Nesine help-text rule, but they stay out of analyses until you confirm the rule.

### 7. events — `data/events/season=…/league=…/`
Key: `match_id, event_order`.

| Column | Type | Notes |
|---|---|---|
| **match_id** | string | |
| **event_order** | int | 1, 2, … in feed order |
| minute, added_minute | int | `90 +5` → 90 and 5 |
| team_side | string | `home` \| `away`; for goals the side the goal counts for (also own goals), so it matches `score_after` |
| **event_type** | string | `goal` \| `penalty_goal` \| `own_goal` \| `missed_penalty` \| `yellow` \| `second_yellow` \| `red` \| `sub_in` \| `sub_out` (a substitution = one `sub_out` + one `sub_in` row) |
| player_name, assist_name | string | |
| score_after | string | after goals, e.g. `2-1` |

### 8. stats — `data/stats/season=…/league=…/`
One row per team. Key: `match_id, team_side`.

| Column | Type | Notes |
|---|---|---|
| **match_id**, **team_side** | string | |
| corners, yellow_cards, shots, shots_on_target, fouls, offsides, crosses | int | statistics page; no "Sarı Kart" row = 0 yellow cards (checked against the key events) |
| red_cards, second_yellows | int | counted from the key events (red includes second-yellow reds) |
| possession_pct | float | |
| **stats_source** | string | `opta` \| `rb` (arsiv pages, daily pipeline) \| `new` (www.mackolik.com) |

### 9. runs — `data/runs/`
Key: `run_id`.

| Column | Type | Notes |
|---|---|---|
| **run_id** | string | `<job>-<started_at>` |
| **job** | string | `snapshot` \| `results` \| `backfill` \| `analysis` |
| **started_at_utc** | ts | |
| finished_at_utc | ts | |
| **status** | string | `ok` \| `partial` \| `failed` (rules in the README) |
| requests, errors, matches_saved | int | |
| notes | string | |

## Derived: analysis_flat — `data/analysis_flat/season=…/league=…/`
Rebuilt automatically from the tables above, never edited by hand (`src/odds_analysis/flat.py`).

**Rows.** One row per match × market × selection that Nesine offered. That includes selections without a price and markets we can't settle; both are flagged.

**Columns** (in addition to the spec, `market_name_tr`, `family`, `closing_source`, the team names and `in_default_analysis` were added):

| Column | Notes |
|---|---|
| match_id, league_id, season, season_type, kickoff_utc | |
| home_team_id, away_team_id | |
| home_team_tr, away_team_tr | |
| ht_home, ht_away, ft_home, ft_away | |
| corners_total, yellow_cards_total, red_cards_total | |
| market_type_id, market_key, market_name_tr, family | |
| line, handicap_home, handicap_away | |
| selection_key, selection_name_tr | |
| closing_odds, closing_source | `closing_snapshot` if we have one, else `closing_history` |
| opening_odds | first `opening_snapshot`; NULL in history |
| odds_movement_pct | `(closing / opening − 1) × 100`; only from our own snapshots |
| implied_prob | `1 / closing_odds` |
| fair_prob, market_margin | margin removed within the market. Only for complete markets (every selection priced) that are a real split of outcomes; double chance is divided by 2; not for player/special markets |
| hit, status | from settlements |
| in_default_analysis | false for `season_type = special`, card markets (until Kart Puanı is confirmed) and anything not `settled` |

**Exports:**
- `exports/analysis_flat/<season>.csv.gz`
- `exports/analysis_flat/<season>.xlsx`, one sheet per league

See decision 1 below: these won't fit size limits for full seasons.

## Data quality checks — `data/quality.csv`
Run after every job, appended. One row per check and league-season, with status `ok`/`warn`/`fail`, a value and details.

| Check | Status if not met |
|---|---|
| duplicate keys in every table | fail |
| odds/settlement rows point to an existing match and market; events/stats to an existing match | fail |
| odds between 1.01 and 1000 | fail |
| implied probabilities of a complete closing market sum to 100–130 % | warn (see decision 2) |
| finished matches have HT and FT scores | fail |
| goals in the key events (up to minute 90) = FT score, when events exist | warn |
| the odds popup belongs to the right match: the uuid must match (history); uuid/teams/kickoff (daily). A wrong popup is rejected at ingestion and counted here | warn |
| coverage: share of finished matches with odds, events, stats per league/season | value only |

## Example (real data)

`scripts/schema_example.py --date 2025-10-18 --league ENG-1 --limit 2` produced these rows from Mackolik. The quality checks on them gave 0 fail and 1 warn: `market_sum`, the high-margin markets in decision 2.

**matches**

| match_id | iddaa_event_code | league_id | season | season_type | kickoff_utc | kickoff_local_tr | home_team_id | away_team_id | status | ht | ft | stadium |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1ul4lz9b1npclnmnufhedm7tg | 2367090 | ENG-1 | 2025/26 | regular | 2025-10-18 11:30:00+00 | 2025-10-18T14:30:00+03:00 | ENG-NOT_FOREST | ENG-CHELSEA | finished | 0-0 | 0-3 | The City Ground |

**odds** (Nottingham Forest – Chelsea; `price_type` `closing_history`, `captured_at_utc`/`minutes_before_kickoff` NULL, `source` arsiv, `mbs` 1)

| market_type_id | market_key | line | handicap_home | handicap_away | selection_key | selection_name_tr | odds |
|---|---|---|---|---|---|---|---|
| 1 | 1X2 | NULL | NULL | NULL | 1 | 1 | 2.80 |
| 1 | 1X2 | NULL | NULL | NULL | 2 | 2 | 1.95 |
| 11 | OU | 1.5 | NULL | NULL | OVER | Üst | 1.11 |
| 268 | HANDICAP | NULL | 0 | 1 | 2 | 2 | 1.09 |
| 5 | HT_FT | NULL | NULL | NULL | 1/2 | 1/2 | 24.85 |
| 216 | CORNERS_OU | 9.5 | NULL | NULL | UNDER | Alt | 1.88 |
| 301 | CARD_POINTS_OU | 3.5 | NULL | NULL | OVER | Üst | 1.13 |
| 701 | PLAYER_TO_SCORE | NULL | NULL | NULL | ALEJANDRO_GARNACHO | Alejandro Garnacho | 3.05 |

**settlements** (same selections)

| market_type_id | line | selection_key | hit_official | hit_engine | hit | status | settle_basis |
|---|---|---|---|---|---|---|---|
| 1 | NULL | 1 | false | false | false | settled | official |
| 1 | NULL | 2 | true | true | true | settled | official |
| 11 | 1.5 | OVER | true | true | true | settled | official |
| 268 | NULL | 2 | true | true | true | settled | official |
| 5 | NULL | 1/2 | false | false | false | settled | official |
| 216 | 9.5 | UNDER | NULL | true | true | settled | engine |
| 301 | 3.5 | OVER | NULL | true | true | unverified | engine |
| 701 | NULL | ALEJANDRO_GARNACHO | NULL | NULL | NULL | unsettleable | NULL |

**events** (first rows)

| event_order | minute | added_minute | team_side | event_type | player_name | assist_name | score_after |
|---|---|---|---|---|---|---|---|
| 1 | 41 | NULL | home | yellow | Morato | NULL | NULL |
| 2 | 46 | NULL | away | sub_out | R. Lavia | NULL | NULL |
| 3 | 46 | NULL | away | sub_in | M. Caicedo | NULL | NULL |

**stats**

| team_side | corners | yellow_cards | red_cards | second_yellows | shots | shots_on_target | possession_pct | fouls | offsides | crosses | stats_source |
|---|---|---|---|---|---|---|---|---|---|---|---|
| home | 5 | 2 | 0 | 0 | 12 | 2 | 50.0 | 13 | 1 | 23 | new |
| away | 2 | 3 | 1 | 1 | 17 | 6 | 50.0 | 16 | 2 | 9 | new |

**analysis_flat** (selected columns)

| market_key | line | selection_key | closing_odds | closing_source | implied_prob | fair_prob | market_margin | hit | status | in_default_analysis |
|---|---|---|---|---|---|---|---|---|---|---|
| 1X2 | NULL | 1 | 2.80 | closing_history | 0.357 | 0.299 | 0.194 | false | settled | true |
| 1X2 | NULL | X | 3.09 | closing_history | 0.324 | 0.271 | 0.194 | false | settled | true |
| 1X2 | NULL | 2 | 1.95 | closing_history | 0.513 | 0.430 | 0.194 | true | settled | true |
| CORNERS_OU | 9.5 | UNDER | 1.88 | closing_history | 0.532 | 0.434 | 0.226 | true | settled | true |

## Decisions needed

These are the points where your spec doesn't fit. In each case I implemented your spec, or the closest version of it, and changed nothing else.

1. **Export size.** A 2025/26 match has about 630 selections: about 330 player-market selections, 60 special, 240 others. Measured on the example: CSV.gz about 25 bytes per row, XLSX about 150 bytes per row.
   - Per season, all 26 leagues: about 5 million rows. That is far above Excel's limit of 1,048,576 rows per sheet, and the CSV.gz would be about 130 MB, above the 50 MB file limit.
   - Per season and league: about 240,000 rows, an XLSX of about 37 MB.

   **Proposal:**
   - CSV.gz per season *and* league, with every row: about 6 MB;
   - XLSX per season and league without player/special markets: about 90,000 rows, about 14 MB, opens on the iPad.

2. **The 100–130 % market-sum check flags normal Nesine markets.** Nesine's margin is about 19 % on 1X2 and 19–23 % on O/U, but higher elsewhere:

   | Market | Margin |
   |---|---|
   | Double chance | ~32 % (after dividing by 2) |
   | Combos (1X2 & O/U …) | ~32 % |
   | 3-way handicap | ~43 % |
   | Winning margin | ~55 % |
   | HT/FT correct score | ~58 % |

   **Proposal:** keep 100–130 % for 2- and 3-way markets, and allow up to 170 % for markets with more selections. For now it is a warning only.
3. **Team English names.** Mackolik only has Turkish display names, often already English-like (`Brighton`, `Not. Forest`, `Bayern Münih`), and "no external sources" rules out an English source. **Proposal:** `name_en` stays NULL unless you fill a small `config/teams_en.yaml` yourself; `team_id` uses the ASCII form of the Mackolik name.
4. **Red-card market.** "Card markets excluded" currently excludes the whole cards family, including `RED_CARD`, whose rule is simple (any red card). Should `RED_CARD` count as settled and analysable?
5. **runs.job values.** Settlement and export run inside the results workflow and are logged as `results` with a note; the health check is not logged. Is that OK, or should `settle`/`export` be their own job values?

Not decisions, just stating how the spec is applied:
- the season is written `2024-25` in folder names;
- `captured_at_utc` is NULL for `closing_history`;
- `selection_key = UNNAMED` for Nesine's `-` placeholder;
- `round` holds Mackolik's stage name;
- `referee` is NULL in history.

## Not yet switched over

This PR adds the structure and the code that writes it. The daily jobs still write the old CSV tables. In the next phase they move to these tables, and the data collected so far (since 2026-10-06) is converted. The backfill writes these tables from its first run.
