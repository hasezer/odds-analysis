# Phase 0 report: endpoint verification

Date: 2026-10-06. Checked from two places:

1. **This development container** (cloud, not GitHub): all checks passed.
2. **GitHub Actions runner**, workflow `Phase 0 - endpoint check` (`.github/workflows/phase0.yml`): **all checks passed**. See [GitHub Actions result](#github-actions-result).

You can re-run it any time from the iPad: GitHub → Actions → *Phase 0 - endpoint check* → *Run workflow*. Every run uploads `phase0-output` (summary, market catalog, all raw responses), kept for 7 days. Raw files are never committed.

---

## Short version

| | Endpoint | Works? | Notes |
|---|---|---|---|
| A | Day list (`command=tab`, `np=0`) | ✅ | Played + unplayed matches, scores, 1X2 / 2,5 / ÇŞ odds, MBS, event code. About 4.5 days back. |
| B | Odds popup (`command=oddspopup`) | ✅ | All Nesine markets. **Still works after full time** and keeps the pre-match odds. Bonus: marks winning selections. |
| C | Iddaa-Programi page | ✅ but weaker | Only 128 matches and **no league codes**. Recommend using A with `np=1` for upcoming matches (220 matches incl. league codes). |
| D | Match page + 3 AJAX calls | ✅ | MS/İY score, goals with minute/assist/running score, cards (2nd yellow flagged), subs, stats. Referee/stadium only on bigger matches. |

**Mackolik did not block us, from GitHub Actions or from the dev container.** Every request returned HTTP 200 with real data and needed no retry.

---

## A: day list

`https://arsiv.mackolik.com/AjaxHandlers/IddaaHandler.aspx?command=tab&type=2&st=Football&l=-1&d=<dd.mm.yyyy>&i=0&t=&ip=1&w=<week>&g=7&np=0&srt=-1&srtd=1`

Verified:
- Every row parses: kickoff (Turkey time, UTC+3), league code (`AVUL`, `İS4`, `JAP2`…), league id, MBS (`mbsN.png`), team ids and names, mackolik match id, İY and MS scores, the three markets with odds, the visible "Kod" column, and the **event code (7th `openOddsDialog` argument)**. Field coverage on 1,359 rows: 100% for event code, league code, MBS and 1X2 odds.
- Portekiz–Norveç: `2026-10-04 21:45 AVUL MBS1`, İY 1-1, MS 2-1, event code `3180547`, odds 1.50 / 3.96 / 3.93.
- Odds written with commas (`'2,58'`) or dots (`2.58`) both parse. `-` and blank cells become NULL.

Some things behave differently from the brief:

| Brief said | What I measured | Impact |
|---|---|---|
| Rolling ~5-day window | Oldest match available was **01.10 21:45 TR** at 06.10 13:20 TR, so **about 4.5 days**. 29.09 and 30.09 are empty. | Same plan: run daily. Downtime of 3+ days is risky. |
| `d=-1` returns empty | `d=-1&np=0` returned the **whole window in one call** (1,360 matches, 5 MB, 01.10 → 15.10). | Useful fallback. Per-date calls are still preferable because they are smaller. |
| `w` (week id) matters | `w` is **ignored**. Results were identical with `w=24139`, `w=24140`, `w=1` or empty. | Nothing to compute. |
| `d` = one calendar day | Each `d` returns that day **plus the early hours of the next day** (iddaa day). Each block has its own date header, so the true date is still known. | The parser uses the header date. Matches are deduplicated by match id. |

Current window by date (np=0): 01.10: 15 (partly expired), 02.10: 122, 03.10: 536, 04.10: 374, 05.10: 68, 06.10: 141, then upcoming.

16 past matches had **no score** in the list. On D they are `Ert.` (postponed, score `P - P`). One match (Real Unión–Laguna, 02.10) is stuck at `IY` with `p=1` four days later, which looks abandoned or a dead feed. Rule for settlement: **settle only when D status is `MS`**, void on `Ert.`/cancelled, otherwise leave it pending.

## B: all markets per match (JSON)

`https://arsiv.mackolik.com/AjaxHandlers/IddaaHandler.aspx?command=oddspopup&e=<EVENT_CODE>&s=futbol`

- **Finished match `e=3179478`** (Galler–Danimarka, 04.10, FT 0-1): `status=Played`, **89 Nesine markets, 533 selections**. Bookies are Nesine (id 14) and Oley (id 15). Only Nesine is kept.
- The odds after full time are the **pre-match odds**. They are identical to the day list: 3.15 / 3.07 / 1.87.
- **`highlight: true` marks winning selections after the match.** On 3179478, 55 selections are highlighted: MS `2`, KG `Yok`, 2,5 `Alt`, Maç Skoru `0-1`, İY/MS `X/2`, Hnd. MS (1:0) `X`, and so on. These are all correct for 0-1 (İY 0-0). This is Nesine/Mackolik's own result, so it can **cross-check every settlement for free**. Corner and card markets were *not* highlighted.
- Upcoming matches: `status=Fixture`, 5/5 sampled returned Nesine markets (8 to 67 markets depending on league). `start_time` is **UTC**, while the lists use Turkey time (21:45 TR = 18:45 UTC).
- Market fields: `name`, `code`, `mbc` (=MBS), `sov` (line), `handicap_value`, `handicap_team`, and `outcomes[]{name, key, value, highlight, market_type_id}`. `-` becomes NULL; 12 of 533 were NULL on the finished example.
- **`code` is not a market type.** It is the per-event coupon number and is different for every match. The stable id is `outcomes[].market_type_id`: 98 market names map to 82 type ids, and only line variants share an id (all `x,5 Korner Alt/Üst` share 216, `Hnd. MS (a:b)` share 268, `x,5 Kart Puanı` share 301). The normalizer will use `market_type_id` + line.

Market families seen (full list in the `market_catalog.csv` artifact):
- Score-based (all settleable from D): MS, ÇŞ, KG, all goal Alt/Üst lines, İY/2Y result, İY ÇŞ, İY Alt/Üst, İY KG, 2Y KG, İY/MS, İY skoru, Maç Skoru, İlk Yarı / Maç Skoru, Hnd. MS (0:1)/(1:0)/(2:0)/(0:2), Tek/Çift, İY Tek/Çift, Toplam Gol Aralığı, team Alt/Üst (home/away, also first-half), Gol Yemeden Kazanır, Yarı Kazanır, İki Yarıyı da Kazanır, İki Yarıda da Gol Atar, Hangi Yarıda Daha Çok Gol, En Çok Gol Olacak Yarı, İki Yarı da 1,5 Alt/Üst, Hangi Takım Kaç Farkla Kazanır, combos (MS ve x,5 Alt/Üst, MS ve KG, 2,5 Alt/Üst ve KG, İY ve İY 1,5, İY ve İY KG, İY/2Y KG).
- İlk Gol: settleable from goal events (see D coverage below).
- Corners: Korner Alt/Üst 7,5 to 12,5, Toplam Korner Aralığı, En Çok Korner, Korner Tek/Çift. First-half corner markets exist too (İY 3,5/4,5/5,5, İY Korner Aralığı, İY En Çok Korner).
- Cards: **"Kart Puanı Alt/Üst" 2,5 to 6,5 and "Hangi Takım Daha Çok Kart Puanı Alır?"**. These are card *points*, not card counts. See the questions below.
- Cannot be settled from our data (will be stored but marked unsettleable): player markets (İlk Golü Atar, Gol Atar, Asist, Kart Görür), Penaltı Olur Mu, Takım Şut / İsabetli Şut / Faul / Ofsayt "N+" markets (partly possible from stats), Taç Atışı, Kale Vuruşu, "Karşılaşma Özel / Kombo Bahisleri".

## C: upcoming program

`https://arsiv.mackolik.com/Iddaa-Programi`: HTTP 200 and the same row structure, so the same parser works. However, it only showed **128 matches (06–07.10)**, and the **league code cell is empty** on every row. A with `d=-1&np=1` gave 220 upcoming matches up to 15.10 with league codes. **Recommendation: use A (`np=1`) as the upcoming source and keep C as a fallback.**

## D: match detail

The page itself (`/Match/Default.aspx?id=<id>`) only contains the header in its HTML. Scores, events and stats are loaded by JavaScript. I found the endpoints in Mackolik's own `Match.js`:

| Data | Endpoint | Format |
|---|---|---|
| Header: league, date/time, teams, stadium, referee, attendance | `/Match/Default.aspx?id=<id>` | HTML |
| **MS + İY score, status, events** | `/Match/MatchData.aspx?t=dtl&id=<id>&s=0` | JSON |
| İstatistikler box (Opta) | `/AjaxHandlers/MatchHandler.aspx?command=optaStats&id=<id>` | HTML fragment |
| Stats box (second provider) | `/AjaxHandlers/MatchHandler.aspx?command=rbStats&id=<id>` | HTML fragment |

`MatchData` JSON: `d.s` = score, `d.st` = status (`MS`, `IY`, `Ert.`, minute), `d.ht` = İY score, and `d.ft`/`d.et`/`d.pt` for extra time and penalties. Each event is `[team(1/2), minute, player_id, player, type, extra]`, where type is 1 goal (`d`: 1 normal, 2 penalty, 3 own goal, plus `astId/astName` for the assist), 2 yellow, 3 red (`d=1` means **second yellow**), 4 substitution, or 7 missed penalty.

Portekiz–Norveç (id 4445150) parsed exactly:
- MS 2-1, İY 1-1, UEFA Uluslar Ligi A Ligi Grup 4, 4.10.2026 21:45, Estadio do Dragao, referee Maurizio Mariani, 48,832 spectators.
- Goals: 36' Norveç (0-1, Ajer, assist Ødegaard); 38' Portekiz (1-1, Cancelo, assist N. Mendes); 79' Portekiz (2-1, G. Ramos, assist J. Félix).
- Cards: 12' Cancelo yellow; 86' Conceição yellow **+ red (second yellow)**; 88' B. Fernandes yellow.
- Stats (Opta): possession 59/41, shots 20/9, on target 7/3, passes 434/274, pass accuracy 87/78, **corners 6/4**, crosses 3/11 vs 1/9, fouls 8/7, offsides 2/2.
- The rbStats provider differs slightly: fouls 9/7, offsides 1/2, corners **6/4 (same)**.

Coverage on a random sample of 15 finished matches across all leagues:

| Item | Available |
|---|---|
| Final status + MS score | 15/15 |
| İY score | 15/15 |
| A list score = D score | 15/15 (0 mismatches) |
| Goal events that add up to the final score | **9/15**. Lower leagues (Japanese amateur, English non-league, Swedish 4th tier, Swiss youth) have **no events at all**. |
| Opta stats | 2/15 (big leagues only) |
| rbStats | 13/15 |
| Corners (either source) | 14/15 |
| Referee / stadium | 0/15. They only appear on bigger matches. |
| Popup (B) still available after FT | 15/15 |

What this means for settlement:
- Score-based markets: always settleable.
- **İlk Gol**, team-scores-in-both-halves, etc. need goal order or half split. Half split comes from İY/MS and is always available. Goal order is only available when events are complete (event goals = final score). Otherwise the result is NULL, unless we use the B highlight (see question 3).
- Corners: from Opta "Korner", falling back to rbStats "Köşe Vuruşu".
- **First-half corners: not available anywhere.** I also checked Mac-Plus and `optaStatsRaw`. First-half corner markets will be NULL, as you specified.
- Cards: only where events exist. Lower leagues with no events give NULL, but those leagues also get almost no card markets.

---

## GitHub Actions result

**Passed: Mackolik does not block GitHub's servers.**

- Run: [Phase 0 - endpoint check #2](https://github.com/hasezer/odds-analysis/actions/runs/37450000472) (2026-10-06 10:29 UTC, runner on a Microsoft Azure IP). All 13 checks passed. About 110 requests to Mackolik, every one **HTTP 200 on the first attempt** with no retries, in about 3 minutes at 1 request/sec.
- The results are the same as in the dev container: same window (01.10 → 08.10 per date; 1,359 matches with `d=-1`), Portekiz–Norveç parsed exactly, 89 markets in the finished popup with 55 highlighted, and the same 15/15 deep sample coverage. On GitHub the `w` parameter test also confirmed it is ignored.
- 98 distinct Nesine market names were seen. They are listed in `market_catalog.csv` inside the run's `phase0-output` artifact, together with every raw response (7 days).
- Run #1 was cancelled halfway because I pushed a second commit. It had also received only HTTP 200 responses up to that point.
- Note: the workflow runs on `workflow_dispatch` (manual), and also on this PR so the check could run before your review.

---

## Questions for you before Phase 1

1. **Card markets are "Kart Puanı" (card points), not card counts.** I need Nesine's points rule. My understanding (not verified) is yellow = 1 point and red = 2 points, but I don't know how Nesine counts a second yellow. Please check Nesine's rules page. Your default (yellow=1, red=1, second yellow=1 total) would mis-settle these. I will put both in `config/card_rules.yaml` and mark card settlements `unverified` until you confirm. The B `highlight` flag does not cover card markets, so it cannot settle this for us.
2. **Upcoming source:** OK to use A (`np=1`, per date) instead of C, since C lacks league codes and has fewer matches?
3. **Use B's `highlight` flag?** It is Nesine/Mackolik data from this project and marks winning selections after the match. I suggest (a) settling from D as you specified, (b) logging any disagreement with `highlight` to `data/settlement_mismatches.csv`, and (c) using `highlight` only as the fallback when D cannot decide (e.g. İlk Gol when events are missing). Fine?
4. **Extra time / cups:** none in the window to test. I will settle on the 90-minute score: `d.ft` when it is filled, otherwise `d.s` when status is `MS`. Cup matches with `UZ`/`Pen` will be logged so we can verify the first one.
