#!/usr/bin/env bash
# Daily Matchday Radar build (run from the repo root). Commits nothing; never touches src/, .github/, config/, scripts/.
#   1. installs what the analysis and the snapshot collector need
#   2. rebuilds the rule caches (analysis/cache is gitignored): ml_data -> miner_data -> rules_deep (+ luck control)
#   3. runs the project's own snapshot command on a COPY of data/ (ODDS_DATA_DIR), so the repo and the backfill
#      are untouched
#   4. builds analysis/output/dashboard.html
set -euo pipefail
WORK="${1:-/tmp/matchday-radar}"
mkdir -p "$WORK"
pip install -q -r analysis/requirements.txt 2>&1 | grep -v WARN || true
python -c "import httpx, selectolax" 2>/dev/null || pip install -q httpx==0.28.1 selectolax==1.0.0 2>&1 | grep -v WARN || true
python -c "import yaml" 2>/dev/null || pip install -q PyYAML 2>&1 | grep -v WARN || true

echo "== rule caches"
[ -f analysis/cache/ml_sel.parquet ] || python analysis/ml_data.py > "$WORK/ml_data.log" 2>&1
[ -f analysis/cache/miner.npz ] || python analysis/miner_data.py > "$WORK/miner_data.log" 2>&1 || true
[ -f analysis/cache/rules_deep.parquet ] || python analysis/rules_deep.py > "$WORK/rules_deep.log" 2>&1

echo "== odds snapshot (copy of data/)"
rm -rf "$WORK/data" && cp -r data "$WORK/data"
ODDS_DATA_DIR="$WORK/data" PYTHONPATH=src python -m odds_analysis snapshot --full > "$WORK/snapshot.log" 2>&1 || \
  echo "snapshot reported errors (see $WORK/snapshot.log); building with what was collected"

echo "== dashboard"
python analysis/dashboard.py --data-dir "$WORK/data" --days 4
