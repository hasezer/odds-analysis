# History investigation – Nesine odds from the new mackolik.com backend

Scope: the 26 leagues in `config/leagues.yaml` (regular season + their own playoff / relegation-playoff stages,
no cups). Everything below was measured from Mackolik only (new www.mackolik.com backend + arsiv.mackolik.com),
at ≤ 1 request/second, read-only. **No backfill was run.**

## TL;DR

1. **There is history, back to August 2019.** The new mackolik.com backend keeps every past match with its iddaa
   (Nesine) event code from **2019-08-01** onwards. With that code the old arsiv odds popup still returns the
   **full Nesine market list with the winners marked** for matches 7 years old. Before August 2019: nothing
   (0 iddaa codes in 2014–2018 samples).
2. **Geo test: no blocking.** From a US IP the servers returned the same full odds as from Turkey. Nothing was
   bypassed.
3. **The historical price is the final pre-kickoff price** (one price per selection: no opening price, no
   movement). Opening odds and line movement exist only from our own snapshots.
4. **For the 26 leagues, a full backfill is about __TOTAL__ matches, ~__HOURS__ hours of requests, ~__GB__ GB
   transferred and ~__MB__ MB of Parquet.** Newest season first, it fits in **__MONTHS__ months** of the
   2,000 free Actions minutes (alongside the daily jobs).
5. **Recommendation: complement, don't replace.** Keep the arsiv program list + popup for pre-match snapshots
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
different match** (7 transient HTTP 500/502, 3 empty). So the popup is validated by uuid, which also fixes the
"popup resolved to an old match" problem the daily pipeline currently works around with `morebets`.

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

**How the market list grew** (big matches, popup):

| Season | Markets per big match | New in that period |
|---|---|---|
| 2019/20 | 34–39 | 1X2, double chance, O/U 0.5–5.5, HT markets, handicaps, correct score, first goal, "Ev Sahibi/Deplasman Gol Yemez", "Gol Atacak Takımlar" |
| 2020/21 | 39–41 | more team totals |
| 2021/22 | 43–44 | |
| 2022/23 | 52–55 | corners and cards markets |
| 2023/24 | 58–59 | **Kart Puanı** (card points) markets |
| 2024/25 | 71 | |
| 2025/26 | 73–79 | |

The new-site odds JSON shows fewer markets (≈ 50 in 2025) than the popup. Three old market names are not in
`config/` yet: "Deplasman Gol Yemez", "Ev Sahibi Gol Yemez", "Gol Atacak Takımlar" (they would be logged as
unmapped, never guessed).

## 4. Per league (26 leagues)

How this was measured (`scripts/history_coverage.py`): for every league and season, the season fixture page
(all matches incl. playoffs), the date listing of the season's busiest matchday (share of the league's matches
with an iddaa code = "offered on Nesine"), then up to 3 of those matches: arsiv popup (must be the same uuid),
key events and statistics page. Events/corners/cards columns also include the samples of
`scripts/history_leagues.py`. Small samples: treat single percentages as indications, not exact rates.

Season labels: calendar-year leagues (Norway, MLS, Brazil, Japan, Argentina) use "2024"; the others "2024/25".
Japan's J1 moves to an autumn–spring calendar from 2026 ("2026/27").

<!-- TABLES -->

## 5. Backfill plan

Per match, 3 requests: arsiv popup (odds + winners + MBS), key events, statistics page. Plus one date listing per
match day (uuid, iddaa code, score, competition → filter to the 26 leagues). Raw responses are not committed;
only Parquet rows.

<!-- BACKFILL -->

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

**Complement.**

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
