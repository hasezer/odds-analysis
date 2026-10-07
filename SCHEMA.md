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

## Collected markets

Only the **45 markets in `config/markets.yaml`** (your selection of 2026-10-07) are stored. Player bets, card markets
(Kart Puanı, Kırmızı Kart), 1st-half corners and every other market are dropped when a popup is read and never stored.

| Group | Markets |
|---|---|
| Maç Sonucu | Maç Sonucu · Çifte Şans · İlk Yarı/Maç Sonucu · MS ve 1,5 / 2,5 / 3,5 / 4,5 Alt/Üst · MS ve Karşılıklı Gol |
| Yarı Sonucu | 1. Yarı Sonucu · 1. Yarı ve 1. Yarı KG · 2. Yarı Sonucu · Ev Sahibi / Deplasman Yarı Kazanır · Ev Sahibi / Deplasman İki Yarıyı da Kazanır |
| Alt/Üst | 0,5 / 1,5 / 2,5 / 3,5 / 4,5 Alt/Üst · 2,5 Alt/Üst ve Karşılıklı Gol |
| Yarı Alt/Üst | 1.Yarı ve 1.Yarı 1,5 Alt/Üst · 1. Yarı 0,5 / 1,5 Alt/Üst · İki Yarı da 1,5 Üst |
| Takım Alt/Üst | Ev Sahibi 0,5 / 1,5 / 2,5 · Deplasman 0,5 / 1,5 / 2,5 · 1. Yarı Ev Sahibi 0,5 · 1. Yarı Deplasman 0,5 |
| Gol | Karşılıklı Gol · 1. Yarı KG · 2. Yarı KG · 1. Yarı / 2. Yarı KG · Toplam Gol Aralığı |
| Kornerler | 8,5 / 9,5 / 10,5 / 11,5 / 12,5 Korner Alt/Üst |
| Maç Skoru | 1. Yarı Skoru · Maç Skoru |

Not every market exists for every match. Share of sampled matches that had the market:

| Market | When it is offered |
|---|---|
| Maç Skoru | ~95 % of sampled matches in most seasons, but only 17 of 74 samples in 2025/2025-26 (Nesine mostly left it out that season) |
| 1. Yarı Skoru | from 2022 |
| 2. Yarı KG | from 2024 |
| İki Yarı da 1,5 Üst | from 2024 |
| 1. Yarı / 2. Yarı KG | from 2025 |
| 12,5 Korner | rare |

