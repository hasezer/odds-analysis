#!/usr/bin/env bash
# Start the next run of the data-writer group after a backfill job. Runs of the group wait in a queue of one: a
# newer waiting run cancels the older one. So:
# - a results run is already waiting or running: start nothing (it continues the backfill when it is done);
# - after 05:00 UTC and today's results run has not succeeded yet (at most 2 tries a day): start the results run
#   (it continues the backfill);
# - otherwise: start the next backfill job.
set -euo pipefail
today=$(date -u +%F)
runs=$(gh run list --workflow results.yml --limit 20 --json status,conclusion,createdAt)
waiting=$(jq '[.[] | select(.status != "completed")] | length' <<<"$runs")
tries_today=$(jq --arg t "${today}T04:00:00Z" '[.[] | select(.createdAt >= $t)] | length' <<<"$runs")
done_today=$(jq --arg t "${today}T04:00:00Z" '[.[] | select(.createdAt >= $t and .conclusion == "success")] | length' <<<"$runs")
if [ "$waiting" != 0 ]; then
  echo "a results run is waiting or running: it continues the backfill when it is done"
elif [ "$(date -u +%H%M)" -ge 0500 ] && [ "$done_today" = 0 ] && [ "$tries_today" -lt 2 ]; then
  echo "today's results run is due: starting it (it continues the backfill afterwards)"
  gh workflow run results.yml --ref main
else
  gh workflow run backfill.yml --ref main
fi
