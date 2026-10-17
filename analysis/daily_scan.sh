#!/usr/bin/env bash
# Daily strategy scan (run from the repo root). Commits nothing; never touches src/, .github/, config/, scripts/.
#   1. installs what the scan and the snapshot collector need
#   2. rebuilds the rule-book cache if missing (analysis/cache is gitignored): ml_data -> miner_data -> rules_deep
#   3. runs the project's own snapshot command on a COPY of data/ (ODDS_DATA_DIR): repo and backfill untouched
#   4. checks every strategy of analysis/strategies.yaml -> analysis/output/daily_scan.md and .xlsx
set -euo pipefail
WORK="${1:-/tmp/daily-scan}"
DAYS="${2:-3}"
mkdir -p "$WORK"
python -m pip install -q -r analysis/requirements.txt 2>&1 | grep -v WARN || true
python -c "import httpx, selectolax" 2>/dev/null || python -m pip install -q httpx==0.28.1 selectolax==1.0.0 2>&1 | grep -v WARN || true
python -c "import yaml" 2>/dev/null || python -m pip install -q PyYAML 2>&1 | grep -v WARN || true

echo "== rule-book cache"
[ -f analysis/cache/ml_sel.parquet ] || python analysis/ml_data.py > "$WORK/ml_data.log" 2>&1
[ -f analysis/cache/miner.npz ] || python analysis/miner_data.py > "$WORK/miner_data.log" 2>&1 || true
[ -f analysis/cache/rules_deep.parquet ] || python analysis/rules_deep.py > "$WORK/rules_deep.log" 2>&1 || true

echo "== odds snapshot (copy of data/)"
rm -rf "$WORK/data" && cp -r data "$WORK/data"
SNAP_START="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
ODDS_DATA_DIR="$WORK/data" PYTHONPATH=src python -m odds_analysis snapshot --full > "$WORK/snapshot.log" 2>&1 || \
  echo "snapshot reported errors (see $WORK/snapshot.log); scanning with what was collected"

echo "== keep the morning odds (branch odds-snapshots; never main)"
rm -rf "$WORK/keep"
python analysis/keep_snapshot.py "$WORK/data" "$WORK/keep" --since "$SNAP_START" && \
  bash analysis/push_snapshot.sh "$WORK/keep" || echo "morning odds not kept today (the scan goes on)"

echo "== scan"
python analysis/daily_scan.py --data-dir "$WORK/data" --days "$DAYS"
