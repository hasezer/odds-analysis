# odds-analysis

[![Snapshot odds](https://github.com/hasezer/odds-analysis/actions/workflows/snapshot.yml/badge.svg)](https://github.com/hasezer/odds-analysis/actions/workflows/snapshot.yml)
[![Results](https://github.com/hasezer/odds-analysis/actions/workflows/results.yml/badge.svg)](https://github.com/hasezer/odds-analysis/actions/workflows/results.yml)
[![Health](https://github.com/hasezer/odds-analysis/actions/workflows/health.yml/badge.svg)](https://github.com/hasezer/odds-analysis/actions/workflows/health.yml)

Collects Nesine pre-match odds via Mackolik every day, settles every selection and analyses the results.
Runs entirely on GitHub Actions and uses only data collected by this project.

| Workflow | When (UTC) | What |
|---|---|---|
| Snapshot odds | 06:07, then every 2 h 08:07–22:07 | upcoming matches + all Nesine markets → `data/matches`, `data/odds` |
| Results | 05:04 | finished matches in the ~4.5-day archive → `data/results`, `events`, `stats`, `official`; then settlement (`data/settled`) and exports |
| Weekly analysis | Mondays 07:37 | `reports/YYYY-MM-DD.md` (+ charts), `reports/findings.md`, `exports/analysis_summary.csv` |
| Health | every 12 h | fails (GitHub emails you) if no successful (ok or partial) results run in 48 h or snapshot in 12 h |
| Phase 0 - endpoint check | manual | re-verifies every Mackolik endpoint |

Every data run commits to `main` and logs itself in `data/runs.csv`. Raw responses are uploaded as Actions artifacts (7 days) and never committed.

**Run status** (`status` column of `data/runs.csv`). Mackolik often answers with bursts of HTTP 500/502. Every request is retried 3 times (after 5, 15 and 45 seconds). After that:
- **ok**: everything worked.
- **partial** (green run with a warning): some requests still failed. They are logged in `data/failed_items.csv`, queued in `data/retry_queue.csv` and retried by the next run.
- **failed** (red run, GitHub emails you): more than 20 % of requests failed, or no match was saved although matches were due.
**Exports for the iPad** live on the [`exports` branch](https://github.com/hasezer/odds-analysis/tree/exports/exports). It is rebuilt every day as a single commit, so the repository doesn't grow. It holds:
- `daily/YYYY-MM-DD.xlsx`: last 60 days
- `all_settled.csv.gz`
- `monthly/YYYY-MM.csv.gz`

In GitHub, open a file → *View raw* to download it.

**Weekly reports:** [`reports/`](reports/). The running log of patterns that held up on newer data is [`reports/findings.md`](reports/findings.md). For a compact table to upload to a Claude chat, use `analysis_summary.csv` on the exports branch.

See [SCHEMA.md](SCHEMA.md) for the agreed data structure (the daily jobs move to it in the next phase), [docs/DATA.md](docs/DATA.md) for the current tables and [PHASE0_REPORT.md](PHASE0_REPORT.md) for the endpoint research.
