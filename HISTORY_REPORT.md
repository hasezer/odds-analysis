# History investigation – Nesine odds from the new mackolik.com backend

Scope: the 26 leagues in `config/leagues.yaml` (regular season + their own playoff / relegation-playoff stages,
no cups). Everything below was measured from Mackolik only (new www.mackolik.com backend + arsiv.mackolik.com),
at ≤ 1 request/second, read-only. **No backfill was run.**

## Decisions (2026-10-07)

| Topic | Decision |
|---|---|
| New site vs arsiv | **Use both.** www.mackolik.com: match lists, scores, events, statistics, history, and checking that the odds popup belongs to the right match. arsiv: pre-match snapshots (opening odds and movement). |
| Odds movement | Analyses of odds movement use **only our own snapshots**. Every analysis states the date range of its data. |
| Japan "J1 100 Year Vision League" (spring 2026) | Data kept, `season_type = special`, excluded from default analyses. |
| Card points (Kart Puanı) | Still unverified: card markets stay **excluded from analysis** until Nesine's rule is confirmed. |
| Belgium 2019/20 (no corner statistics) | Corner markets of that season are `unsettleable`. |
| Backfill | Full history (Aug 2019 → now) for the 26 leagues, newest season first, 1 request/second. Starts only after the SCHEMA.md PR is approved. |
| Actions budget | `monthly_minutes` (2,000 now; 3,000 with GitHub Student Pro) and `daily_reserve` (900) as config values. The backfill pauses when the minutes left drop below the reserve; the reserve is updated after a week of measured daily usage. |

## TL;DR

1. **There is history, back to August 2019.** The new mackolik.com backend keeps every past match with its iddaa
   (Nesine) event code from **2019-08-01** onwards. With that code the old arsiv odds popup still returns the
   **full Nesine market list with the winners marked** for matches 7 years old. Before August 2019: nothing
   (0 iddaa codes in 2014–2018 samples).
2. **Geo test: no blocking.** From a US IP the servers returned the same full odds as from Turkey. Nothing was
   bypassed.
3. **The historical price is the final pre-kickoff price** (one price per selection: no opening price, no
   movement). Opening odds and line movement exist only from our own snapshots.
4. **All 26 leagues have Nesine odds from their 2019/20 (or 2019) season onwards**, for 96–100 % of their
   matches, with goals/cards events and corners for every sampled match (one gap: Belgium 2019/20 corners).
5. **A full backfill is about 63,600 matches, ~54 hours at 1 request/second (~67 h with real response times),
   ~3.5 GB transferred and ~22 MB of Parquet.** Newest season first, it fits in **about 4 months** of the free
   2,000 Actions minutes (next to the daily jobs); the last 2 seasons alone take 1 month.
6. **Recommendation: complement, don't replace.** Keep the arsiv program list + popup for pre-match snapshots
   (opening/movement). Use the new backend for the match list, scores, events, corners/cards and history.

## 1. New mackolik.com endpoints

All JSON unless stated. `<uuid>` is the 25-character Perform/Opta match id used everywhere on the new site.

| What | Endpoint | Notes |
|---|---|---|
| All matches of a date | `/perform/p0/ajax/components/competition/livescores/json?sports[]=Soccer&matchDate=YYYY-MM-DD` | competitions (id, name, country, code, stages) + matches (uuid, slug, kickoff UTC, competition/stage, state, FT/HT score, red cards, **`iddaaCode`**). ~166 KB compressed, ~7 s |
| Season fixtures | `/puan-durumu/<slug>/<YYYY-YYYY or YYYY>/fikstur/<competition_id>` (HTML) | every match of a season incl. playoff stages (uuid, round/stage name, scores). ~3 MB, ~5 s. Needs the real slug (in `config/leagues.yaml`) |
| Odds | `/ajax/iddaa/outcomes/soccer/all/<uuid>` | markets → outcomes (price, label, iddaa market code, `mbc` = MBS). **Empty for some matches** (often Bundesliga) whose arsiv popup is complete |
| Market names | `/ajax/iddaa/markets/soccer/all/<uuid>?template=all` (HTML) | market titles + Nesine deep link `iddaa/detail/<code>` |
| Key events | `/ajax/football/key-events?ajaxViewName=events&matchId=<uuid>` | goals (score, scorer, assist), yellow/red cards, substitutions, minutes like `90 +5`. ~1.5 KB |
| Statistics | `/mac/<slug>/istatistik/<uuid>` (HTML, server-rendered) | Korner, Sarı Kart, Faul, Şut, xG… ~37 KB. `/mac/x/istatistik/<uuid>` redirects (301) to the real slug |
| Match header | `/perform/p0/ajax/components/match/matchHeader` | teams, score, status |
| gameStats ajax | – | returns 502; not usable |

**uuid ↔ arsiv popup.** The arsiv popup (`IddaaHandler.aspx?command=oddspopup&e=<iddaa code>`) returns a `uuid`
field. For historical codes taken from the date listing it was **the same match in 50 of 60 samples, never a
different match** (7 transient HTTP 500/502, 3 empty). In the larger per-league run it resolved to an older
match for 2 of ~400 checked matches (both 2026). So the popup is always validated by uuid; for the rare miss the
new-site odds JSON still has the prices (47 and 50 markets in those two cases) and the engine settles them from
the score. The same check fixes the "popup resolved to an old match" problem the daily pipeline currently works
around with `morebets`.

## 2. Geo test

From a US IP (Google cloud, AS396982) every endpoint above returned HTTP 200 with the same full Nesine odds as
from Turkey. No geo headers, no captcha, no redirect. The site's frontend calls `geolocation.daznservices.com`,
but the country is only used for analytics. **Nothing was bypassed**; GitHub's US runners work as they are.

## 3. What the history contains

- **Oldest date with odds: 2019-08-01.** iddaa codes appear in the date listing from that day (thin until
  ~September 2019). 2014–2018 samples: 0 matches with a code.
- **Winners marked – for goal/result markets only.** Example: Sunderland–Wolverhampton (2025-10-18), 79 markets,
  51 with a highlighted winner. The 28 without marks are all corner, card (incl. Kart Puanı), red card, penalty,
  "İlk Gol", "2. Yarı Karşılıklı Gol" and player/special markets. Corners and cards are settled by our engine from
  the statistics page (as today). Goal-scorer markets could be settled from key events; player shots/assists
  cannot (Mackolik has no per-player shot data) and stay unsettled.
