# Analysis work: standing rules and memory

## Owner's standing rules (always)
- **Do not change the collection code, workflows or config:** `src/odds_analysis/`, `.github/`, `config/`, `scripts/`. A backfill runs in GitHub Actions and commits to `main` about every 2 hours.
- **Use only data this project collected** (Nesine via Mackolik). No external data sources, ever.
- **Always `git pull origin main` before analysing.**
- **Data scope:**
  - Seasons in use: 2024/25, 2025/26, 2026/27 (so far), 2024, 2025 and 2026. Older seasons are not used yet.
  - Ignore the 37 TUR-1 placeholder fixtures whose `match_id` starts with "macko" (`load.py` drops them).
- **The owner only has an iPad:**
  - explain results in simple terms;
  - send tables as Excel and charts as PNG;
  - no website or interface is wanted for the daily scan, just the findings.
- **Git:**
  - work on a branch;
  - put analysis code under `analysis/`;
  - open PRs for the owner to merge, and **never merge yourself**.
- **Validation:** find on 2024/25 (+2024), confirm on 2025/26 (+2025), exam on 2026/27 (+2026 so far). Every search gets a luck control (shuffled results or a no-edge twin).

## The strategy book is the project's memory. Never lose it.
- **Where it lives:**
  - `strategies.yaml`: every strategy with exact criteria, season-by-season evidence, status, `first_added`, plus `lessons` (what did not work).
  - `STRATEGIES.md`: the same, in plain language.
  - `strategy_history/`: a dated copy of every version and `CHANGELOG.md`.
- **Never delete or hand-edit strategies.** Rebuild with `python analysis/build_strategy_book.py`. It keeps every earlier strategy: one that no longer passes becomes `status: retired` with a date and reason. The daily scan skips retired ones.
- **When a new study finds something:**
  - add it to `build_strategy_book.py`, as a new kind or as an entry in an existing kind;
  - rebuild;
  - commit `strategies.yaml`, `STRATEGIES.md` and `strategy_history/` in the same PR as the study.
- **When a study finds that something does NOT work:** add one line to `LESSONS` in `build_strategy_book.py`.
- **Daily scan:**
  - `bash analysis/daily_scan.sh /tmp/daily-scan 2` checks every active strategy on today's and tomorrow's fixtures. It writes `output/daily_scan.md` and `.xlsx`.
  - The Claude routine "Daily strategy scan (26 leagues)" runs it every morning at 08:56 Turkey time.

- Live tracker: `python analysis/tracker.py` replays every strategy (as stored, from the day after `first_added`) on
  finished matches at closing odds -> `output/tracker.md` / `.xlsx`. The daily routine runs it after the scan.
- **The owner plays a 10-game system coupon (system 3-4-5 = 582 combos).** Strategy kind `system` stores whole
  coupons (groups of leagues + bets, lowest odds first, one per weekend Fri-Mon). The daily scan prints the coming
  weekend's coupons (section "Your 10-game system") and the tracker replays them weekly (SIX_SYSTEM_REPORT).

## Reports, in order
- `REPORT.md` (first look)
- `HTFT_REPORT.md`
- `ML_REPORT.md`
- `MINER_REPORT.md`
- `RULES_REPORT.md`
- `RULES_V3_REPORT.md`
- `HIGH_ODDS_REPORT.md`
- `RULES_V4_REPORT.md`
- `RULES_V5_REPORT.md`
- `SIX_PLUS_REPORT.md`
- `SIX_SYSTEM_REPORT.md` (the owner's 10-game 3-4-5 system: Goals coupon)
- `HTFT2_REPORT.md` (HT/FT from the favourite's side: map, half-time live table, prices)
- `HTFT3_REPORT.md` (how to spot 1/X, 2/X, X/1, X/2, 1/2, 2/1: hit-rate techniques)
- `BB_REPORT.md` (both teams score in both halves: every sign, fair race, rules, live half-time table)
- `cs_study.py` (correct scores, full time and half time; no report by the owner's request: rules, bands and lessons live in the strategy book)

## Known data traps
- **HT_2H_BTTS:** prices are label-swapped for 211 matches in Oct–Nov 2025 (excluded in `miner_data.py`); there YES/YES sits at 1.10–2.02, real prices start at 4.66. The price exists only from 2025/26.
- **HT_BTTS / 2H_BTTS:** the NO side is missing for ~45% of matches; use the YES odds, not the 'fair' chance.
- **Referee:** empty.
- **Odds movement:** the project's 2-hourly snapshot workflow is paused (schedule commented out; last run 2026-10-06), so our own snapshots cover only ~11 settled matches. From 2026-10-17 the daily scan keeps its morning snapshot on the data-only branch `odds-snapshots` (`keep_snapshot.py` + `push_snapshot.sh`, never main); `movement.py` compares those morning prices with Nesine's closing prices.
- **Nesine caps:** HT/FT about 35, correct score 130, half-time correct score 66.
- **Correct scores:** listed for only 33% of 2025/26 matches (99% in 2024/25, 93% in 2026/27), and the odds got longer after 2024/25 (smaller margin). Use normalised chances, not fixed odds cut-offs.
- **Comparing techniques:** compare on the same number of games (e.g. each picks its top 10% in each season). A fixed cut-off from 2024/25 picks different-sized groups later, which flatters the stricter one.
- **"Fair" chance:** spreading the cut evenly is biased for short odds. Use the break-even hit rate at the odds paid.
- **`analysis/cache/` is gitignored:** rebuild it with the scripts. The strategy book does not depend on it being present.
