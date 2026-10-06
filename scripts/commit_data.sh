#!/usr/bin/env bash
# Commit data/ (and exports/, reports/ when present) to main, rebasing on concurrent pushes.
set -euo pipefail
msg="${1:-data update}"
git config user.name "odds-bot"
git config user.email "odds-bot@users.noreply.github.com"
for path in data exports reports; do
  if [ -e "$path" ]; then git add -A "$path"; fi
done
if git diff --cached --quiet; then
  echo "nothing to commit"
  exit 0
fi
git commit -q -m "$msg"
for delay in 2 4 8 16 32; do
  if git pull -q --rebase origin main && git push -q origin HEAD:main; then
    echo "pushed: $msg"
    exit 0
  fi
  echo "push failed, retrying in ${delay}s"
  sleep "$delay"
done
echo "could not push data commit" >&2
exit 1
