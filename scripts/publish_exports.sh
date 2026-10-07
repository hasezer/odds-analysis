#!/usr/bin/env bash
# Build exports into ./_exports (starting from the current 'exports' branch) and publish them as a single
# fresh commit on the 'exports' branch (force-pushed: rebuildable files, so no history is kept).
# Usage: scripts/publish_exports.sh "<python -m odds_analysis args>"   e.g. "export --days 7"
set -euo pipefail
args="${1:-export --days 7}"
rm -rf _exports
if git ls-remote --exit-code --heads origin exports >/dev/null 2>&1; then
  git fetch -q --depth 1 origin exports
  mkdir -p _exports && git archive FETCH_HEAD | tar -x -C _exports
fi
mkdir -p _exports/exports
# files of the pre-SCHEMA.md exports (removed 2026-10)
rm -rf _exports/exports/daily _exports/exports/monthly _exports/exports/all_settled.csv.gz
ODDS_EXPORTS_DIR="$PWD/_exports/exports" PYTHONPATH=src python -m odds_analysis $args
cat > _exports/README.md <<'MD'
# Exports (rebuilt automatically – this branch has no history)

Per season (`exports/<season>/`, e.g. `exports/2026-27/`):
- `oranlar_<season>.xlsx` – **one row per match**, one sheet per league: date, teams, HT/FT score, corners, cards and
  Nesine's closing odds of the 45 collected markets; winning odds are green
- `<league_id>.csv.gz` – every selection (analysis_flat: opening/closing odds, probabilities, margin, hit, status)

Columns are described in `SCHEMA.md` on the main branch.
MD
cd _exports
git init -q -b exports
git config user.name "odds-bot"
git config user.email "odds-bot@users.noreply.github.com"
git add -A
git commit -q -m "exports $(date -u +%Y-%m-%dT%H:%MZ)"
if [ -n "${GH_TOKEN:-}" ] && [ -n "${GITHUB_REPOSITORY:-}" ]; then
  url="https://x-access-token:${GH_TOKEN}@github.com/${GITHUB_REPOSITORY}.git"
else
  url="$(cd .. && git config --get remote.origin.url)"
fi
for delay in 2 4 8 16 0; do
  if git push -q -f "$url" exports:exports; then
    pushed=1
    break
  fi
  sleep "$delay"
done
[ "${pushed:-0}" = 1 ] || { echo "could not push the exports branch" >&2; exit 1; }
echo "exports published"
