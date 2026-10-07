"""Freshness check: fail if the results/snapshot jobs have not succeeded recently (archive is ~4.5 days)."""

from __future__ import annotations

import sys
from datetime import datetime

from .config import load, now_utc
from .storage import read_log


def succeeded(runs):
    """ok and partial runs count as successful (partial = a few failed items, retried by the next run).
    Rows logged before the status column existed: no errors = success."""
    errors_ok = runs["errors"].replace("", "0").astype(int) == 0
    if "status" not in runs:
        return errors_ok
    status = runs["status"].fillna("")
    return status.isin(["ok", "partial"]) | ((status == "") & errors_ok)


def last_success(runs, job: str) -> datetime | None:
    ok = runs[(runs["job"] == job) & succeeded(runs)] if not runs.empty else runs
    if ok.empty:
        return None
    return max(datetime.fromisoformat(t.replace("Z", "+00:00")) for t in ok["run_at"])


def check() -> int:
    cfg = load("pipeline")["health"]
    runs = read_log("runs")
    now = now_utc()
    if runs.empty:
        print("no runs logged yet (pipeline not started) - nothing to check")
        return 0
    first_run = min(datetime.fromisoformat(t.replace("Z", "+00:00")) for t in runs["run_at"])
    problems = []
    for job, limit in (("results", cfg["max_hours_without_results"]), ("snapshot", cfg["max_hours_without_snapshot"])):
        if not limit:  # check switched off (e.g. snapshots paused)
            print(f"{job}: check off")
            continue
        last = last_success(runs, job) or first_run
        age = (now - last).total_seconds() / 3600 if last else None
        print(f"{job}: last successful run {last} ({'never' if age is None else f'{age:.1f} h ago'}), limit {limit} h")
        if age is None or age > limit:
            problems.append(f"no successful {job} run in {limit} h")
    if problems:
        print("ALERT: " + "; ".join(problems) + ". Mackolik keeps only ~4.5 days: fix within 2 days or data is lost.",
              file=sys.stderr)
        return 1
    return 0