- **MBS** (minimum bet count) is present on every selection (1 for top leagues, 2–3 for small leagues).
- **Price type:** one price per selection = the **last pre-kickoff price** (our own "closing" snapshot is taken
  ~40 minutes earlier and sometimes differs by a tick). No opening price, no live prices.

**How the market list grew** (popup; top-5 leagues + Süper Lig medians from the per-league table; "first seen" =
first season a market type appears in any sample of the 26 leagues):

| Season | Markets per top match | Market types first seen |
|---|---|---|
| 2019/20 | 34–37 | the base set: 1X2, double chance, O/U 0.5–5.5 (full time, 1st half, home, away), HT/FT, half results, handicaps, correct score, total goals range, BTTS, odd/even, first goal, "Ev Sahibi/Deplasman Gol Yemez", "Gol Atacak Takımlar", corner ranges, first corner |
| 2020/21 | 40–43 | corner O/U, most corners, red card |
| 2021/22 | 39–43 | win both halves, half with more goals per team, winning margin |
| 2022/23 | 46–58 | 1st-half BTTS / score / combos, 1X2 & BTTS, O/U & BTTS, **Kart Puanı O/U** |
| 2023/24 | 58–59 | win to nil, 1st-half odd/even, corner odd/even, HT/FT score |
| 2024/25 | 65–73 | 2nd-half BTTS, more card points, penalty |
| 2025/26 | 70–90 | **player markets** (scorer, shots, assists, cards, fouls…) and team stats (shots, fouls, offsides, throw-ins, goal kicks) |
| 2026/27 | 84–92 | more player combos (goal or assist, hat-trick), goalkeeper saves |

Smaller leagues follow the same steps with fewer markets (≈ 30 in 2019/20, 50–75 in 2025/26).

The new-site odds JSON shows fewer markets (≈ 50 in 2025) than the popup. Three old market names are not in
`config/` yet: "Deplasman Gol Yemez", "Ev Sahibi Gol Yemez", "Gol Atacak Takımlar" (they would be logged as
unmapped, never guessed).

## 4. Per league (26 leagues)