A 2025/26 match has about 120–160 stored selections; a full season of all 26 leagues about 1.2 million rows.

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
| **market_type_id** | string | Nesine's id. Some types are one line each (goals O/U 1.5 = 11, 2.5 = 12, 3.5 = 13), some cover several lines (corners O/U 8.5/9.5/10.5 = 216) – the line is always in the odds row |
| market_key | string | English, without the line: `1X2`, `DC`, `OU`, `HT_OU`, `TEAM_OU_HOME`, `HT_FT`, `CORRECT_SCORE`, `1X2_AND_OU`, `CORNERS_OU`, … (one per entry of `config/markets.yaml`) |
| **name_tr** | string | Nesine's name; for a type covering several lines the line is removed (`Korner Alt/Üst`) |
| family | string | `result` \| `goals` \| `halves` \| `combo` \| `corners` (the spec's `handicap`, `cards`, `player`, `special` stay allowed but are not collected) |
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
| **selection_key** | string | `1` `X` `2` `OVER` `UNDER` `YES` `NO` `1X` `12` `X2`, HT/FT `1/X`, 1st half / 2nd half BTTS `YES/NO`, scores `2-1` / `OTHER` (Diğer), goal ranges `2-3` `6+`, combos `1&OVER` `X&YES` `UNDER&NO` |
| selection_name_tr | string | Nesine's text (e.g. `Üst`, `1 ve Alt`, `MS1 & Var`) |
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
| **status** | string | `settled` \| `void` (match postponed/cancelled/abandoned) \| `pending` \| `unsettleable` (`unverified` stays allowed but is not used: no card markets) |
| settle_basis | string | `official` \| `engine` (NULL when not settled) |
| **settled_at_utc** | ts | |

Settlement rules (`config/pipeline.yaml` → `settlement`):
- **Official:** every collected market except the ones below uses Nesine's winner marks. The engine still computes `hit_engine` as a cross-check: in the example it agreed on every selection where both exist.
- **Engine:** corners O/U (from the statistics page) and 2. Yarı KG (Nesine marks no winner there).
- **Unsettleable:** Belgium 2019/20 corner markets (no corner statistics for that season), and any selection whose data is missing (e.g. the statistics page failed every retry).

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
| fair_prob, market_margin | margin removed within the market. Only for complete markets (every selection priced); double chance is divided by 2 |
| hit, status | from settlements |
| in_default_analysis | false for `season_type = special` and anything not `settled` |

**Exports** (`exports/<season>/`):
- `oranlar_<season>.xlsx`: **one row per match with closing odds** (upcoming matches appear once their closing snapshot is taken) and one sheet per league. Columns: Tarih, Saat, Ev Sahibi, Deplasman, İY, MS, Korner, Sarı Kart, Kırmızı Kart, then the closing odds of the 45 markets in the order of `config/markets.yaml` (`MS 1`, `MS X`, `MS 2`, `ÇŞ 1-X`, …, `2,5 Alt`, `2,5 Üst`, …, `Skor 2-1`). **Winning odds are filled green.** About 380 rows × 130–170 columns per league.
- `<league_id>.csv.gz`: the full `analysis_flat` (one row per selection) for analysis tools.

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

`scripts/schema_example.py --date 2025-10-18 --league ENG-1 --limit 4` produced these rows from Mackolik. All quality checks were ok (0 fail, 0 warn).

**matches**

| match_id | iddaa_event_code | league_id | season | season_type | kickoff_utc | kickoff_local_tr | home_team_id | away_team_id | status | ht | ft | stadium |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1ul4lz9b1npclnmnufhedm7tg | 2367090 | ENG-1 | 2025/26 | regular | 2025-10-18 11:30:00+00 | 2025-10-18T14:30:00+03:00 | ENG-NOT_FOREST | ENG-CHELSEA | finished | 0-0 | 0-3 | The City Ground |

**odds + settlements** (Nottingham Forest – Chelsea, 0-0 / 0-3; `price_type` `closing_history`, `source` arsiv, `mbs` 1)

| market_type_id | market_key | line | selection_key | selection_name_tr | odds | hit_official | hit_engine | hit | status | settle_basis |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 1X2 | NULL | 1 | 1 | 2.80 | false | false | false | settled | official |
| 1 | 1X2 | NULL | 2 | 2 | 1.95 | true | true | true | settled | official |
| 12 | OU | 2.5 | OVER | Üst | 1.61 | true | true | true | settled | official |
| 343 | 1X2_AND_OU | 2.5 | 2&OVER | 2 ve Üst | 2.88 | true | true | true | settled | official |
| 5 | HT_FT | NULL | X/2 | X/2 | 5.11 | true | true | true | settled | official |
| 29 | TEAM_OU_AWAY | 1.5 | OVER | Üst | 1.84 | true | true | true | settled | official |
| 599 | 2H_BTTS | NULL | NO | Yok | 1.18 | NULL | true | true | settled | engine |
| 216 | CORNERS_OU | 9.5 | UNDER | Alt | 1.88 | NULL | true | true | settled | engine |

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

**oranlar_2025-26.xlsx**, sheet ENG-1 (first columns; winning odds are green in the file)

| Tarih | Saat | Ev Sahibi | Deplasman | İY | MS | Korner | Sarı Kart | Kırmızı Kart | MS 1 | MS X | MS 2 | … |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 18.10.2025 | 14:30 | Not. Forest | Chelsea | 0-0 | 0-3 | 7 | 5 | 1 | 2.80 | 3.09 | **1.95** | … |
| 18.10.2025 | 17:00 | Brighton | Newcastle | 1-0 | 2-1 | 12 | 1 | 0 | **2.53** | 3.05 | 2.13 | … |


## Decisions

Settled (2026-10-07):
- **Markets:** only the 45 in `config/markets.yaml`. No player bets, no card markets (Kart Puanı, Kırmızı Kart), no 1st-half corners.
- **Exports:** one row per match in `oranlar_<season>.xlsx` (one sheet per league, winners green); the full one-row-per-selection data as `<league_id>.csv.gz` per season.

Still open (my proposal is implemented; say if you want it different):
1. **Market-sum check (100–130 %).** Nesine's margin on some collected markets is higher:

   | Market | Margin |
   |---|---|
   | Combos (MS ve Alt/Üst, MS ve KG …) | ~32 % |
   | Double chance | ~32 % (after dividing by 2) |
   | İY/MS | ~32 % |
   | Correct scores | higher still |

   **Proposal:** 100–130 % for 2- and 3-way markets, up to 170 % for markets with more selections and for double chance. The check is a warning only and never blocks anything.
2. **Team English names:** Mackolik only has Turkish display names. **Proposal:** `name_en` stays NULL unless you fill `config/teams_en.yaml` yourself.
3. **runs.job values:** settlement and export run inside the results workflow and are logged as `results` with a note.

How the spec is applied:
- the season is written `2024-25` in folder names;
- `captured_at_utc` is NULL for `closing_history`;
- `round` holds Mackolik's stage name;
- `referee` is NULL in history.

## Status

The daily jobs write these tables since PR "Daily collection on SCHEMA.md". The odds snapshots collected before
(2026-10-06 →) were converted once (26 leagues, 45 markets; `src/odds_analysis/migrate.py`); the old CSV tables were
removed (git history keeps them). The backfill writes these tables from its first run.
