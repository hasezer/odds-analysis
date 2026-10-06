# odds-analysis

[![Snapshot odds](https://github.com/hasezer/odds-analysis/actions/workflows/snapshot.yml/badge.svg)](https://github.com/hasezer/odds-analysis/actions/workflows/snapshot.yml)
[![Results](https://github.com/hasezer/odds-analysis/actions/workflows/results.yml/badge.svg)](https://github.com/hasezer/odds-analysis/actions/workflows/results.yml)
[![Health](https://github.com/hasezer/odds-analysis/actions/workflows/health.yml/badge.svg)](https://github.com/hasezer/odds-analysis/actions/workflows/health.yml)

Collects Nesine pre-match odds via Mackolik every day, settles every selection and analyses the results.
Runs entirely on GitHub Actions and uses only data collected by this project.

| Workflow | When (UTC) | What |
|---|---|---|
| Snapshot odds | 06:00, then every 2 h 08:00–22:00 | upcoming matches + all Nesine markets → `data/matches`, `data/odds` |
| Results | 05:00 | finished matches in the ~4.5-day archive → `data/results`, `events`, `stats`, `official`; then settlement (`data/settled`) and exports |
| Weekly analysis | Mondays 07:37 | `reports/YYYY-MM-DD.md` (+ charts), `reports/findings.md`, `exports/analysis_summary.csv` |
| Health | every 12 h | fails (GitHub emails you) if no successful results run in 48 h or snapshot in 12 h |
| Phase 0 - endpoint check | manual | re-verifies every Mackolik endpoint |

Every data run commits to `main` and logs itself in `data/runs.csv`. Raw responses are uploaded as Actions artifacts (7 days) and never committed.
**Exports for the iPad** live on the [`exports` branch](https://github.com/hasezer/odds-analysis/tree/exports/exports). It is rebuilt every day as a single commit, so the repository doesn't grow. It holds:
- `daily/YYYY-MM-DD.xlsx`: last 60 days
- `all_settled.csv.gz`
- `monthly/YYYY-MM.csv.gz`

In GitHub, open a file → *View raw* to download it.

**Weekly reports:** [`reports/`](reports/). The running log of patterns that held up on newer data is [`reports/findings.md`](reports/findings.md). For a compact table to upload to a Claude chat, use `analysis_summary.csv` on the exports branch.

See [docs/DATA.md](docs/DATA.md) for the tables and [PHASE0_REPORT.md](PHASE0_REPORT.md) for the endpoint research.