How this was measured (`scripts/history_coverage.py`): for every league and season, the season fixture page
(all matches incl. playoffs), then the date listing of the season's busiest mid-season matchday from September
2019 on (share of the league's matches with an iddaa code = "offered on Nesine"), then 2–3 of those matches:
arsiv popup (must be the same uuid), key events and statistics page. Market counts and the events/corners/cards
columns also include 1–2 random matches per season from `scripts/history_leagues.py` (first 10 leagues).

Read the numbers as indications: each season has only 2–5 sampled matches.
- A median under ~25 (e.g. Saudi 2025/26: 29, Belgium 2023/24: 23, Austria/Denmark 2021/22: 19) comes from a
  matchday where Nesine offered a reduced list for those matches; other matches of the same season have the full
  list. 2019 values of 16–18 are the thin first weeks of the history.
- Events/corners/cards count only pages that loaded: 4 statistics pages failed with a transient HTTP 502 during
  the probe and returned the numbers on retry. The only real gap found: **Belgium 2019/20 has no statistics
  page data** (no corners in 2 of 2 sampled matches; cards still come from key events). A match without yellow cards has no "Sarı Kart" row (= 0); key events
  list every card, so cards are known for every sampled match.

Season labels: calendar-year leagues (Norway, MLS, Brazil, Japan, Argentina) use "2024"; the others "2024/25".
Japan's J1 moves to an autumn–spring calendar from 2026 ("2026/27"). In spring 2026 the J1 clubs played a
one-off transition league, "J1 100 Year Vision League" (own competition id, in `config/leagues.yaml` as
`extra`); it is the Japan "2026" season below. Decision: keep the data as `season_type = special`, excluded from
default analyses.

### Summary per league

| League | First season with Nesine odds | Listed with odds (sampled matchday) | Markets per match by season (popup, median) | Events | Corners | Cards (stats page) |
|---|---|---|---|---|---|---|
| Netherlands Eerste Divisie | 2019/20 | 100% | 2019/20: 32 · 2020/21: 32 · 2021/22: 32 · 2022/23: 46 · 2023/24: 46 · 2024/25: 50 · 2025/26: 49 · 2026/27: 54 | 100% | 100% | 100% |
| Germany 2. Bundesliga | 2019/20 | 100% | 2019/20: 32 · 2020/21: 31 · 2021/22: 32 · 2022/23: 55 · 2023/24: 60 · 2024/25: 65 · 2025/26: 45 · 2026/27: 45 | 100% | 100% | 100% |
| Norway Eliteserien | 2019 | 100% | 2019: 18 · 2020: 30 · 2021: 32 · 2022: 32 · 2023: 44 · 2024: 60 · 2025: 63 · 2026: 66 | 100% | 100% | 100% |
| Netherlands Eredivisie | 2019/20 | 100% | 2019/20: 18 · 2020/21: 32 · 2021/22: 32 · 2022/23: 54 · 2023/24: 55 · 2024/25: 68 · 2025/26: 74 · 2026/27: 75 | 100% | 100% | 100% |
| Spain La Liga 2 | 2019/20 | 100% | 2019/20: 29 · 2020/21: 30 · 2021/22: 31 · 2022/23: 55 · 2023/24: 56 · 2024/25: 66 · 2025/26: 68 · 2026/27: 75 | 100% | 100% | 100% |
| Argentina Liga Profesional | 2019 | 96% | 2019: 18 · 2020: 31 · 2021: 31 · 2022: 20 · 2023: 52 · 2024: 50 · 2025: 60 · 2026: 71 | 100% | 100% | 100% |
| France Ligue 2 | 2019/20 | 100% | 2019/20: 29 · 2020/21: 32 · 2021/22: 32 · 2022/23: 39 · 2023/24: 46 · 2024/25: 54 · 2025/26: 54 · 2026/27: 59 | 100% | 100% | 100% |
| Italy Serie B | 2019/20 | 100% | 2019/20: 30 · 2020/21: 32 · 2021/22: 32 · 2022/23: 59 · 2023/24: 58 · 2024/25: 66 · 2025/26: 70 · 2026/27: 70 | 100% | 100% | 100% |
| Brazil Serie A | 2019 | 100% | 2019: 31 · 2020: 33 · 2021: 33 · 2022: 48 · 2023: 52 · 2024: 54 · 2025: 70 · 2026: 81 | 100% | 100% | 100% |
| Germany Bundesliga | 2019/20 | 100% | 2019/20: 37 · 2020/21: 41 · 2021/22: 43 · 2022/23: 48 · 2023/24: 59 · 2024/25: 71 · 2025/26: 90 · 2026/27: 88 | 100% | 100% | 100% |
| Switzerland Super League | 2019/20 | 100% | 2019/20: 30 · 2020/21: 32 · 2021/22: 32 · 2022/23: 39 · 2023/24: 46 · 2024/25: 63 · 2025/26: 61 · 2026/27: 66 | 100% | 100% | 100% |
| Belgium Jupiler Pro League | 2019/20 | 100% | 2019/20: 30 · 2020/21: 32 · 2021/22: 38 · 2022/23: 45 · 2023/24: 23 · 2024/25: 70 · 2025/26: 72 · 2026/27: 72 | 100% | 88% | 100% |
| USA MLS | 2019 | 100% | 2019: 18 · 2020: 30 · 2021: 32 · 2022: 38 · 2023: 51 · 2024: 49 · 2025: 72 · 2026: 76 | 100% | 100% | 100% |
| England Premier League | 2019/20 | 100% | 2019/20: 34 · 2020/21: 41 · 2021/22: 40 · 2022/23: 55 · 2023/24: 58 · 2024/25: 71 · 2025/26: 86 · 2026/27: 88 | 100% | 100% | 100% |
| Turkey Süper Lig | 2019/20 | 100% | 2019/20: 34 · 2020/21: 32 · 2021/22: 40 · 2022/23: 54 · 2023/24: 56 · 2024/25: 65 · 2025/26: 70 · 2026/27: 84 | 100% | 100% | 100% |
| England Championship | 2019/20 | 100% | 2019/20: 30 · 2020/21: 32 · 2021/22: 32 · 2022/23: 46 · 2023/24: 58 · 2024/25: 69 · 2025/26: 74 · 2026/27: 76 | 100% | 100% | 100% |
| Austria Bundesliga | 2019/20 | 100% | 2019/20: 30 · 2020/21: 32 · 2021/22: 19 · 2022/23: 55 · 2023/24: 58 · 2024/25: 62 · 2025/26: 64 · 2026/27: 66 | 100% | 100% | 100% |
| Denmark Superliga | 2019/20 | 100% | 2019/20: 30 · 2020/21: 32 · 2021/22: 19 · 2022/23: 46 · 2023/24: 44 · 2024/25: 64 · 2025/26: 64 · 2026/27: 66 | 100% | 100% | 100% |
| Scotland Premiership | 2019/20 | 100% | 2019/20: 30 · 2020/21: 32 · 2021/22: 32 · 2022/23: 46 · 2023/24: 46 · 2024/25: 50 · 2025/26: 52 · 2026/27: 54 | 100% | 100% | 100% |
| Portugal Primeira Liga | 2019/20 | 100% | 2019/20: 32 · 2020/21: 32 · 2021/22: 31 · 2022/23: 55 · 2023/24: 58 · 2024/25: 66 · 2025/26: 60 · 2026/27: 76 | 100% | 100% | 100% |
| Spain La Liga | 2019/20 | 100% | 2019/20: 34 · 2020/21: 43 · 2021/22: 39 · 2022/23: 55 · 2023/24: 59 · 2024/25: 70 · 2025/26: 76 · 2026/27: 92 | 100% | 100% | 100% |
| Italy Serie A | 2019/20 | 98% | 2019/20: 36 · 2020/21: 40 · 2021/22: 40 · 2022/23: 58 · 2023/24: 58 · 2024/25: 73 · 2025/26: 80 · 2026/27: 88 | 100% | 100% | 100% |
| France Ligue 1 | 2019/20 | 100% | 2019/20: 34 · 2020/21: 41 · 2021/22: 43 · 2022/23: 46 · 2023/24: 58 · 2024/25: 68 · 2025/26: 77 · 2026/27: 88 | 100% | 100% | 100% |
| Mexico Liga MX | 2019/20 | 100% | 2019/20: 30 · 2020/21: 24 · 2021/22: 32 · 2022/23: 38 · 2023/24: 36 · 2024/25: 37 · 2025/26: 44 · 2026/27: 52 | 100% | 100% | 100% |
| Saudi Pro League | 2019/20 | 97% | 2019/20: 16 · 2020/21: 31 · 2021/22: 31 · 2022/23: 44 · 2023/24: 52 · 2024/25: 48 · 2025/26: 29 · 2026/27: 52 | 100% | 100% | 100% |
| Japan J1 League | 2019 | 100% | 2019: 30 · 2020: 30 · 2021: 33 · 2022: 36 · 2023: 46 · 2024: 60 · 2025: 66 · 2026: 52 · 2026/27: 70 | 100% | 100% | 100% |

<details><summary>Matches per season (fixture pages; playoff stages included)</summary>

| League | Season | Matches (incl. not yet played) | Est. matches with Nesine odds, played by 2026-10-07 | Extra stages |
|---|---|---|---|---|
| Netherlands Eerste Divisie | 2019/20 | 290 | 290 | – |
| Netherlands Eerste Divisie | 2020/21 | 380 | 380 | – |
| Netherlands Eerste Divisie | 2021/22 | 380 | 380 | – |
| Netherlands Eerste Divisie | 2022/23 | 380 | 380 | – |
| Netherlands Eerste Divisie | 2023/24 | 392 | 392 | Play-off 1. Tur (6), Play-off 2. Tur (4), Yükselme Play-off - Final (2) |
| Netherlands Eerste Divisie | 2024/25 | 380 | 380 | – |
| Netherlands Eerste Divisie | 2025/26 | 380 | 380 | – |
| Netherlands Eerste Divisie | 2026/27 | 90 | 90 | – |
| Germany 2. Bundesliga | 2019/20 | 306 | 297 | – |
| Germany 2. Bundesliga | 2020/21 | 306 | 306 | – |
| Germany 2. Bundesliga | 2021/22 | 306 | 306 | – |
| Germany 2. Bundesliga | 2022/23 | 306 | 306 | – |
| Germany 2. Bundesliga | 2023/24 | 308 | 308 | Play- out Final (2) |
| Germany 2. Bundesliga | 2024/25 | 306 | 306 | – |
| Germany 2. Bundesliga | 2025/26 | 306 | 306 | – |
| Germany 2. Bundesliga | 2026/27 | 54 | 54 | – |
| Norway Eliteserien | 2019 | 240 | 121 | – |
| Norway Eliteserien | 2020 | 240 | 240 | – |
| Norway Eliteserien | 2021 | 240 | 240 | – |
| Norway Eliteserien | 2022 | 240 | 240 | – |
| Norway Eliteserien | 2023 | 240 | 240 | – |
| Norway Eliteserien | 2024 | 240 | 240 | – |
| Norway Eliteserien | 2025 | 239 | 239 | – |
| Norway Eliteserien | 2026 | 168 | 168 | – |
| Netherlands Eredivisie | 2019/20 | 232 | 232 | – |
| Netherlands Eredivisie | 2020/21 | 309 | 309 | Avrupa Ligi Play-off - Yarı Final (2), Avrupa Ligi Play-off - Final (1) |
| Netherlands Eredivisie | 2021/22 | 312 | 312 | Avrupa Ligi Play-off - Yarı Final (4), Avrupa Ligi Play-off - Final (2) |
| Netherlands Eredivisie | 2022/23 | 312 | 312 | Avrupa Ligi Play-off - Yarı Final (4), Avrupa Ligi Play-off - Final (2) |
| Netherlands Eredivisie | 2023/24 | 309 | 309 | Konferans Ligi Play-off - Yarı Final (2), Konferans Ligi Play-off - Final (1) |
| Netherlands Eredivisie | 2024/25 | 309 | 309 | Konferans Ligi Play-off - Yarı Final (2), Konferans Ligi Play-off - Final (1) |
| Netherlands Eredivisie | 2025/26 | 309 | 309 | Konferans Ligi Play-off - Yarı Final (2), Konferans Ligi Play-off - Final (1) |
| Netherlands Eredivisie | 2026/27 | 63 | 63 | – |
| Spain La Liga 2 | 2019/20 | 468 | 468 | Yükselme Playoff Yarı Final (4), Yükselme Playoffları - Finaller (2) |
| Spain La Liga 2 | 2020/21 | 467 | 467 | Yükselme Play-off - Yarı Final (4), Yükselme Play-off - Finaller (2) |
| Spain La Liga 2 | 2021/22 | 468 | 468 | Yükselme Play-off - Yarı Final (4), Yükselme Play-off - Final (2) |
| Spain La Liga 2 | 2022/23 | 468 | 468 | Yükselme Play-off - Yarı Final (4), Yükselme Play-off - Final (2) |
| Spain La Liga 2 | 2023/24 | 468 | 468 | Yükselme Play-off - Yarı Final (4), Yükselme Play-off - Final (2) |
| Spain La Liga 2 | 2024/25 | 468 | 468 | Yükselme Play-off - Yarı Final (4), Yükselme Play-off - Final (2) |
| Spain La Liga 2 | 2025/26 | 468 | 468 | Yükselme Play-off - Yarı Final (4), Yükselme Play-off - Final (2) |
| Spain La Liga 2 | 2026/27 | 88 | 88 | – |
| Argentina Liga Profesional | 2019 | 276 | 176 | – |
| Argentina Liga Profesional | 2020 | 135 | 135 | Alt Tablo Turu (30), Şampiyona Grubu (30), Plate - Final (1), Şampiyona Final (1), Sudamericana Kupası Play-Off Final (1) |
| Argentina Liga Profesional | 2021 | 501 | 501 | Birinci Aşama - Çeyrek Final (4), Birinci Aşama - Yarı Final (2), Birinci Aşama - Final (1), 2. Aşama (325) |
| Argentina Liga Profesional | 2022 | 581 | 581 | Birinci Aşama Çeyrek Final (4), 1. Tur - Yarı Final (2), 1. Aşama - Final (1) |
| Argentina Liga Profesional | 2023 | 582 | 582 | 2. Aşama (196), Küme Düşme Play-off (1), 2. Tur - Çeyrek Final (4), 2. Tur Yarı Finaller (2), 2. Tur Finali (1) |
| Argentina Liga Profesional | 2024 | 581 | 581 | 1. Aşama - Çeyrek Final (4), 1. Tur Yarı Finalleri (2), 1. Tur Finali (1) |
| Argentina Liga Profesional | 2025 | 510 | 510 | 1. Tur - Son 16 Turu (8), 1. Aşama - Çeyrek Final (4), 1. Tur Yarı Finalleri (2), 1. Tur Finali (1), 2. Tur - Son 16 Turu (8), 2. Aşama - Çeyrek Final (4), 2. Tur Yarı Finaller (2), 2. Tur Final (1) |
| Argentina Liga Profesional | 2026 | 419 | 419 | 1. Aşama - Son 16 Turu (8), 1. Aşama - Çeyrek Final (4), 1. Tur Yarı Finaller (2), 1. Tur - Final (1) |
| France Ligue 2 | 2019/20 | 280 | 270 | – |
| France Ligue 2 | 2020/21 | 381 | 381 | Yükselme Playofflar (1), Yükselme Play-off - 2. Tur (1) |
| France Ligue 2 | 2021/22 | 381 | 381 | Yükselme Play-off - 1. Tur (1), Yükselme Play-off - 2. Tur (1) |
| France Ligue 2 | 2022/23 | 379 | 379 | – |
| France Ligue 2 | 2023/24 | 381 | 381 | Yükselme Play-off - 1. Tur (1), Yükselme Play-off - Final (1) |
| France Ligue 2 | 2024/25 | 308 | 308 | Yükselme Play-off - 1. Tur (1), Yükselme Play-off Final (1) |
| France Ligue 2 | 2025/26 | 306 | 306 | Yükselme Play-off - 1. Tur (1), Yükselme Play-off - Final (1) |
| France Ligue 2 | 2026/27 | 63 | 63 | – |
| Italy Serie B | 2019/20 | 390 | 390 | Play-off - Eleme Turu (2), Yükselme Playoff Yarı Final (4), Küme Düşme Play-off Final (2), Yükselme Playoffları - Finaller (2) |
| Italy Serie B | 2020/21 | 387 | 387 | Play-off - Eleme Turu (2), Yükselme Play-off - Yarı Final (4), Yükselme Play-off - Finaller (2) |
| Italy Serie B | 2021/22 | 390 | 390 | Küme Düşme Play-off - Final (2), Yükselme Play-off - Eleme Turu (2), Yükselme Play-off - Yarı Final (4), Yükselme Play-off - Final (2) |
| Italy Serie B | 2022/23 | 389 | 389 | Küme Düşme Play-off - Final (2), Yükselme Play-off - Eleme Turu (1), Yükselme Play-off - Yarı Final (4), Yükselme Play-off - Final (2) |
| Italy Serie B | 2023/24 | 390 | 390 | Küme Düşme Play-off - Final (2), Yükselme Play-off - Eleme Turu (2), Yükselme Play-off - Yarı Final (4), Yükselme Play-off - Final (2) |
| Italy Serie B | 2024/25 | 388 | 388 | Yükselme Play-off - Eleme Turu (2), Yükselme Play-off Yarı Final (4), Yükselme Play-off - Final (2), Küme Düşme - Final (1) |
| Italy Serie B | 2025/26 | 390 | 390 | Yükselme Play-off - Eleme Turu (2), Küme Düşme - Final (2), Yükselme Play-Off - Yarı Final (4), Yükselme Play-off - Final (2) |
| Italy Serie B | 2026/27 | 50 | 50 | – |
| Brazil Serie A | 2019 | 380 | 261 | – |
| Brazil Serie A | 2020 | 380 | 380 | – |
| Brazil Serie A | 2021 | 380 | 380 | – |
| Brazil Serie A | 2022 | 380 | 380 | – |
| Brazil Serie A | 2023 | 380 | 380 | – |
| Brazil Serie A | 2024 | 380 | 380 | – |
| Brazil Serie A | 2025 | 380 | 380 | – |
| Brazil Serie A | 2026 | 279 | 279 | – |
| Germany Bundesliga | 2019/20 | 306 | 306 | – |
| Germany Bundesliga | 2020/21 | 306 | 306 | – |
| Germany Bundesliga | 2021/22 | 305 | 305 | – |
| Germany Bundesliga | 2022/23 | 306 | 306 | – |
| Germany Bundesliga | 2023/24 | 308 | 308 | Play-out Final (2) |
| Germany Bundesliga | 2024/25 | 305 | 305 | – |
| Germany Bundesliga | 2025/26 | 306 | 306 | – |
| Germany Bundesliga | 2026/27 | 36 | 36 | – |
| Switzerland Super League | 2019/20 | 180 | 170 | – |
| Switzerland Super League | 2020/21 | 180 | 180 | – |
| Switzerland Super League | 2021/22 | 180 | 180 | – |
| Switzerland Super League | 2022/23 | 179 | 179 | – |
| Switzerland Super League | 2023/24 | 228 | 228 | Şampiyona Grubu (15), Küme Düşme Grubu (15) |
| Switzerland Super League | 2024/25 | 228 | 228 | Şampiyona Grubu (15), Küme Düşme Grubu (15) |
| Switzerland Super League | 2025/26 | 228 | 228 | Şampiyona Grubu (15), Küme Düşme Grubu (15) |
| Switzerland Super League | 2026/27 | 54 | 54 | – |
| Belgium Jupiler Pro League | 2019/20 | 232 | 224 | – |
| Belgium Jupiler Pro League | 2020/21 | 330 | 330 | Şampiyona Grubu (12), Konferans Ligi Play-off Grubu (12) |
| Belgium Jupiler Pro League | 2021/22 | 328 | 328 | Konferans Ligi Play-off Grubu (12), Şampiyona Grubu (12) |
| Belgium Jupiler Pro League | 2022/23 | 328 | 328 | Konferans Ligi Play-off Grubu (12), Şampiyona Grubu (12) |
| Belgium Jupiler Pro League | 2023/24 | 314 | 314 | Konferans Ligi Play-off Grubu (29), Şampiyonluk Grubu (30), Küme Düşme Grubu (12), Play-out (2), Konferans Ligi Play-off - Final (1) |
| Belgium Jupiler Pro League | 2024/25 | 312 | 312 | Konferans Ligi Play-off Grubu (30), Şampiyona Grubu (30), Küme Düşme Grubu (12), Konferans Ligi Play-off - Final (1) |
| Belgium Jupiler Pro League | 2025/26 | 313 | 313 | Konferans Ligi Play-off Grubu (30), Şampiyona Grubu (30), Küme Düşme Grubu (12), Konferans Ligi Play-off - Final (1) |
| Belgium Jupiler Pro League | 2026/27 | 63 | 63 | – |
| USA MLS | 2019 | 421 | 149 | Play-In Turu (6), MLS Kupası - Konferans Yarı Final (4), MLS Kupası - Konferans Final (2), MLS Kupası Final (1) |
| USA MLS | 2020 | 324 | 324 | Grup Aşaması (36), Son 16 Turu (8), Çeyrek Final (4), Yarı Final (2), Final (1), Play-In Turu (2), MLS Cup - Conference Quarter-finals (8), MLS Kupası - Konferans Yarı Final (4), MLS Kupası - Konferans Final (2), MLS Kupası Final (1) |
| USA MLS | 2021 | 472 | 472 | Play-In Turu (6), Kupası - Konferans Yarı Final (4), MLS Kupası - Konferans Final (2), Kupası Final (1) |
| USA MLS | 2022 | 489 | 489 | Kupa - 1. Tur (6), Kupası - Konferans Yarı Final (4), Kupası - Konferans Finaller (2), MLS Kupası Final (1) |
| USA MLS | 2023 | 521 | 521 | Play-In Turu (2), Kupa - 1. Tur (19), Kupa - Konferans Yarı Finaller (4), Kupa - Konferans Finaller (2), Kupa - Final (1) |
| USA MLS | 2024 | 522 | 522 | Play-In Turu (2), Kupa - 1. Tur (20), Kupa - Konferans Yarı Final (4), Kupa - Konferans Finalleri (2), Kupa - Final (1) |
| USA MLS | 2025 | 540 | 540 | Play-In Turu (2), Kupa - 1. Tur (21), MLS Kupası - Konferans Yarı Final (4), Kupa - Konferans Finalleri (2), Kupa - Final (1) |
| USA MLS | 2026 | 405 | 404 | – |
| England Premier League | 2019/20 | 380 | 380 | – |
| England Premier League | 2020/21 | 380 | 380 | – |
| England Premier League | 2021/22 | 380 | 380 | – |
| England Premier League | 2022/23 | 380 | 380 | – |
| England Premier League | 2023/24 | 380 | 380 | – |
| England Premier League | 2024/25 | 380 | 380 | – |
| England Premier League | 2025/26 | 380 | 380 | – |
| England Premier League | 2026/27 | 50 | 50 | – |
| Turkey Süper Lig | 2019/20 | 306 | 306 | – |
| Turkey Süper Lig | 2020/21 | 420 | 420 | – |
| Turkey Süper Lig | 2021/22 | 380 | 380 | – |
| Turkey Süper Lig | 2022/23 | 313 | 313 | – |
| Turkey Süper Lig | 2023/24 | 379 | 379 | – |
| Turkey Süper Lig | 2024/25 | 341 | 341 | – |
| Turkey Süper Lig | 2025/26 | 306 | 306 | – |
| Turkey Süper Lig | 2026/27 | 54 | 54 | – |
| England Championship | 2019/20 | 557 | 557 | Yükselme Playoff Yarı Final (4), Yükselme Playofflar Final (1) |
| England Championship | 2020/21 | 557 | 557 | Yükselme Play-off - Yarı Final (4), Yükselme Playofflar Final (1) |
| England Championship | 2021/22 | 557 | 557 | Yükselme Play-off - Yarı Final (4), Yükselme Play-off - Final (1) |
| England Championship | 2022/23 | 557 | 557 | Yükselme Play-off Yarı Final (4), Yükselme Play-off Final (1) |
| England Championship | 2023/24 | 557 | 557 | Yükselme Play-off - Yarı Final (4), Yükselme Play-off - Final (1) |
| England Championship | 2024/25 | 557 | 557 | Yükselme Play-off - Yarı Final (4), Yükselme Play-off - Final (1) |
| England Championship | 2025/26 | 557 | 557 | Yükselme Play-off - Yarı Final (4), Yükselme Play-off - Final (1) |
| England Championship | 2026/27 | 95 | 95 | – |
| Austria Bundesliga | 2019/20 | 195 | 189 | Küme Düşme Grubu (30), Şampiyona Grubu (30), Avrupa Ligi Play-off - 1.Tur (1), Avrupa Ligi Play-off - Final (2) |
| Austria Bundesliga | 2020/21 | 195 | 195 | Küme Düşme Grubu (30), Şampiyona Grubu (30), Avrupa Ligi Play-off - 1.Tur (1), Konferans Ligi Play-off - Final (2) |
| Austria Bundesliga | 2021/22 | 195 | 195 | Küme Düşme Grubu (30), Şampiyona Grubu (30), Konferans Ligi Play-off - 1. Tur (1), Konferans Ligi Play-off - Final (2) |
| Austria Bundesliga | 2022/23 | 195 | 195 | Küme Düşme Grubu (30), Şampiyona Grubu (30), Konferans Ligi Play-off - 1. Tur (1), Konferans Ligi Play-off - Final (2) |
| Austria Bundesliga | 2023/24 | 195 | 195 | Şampiyona Grubu (30), Küme Düşme Grubu (30), Konferans Ligi Play-off - 1. Tur (1), Konferans Ligi Play-off - Final (2) |
| Austria Bundesliga | 2024/25 | 195 | 195 | Küme Düşme Grubu (30), Şampiyona Grubu (30), Konferans Ligi Play-off - 1. Tur (1), Konferans Ligi Play-off - Final (2) |
| Austria Bundesliga | 2025/26 | 195 | 195 | Şampiyona Grubu (30), Küme Düşme Grubu (30), Konferans Ligi Play-off - 1. Tur (1), Konferans Ligi Play-off - Final (2) |
| Austria Bundesliga | 2026/27 | 132 | 42 | – |
| Denmark Superliga | 2019/20 | 243 | 222 | Küme Düşme Grubu (24), Şampiyona Grubu (30), Avrupa Ligi Play-off - Çeyrek Final (2), Küme Düşme Play-off - Final (2), Avrupa Ligi Playoff- Yarı Final (2), Avrupa Ligi Play-off - Final (1) |
| Denmark Superliga | 2020/21 | 193 | 193 | Küme Düşme Grubu (30), Şampiyona Grubu (30), Conference League Play-offs - Final (1) |
| Denmark Superliga | 2021/22 | 193 | 193 | Küme Düşme Grubu (30), Şampiyona Grubu (30), Konferans Ligi Play-off - Final (1) |
| Denmark Superliga | 2022/23 | 193 | 193 | Küme Düşme Grubu (30), Şampiyona Grubu (30), Konferans Ligi Play-off- Final (1) |
| Denmark Superliga | 2023/24 | 193 | 193 | Küme Düşme Grubu (30), Şampiyona Grubu (30), Konferans Ligi Play-off - Final (1) |
| Denmark Superliga | 2024/25 | 193 | 193 | Küme Düşme Grubu (30), Şampiyona Grubu (30), Konferans Ligi Play-off - Final (1) |
| Denmark Superliga | 2025/26 | 193 | 193 | Küme Düşme Grubu (30), Şampiyona Grubu (30), Konferans Ligi Play-off - Final (1) |
| Denmark Superliga | 2026/27 | 132 | 54 | – |
| Scotland Premiership | 2019/20 | 198 | 198 | – |
| Scotland Premiership | 2020/21 | 228 | 228 | – |
| Scotland Premiership | 2021/22 | 228 | 228 | – |
| Scotland Premiership | 2022/23 | 228 | 228 | – |
| Scotland Premiership | 2023/24 | 234 | 234 | Play-out Çeyrek Final (2), Play-out Yarı Final (2), Play-out Final (2) |
| Scotland Premiership | 2024/25 | 228 | 228 | – |
| Scotland Premiership | 2025/26 | 228 | 228 | – |
| Scotland Premiership | 2026/27 | 198 | 42 | – |
| Portugal Primeira Liga | 2019/20 | 306 | 306 | – |
| Portugal Primeira Liga | 2020/21 | 306 | 306 | – |
| Portugal Primeira Liga | 2021/22 | 306 | 306 | – |
| Portugal Primeira Liga | 2022/23 | 306 | 306 | – |
| Portugal Primeira Liga | 2023/24 | 308 | 308 | Play-out Final (2) |
| Portugal Primeira Liga | 2024/25 | 306 | 306 | – |
| Portugal Primeira Liga | 2025/26 | 306 | 306 | – |
| Portugal Primeira Liga | 2026/27 | 306 | 62 | – |
| Spain La Liga | 2019/20 | 380 | 380 | – |
| Spain La Liga | 2020/21 | 380 | 380 | – |
| Spain La Liga | 2021/22 | 380 | 380 | – |
| Spain La Liga | 2022/23 | 380 | 380 | – |
| Spain La Liga | 2023/24 | 380 | 380 | – |
| Spain La Liga | 2024/25 | 380 | 380 | – |
| Spain La Liga | 2025/26 | 380 | 380 | – |
| Spain La Liga | 2026/27 | 380 | 69 | – |
| Italy Serie A | 2019/20 | 380 | 380 | – |
| Italy Serie A | 2020/21 | 380 | 380 | – |
| Italy Serie A | 2021/22 | 380 | 332 | – |
| Italy Serie A | 2022/23 | 381 | 381 | Play-out (1) |
| Italy Serie A | 2023/24 | 380 | 380 | – |
| Italy Serie A | 2024/25 | 380 | 380 | – |
| Italy Serie A | 2025/26 | 380 | 380 | – |
| Italy Serie A | 2026/27 | 380 | 50 | – |
| France Ligue 1 | 2019/20 | 380 | 380 | – |
| France Ligue 1 | 2020/21 | 380 | 380 | – |
| France Ligue 1 | 2021/22 | 380 | 380 | – |
| France Ligue 1 | 2022/23 | 380 | 380 | – |
| France Ligue 1 | 2023/24 | 308 | 308 | Play-Out Final (2) |
| France Ligue 1 | 2024/25 | 308 | 308 | Play-Out Final (2) |
| France Ligue 1 | 2025/26 | 308 | 308 | Play-out - Final (2) |
| France Ligue 1 | 2026/27 | 306 | 45 | – |
| Mexico Liga MX | 2019/20 | 338 | 320 | Açılış (171), Açılış Çeyrek Final (8), Açılış Yarı Final (4), Açılış Final (2), Kapanış (153) |
| Mexico Liga MX | 2020/21 | 342 | 342 | Açılış (153), Açılış Yeni Sıralama (4), Açılış Çeyrek Final (8), Açılış Yarı Final (4), Açılış Final (2), Kapanış (153), Kapanış - Yeni Sıralama (4), Kapanış Çeyrek Final (8), Kapanış Yarı Final (4), Kapanış Final (2) |
| Mexico Liga MX | 2021/22 | 342 | 342 | Açılış (153), Açılış Yeni Sıralama (4), Açılış Çeyrek Final (8), Açılış Yarı Final (4), Açılış Final (2), Kapanış (153), Kapanış - Yeni Sıralama (4), Kapanış - Çeyrek Final (8),  Kapanış - Yarı Final (4), Kapanış - Final (2) |
| Mexico Liga MX | 2022/23 | 342 | 342 | Açılış (153), Açılış - Yeni Sıralama (4), Açılış - Çeyrek Final (8), Açılış - Yarı Final (4), Açılış - Finaller (2), Kapanış (153), Kapanış - Yeni Sıralama (4), Kapanış Çeyrek Final (8), Kapanış - Yarı Final (4), Kapanış - Final (2) |
| Mexico Liga MX | 2023/24 | 340 | 340 | Açılış (153), Açılış - Yeni Sıralama (2), Apertura - Play-off (1), Açılış - Çeyrek Final (8), Açılış - Yarı Final (4), Açılış - Final (2), Kapanış (153), Kapanış - Yeni Sıralama (2), Kapanış - Play-off (1), Kapanış Çeyrek Final (8), Kapanış Yarı Final (4), Kapanış Final (2) |
| Mexico Liga MX | 2024/25 | 340 | 340 | Açılış (153), Açılış - Yeni Sıralama (2), Açılış - Play-off (1), Açılış - Çeyrek Final (8), Açılış - Yarı Final (4), Açılış - Final (2), Kapanış (153), Kapanış - Yeni Sıralama (2), Kapanış - Play-off (1), Kapanış - Çeyrek Final (8), Kapanış Yarı Final (4), Kapanış - Final (2) |
| Mexico Liga MX | 2025/26 | 337 | 337 | Açılış (153), Açılış - Yeni Sıralama (2), Açılış - Play-off (1), Açılış - Çeyrek Final (8), Açılış - Yarı Final (4), Açılış - Final (2), Kapanış (153), Kapanış Çeyrek Finaller (8), Kapanış Yarı Finaller (4), Kapanış Final (2) |
| Mexico Liga MX | 2026/27 | 153 | 88 | – |
| Saudi Pro League | 2019/20 | 240 | 200 | – |
| Saudi Pro League | 2020/21 | 240 | 240 | – |
| Saudi Pro League | 2021/22 | 240 | 240 | – |
| Saudi Pro League | 2022/23 | 240 | 240 | – |
| Saudi Pro League | 2023/24 | 306 | 306 | – |
| Saudi Pro League | 2024/25 | 306 | 306 | – |
| Saudi Pro League | 2025/26 | 306 | 306 | – |
| Saudi Pro League | 2026/27 | 306 | 63 | – |
| Japan J1 League | 2019 | 306 | 126 | – |
| Japan J1 League | 2020 | 441 | 441 | – |
| Japan J1 League | 2021 | 380 | 380 | – |
| Japan J1 League | 2022 | 306 | 306 | – |
| Japan J1 League | 2023 | 306 | 306 | – |
| Japan J1 League | 2024 | 380 | 380 | – |
| Japan J1 League | 2025 | 380 | 380 | – |
| J1 100 Year Vision League | 2026 | 200 | 200 | Grup Aşaması (180), Final (2), Üçüncülük Maçı (2), 5.lik Maçı (2), 7.lik Maçı (2), 9.luk Maçı (2), 15.lik Maçı (2), 17.lik Maçı (2), 19.luk Maçı (2), 11.lik Maçı (2), 13.lük Maçı (2) |
| Japan J1 League | 2026/27 | 380 | 80 | – |

</details>

## 5. Backfill plan

Per match, 3 requests: arsiv popup (odds + winners + MBS), key events, statistics page. Plus one date listing per
match day (uuid, iddaa code, score, competition → filter to the 26 leagues). Raw responses are not committed;
only Parquet rows.

### Estimate (all 26 leagues, from the oldest season with odds)

- Matches with Nesine odds: **63,603**
- Requests: **193,189** (3 per match: popup, key events, stats page; plus 2,380 date listings)
- Time at 1 request/second: **53.7 h**; with measured latency: **66.8 h**
- Transferred (compressed): **3.5 GB**
- Parquet size: **~22 MB**
- Only the last 2 seasons per league: **11,376** matches, **34,642** requests, ~12.1 h, 0.6 GB

### Chunk plan, newest season first (1100 Actions minutes per month for backfill)

| Month | Seasons | Matches | Minutes |
|---|---|---|---|
| 1 | 2026: all (5); 2026/27: all (22); 2025/26: all (21); 2025: all (5); 2024/25: Spain La Liga 2, Italy Serie B, Turkey Süper Lig, Austria Bundesliga, Denmark Superliga, Belgium Jupiler Pro League, France Ligue 1, Mexico Liga MX, Saudi Pro League, Netherlands Eredivisie, England Premier League, Spain La Liga | 15,676 | 1093 |
| 2 | 2024/25: Italy Serie A, Switzerland Super League, England Championship, Germany 2. Bundesliga, Scotland Premiership, France Ligue 2, Germany Bundesliga, Portugal Primeira Liga, Netherlands Eerste Divisie; 2024: all (5); 2023/24: all (21); 2023: all (5); 2022/23: Spain La Liga 2, Netherlands Eredivisie, Italy Serie B, Austria Bundesliga, Italy Serie A | 15,933 | 1100 |
| 3 | 2022/23: Denmark Superliga, Turkey Süper Lig, Belgium Jupiler Pro League, Spain La Liga, France Ligue 1, France Ligue 2, Saudi Pro League, Switzerland Super League, Mexico Liga MX, Germany 2. Bundesliga, England Premier League, Scotland Premiership, Germany Bundesliga, England Championship, Portugal Primeira Liga, Netherlands Eerste Divisie; 2022: all (5); 2021/22: all (21); 2021: Argentina Liga Profesional, Norway Eliteserien, USA MLS, Brazil Serie A | 15,749 | 1078 |
| 4 | 2021: Japan J1 League; 2020/21: all (21); 2020: all (5); 2019/20: all (21); 2019: Argentina Liga Profesional, Brazil Serie A, Japan J1 League, Norway Eliteserien | 16,096 | 1100 |
| 5 | 2019: USA MLS | 149 | 10 |

Assumptions: daily jobs keep ~900 of the 2,000 monthly minutes (snapshots 9×/day, results, health; smaller once
limited to 26 leagues), leaving ~1,100 minutes per month for the backfill. Each backfill job runs ≤ 110 minutes,
flushes every 25 matches and resumes where it stopped (same pattern as the results backfill).

Alternatives if it should go faster: make the repository public (Actions minutes are free and unlimited for
public repos, but the data becomes public), GitHub Pro (3,000 minutes), or accept a few more months.

Data quality notes for the backfill:
- Final pre-kickoff price only (no opening/movement) → history rows get `snapshot_type = "history_close"`,
  kept separate from our own opening/closing snapshots.
- Winners come from the popup highlight (official) where present, same as `hit_official` today; corners/cards
  and the other unmarked markets are settled by the engine (statistics page, key events) or stay unsettled.
- Transient 500/502s are common on arsiv (also visible in today's daily runs): retries with backoff and a
  "pending" list re-tried by the next job.

## 6. Replace or complement?

**Complement** (approved 2026-10-07).

| Job | Keep (arsiv) | Add (new backend) |
|---|---|---|
| Pre-match snapshots (opening, movement, closing) | program list A (np=1) + popup B | – |
| Which matches / leagues | – | date listing: uuid, iddaa code, competition id → filter to the 26 leagues |
| Results, settlement | popup B highlights (official winners), **validated by uuid** | score from the listing; key events (goals, cards); statistics page (corners, cards) |
| History | – | listing + popup by code (2019-08 →) |

Why not replace: the new backend has **no opening price and no price history**, and its own odds JSON is
sometimes empty. Why add it: one stable id (uuid) across both systems, a listing for any past date (no more
4.5-day arsiv window for results), and events/corners/cards in light JSON/HTML.

Observed during this investigation: on 2026-10-06 arsiv returned bursts of HTTP 500/502 (day lists, popups,
MatchData). The scheduled snapshot runs of 19:18 and 23:34 UTC were marked failed although most data was saved
(e.g. 118 matches listed, 1 popup error). Not changed here (phase paused); worth a small fix later: only fail a
run when a large share of fetches fails.

## Files

- `config/leagues.yaml` – the 26 leagues: new-backend competition id, code and slug; arsiv code/id where verified
  by joining both systems on the same iddaa code (others are filled automatically later, never guessed).
- `scripts/history_probe.py` – endpoint, year and big/small match samples.
- `scripts/history_leagues.py`, `scripts/history_coverage.py` – per league-season probes.
- `scripts/history_summary.py` – builds the tables in sections 4–5 from the probe output.
- `scripts/history_scan.py` – day-by-day listing scan (too slow for the full range; kept for the backfill index).
- `src/odds_analysis/http.py` – `get(..., follow_redirects=)` for the statistics page.
