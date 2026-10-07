# odds-analysis

[![Snapshot odds](https://github.com/hasezer/odds-analysis/actions/workflows/snapshot.yml/badge.svg)](https://github.com/hasezer/odds-analysis/actions/workflows/snapshot.yml)
[![Results](https://github.com/hasezer/odds-analysis/actions/workflows/results.yml/badge.svg)](https://github.com/hasezer/odds-analysis/actions/workflows/results.yml)
[![Health](https://github.com/hasezer/odds-analysis/actions/workflows/health.yml/badge.svg)](https://github.com/hasezer/odds-analysis/actions/workflows/health.yml)

Collects Nesine pre-match odds via Mackolik for **26 leagues** (`config/leagues.yaml`) and **45 markets**
(`config/markets.yaml`), settles every selection and analyses the results. Runs entirely on GitHub Actions and uses
only data collected by this project. The data structure is described in [SCHEMA.md](SCHEMA.md).

| Workflow | When (UTC) | What |
|---|---|---|
| Snapshot odds | 06:07, then every 2 h 08:07–22:07 | upcoming matches (www.mackolik.com) + Nesine odds (arsiv popup): opening, price changes, closing → `data/matches`, `data/odds` |
| Results | 05:04 | finished matches of the last 5 days: score, events, statistics, Nesine's final odds + winner marks → `data/events`, `stats`, `odds`, `settlements`, `analysis_flat`; quality checks; exports |
| Weekly analysis | paused | moves to the new tables in its own PR |
| Health | every 12 h | fails (GitHub emails you) if no successful (ok or partial) results run in 48 h or snapshot in 12 h |
| Phase 0 - endpoint check | manual | re-verifies every Mackolik endpoint |

Every data run commits to `main` and logs itself in `data/runs.csv` (and the `data/runs/` table). Data quality checks
after every run are appended to `data/quality.csv`. Raw responses are uploaded as Actions artifacts (7 days) and never
committed.

**Run status** (`status` column of `data/runs.csv`). Mackolik often answers with bursts of HTTP 500/502. Every request is retried 3 times (after 5, 15 and 45 seconds). After that:
- **ok**: everything worked.
- **partial** (green run with a warning): some requests still failed. They are logged in `data/failed_items.csv`, queued in `data/retry_queue.csv` and retried by the next run.
- **failed** (red run, GitHub emails you): more than 20 % of requests failed, or no match was saved although matches were due.

**Exports for the iPad** live on the [`exports` branch](https://github.com/hasezer/odds-analysis/tree/exports/exports), rebuilt after every results run as a single commit (so the repository doesn't grow). Per season (`exports/<season>/`):
- `oranlar_<season>.xlsx`: **one row per match**, one sheet per league, closing odds of the 45 markets, winning odds green
- `<league_id>.csv.gz`: every selection with opening/closing odds, probabilities, margin, hit and status

In GitHub, open a file → *View raw* to download it.

**Weekly reports:** [`reports/`](reports/). The running log of patterns that held up on newer data is [`reports/findings.md`](reports/findings.md). For a compact table to upload to a Claude chat, use `analysis_summary.csv` on the exports branch.

See [SCHEMA.md](SCHEMA.md) for the data structure, [HISTORY_REPORT.md](HISTORY_REPORT.md) for the history research and [PHASE0_REPORT.md](PHASE0_REPORT.md) for the endpoint research.
