#!/usr/bin/env bash
# Push the files written by keep_snapshot.py to the data-only branch `odds-snapshots` (never to main).
# Uses a temporary git worktree, so the current checkout is untouched. Creates the branch on first use.
#   bash analysis/push_snapshot.sh <dir with odds_*.parquet / matches_*.parquet>
set -uo pipefail
SRC="$1"
BR="odds-snapshots"
ls "$SRC"/*.parquet > /dev/null 2>&1 || { echo "nothing to push in $SRC"; exit 0; }
for attempt in 1 2 3 4 5; do
  TMP="$(mktemp -d)"
  git fetch -q origin "$BR" 2> /dev/null
  if git rev-parse -q --verify "refs/remotes/origin/$BR" > /dev/null; then
    git worktree add -q --detach "$TMP" "origin/$BR"
  else
    git worktree add -q --detach "$TMP"
    (cd "$TMP" && git checkout -q --orphan tmp-snapshots && git rm -rqf . > /dev/null && \
      printf '%s\n' "# odds-snapshots" "" \
        "Data only. Morning Nesine odds kept by the daily scan (analysis/keep_snapshot.py), one pair of files per" \
        "run in snapshots/: odds_<capture time>.parquet and matches_<capture time>.parquet. Read by" \
        "analysis/movement.py. Never merged into main." > README.md && git add README.md)
  fi
  mkdir -p "$TMP/snapshots"
  cp "$SRC"/*.parquet "$TMP/snapshots/"
  (cd "$TMP" && git add snapshots && \
    git -c commit.gpgsign=false commit -q -m "odds snapshot $(date -u +%Y-%m-%dT%H:%MZ)" && \
    git push -q origin "HEAD:refs/heads/$BR")
  ok=$?
  git worktree remove --force "$TMP" > /dev/null 2>&1
  if [ $ok -eq 0 ]; then
    echo "pushed $(ls "$SRC"/*.parquet | wc -l) files to $BR"
    exit 0
  fi
  sleep $((2 ** attempt))
done
echo "could not push the snapshot to $BR (the scan itself is not affected)"
exit 0
