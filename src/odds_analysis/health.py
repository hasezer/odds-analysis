"""Freshness check: fail if the results/snapshot jobs have not succeeded recently (archive is ~4.5 days)."""

from __future__ import annotations

import sys
from datetime import datetime

from .config import load, now_utc
from .storage import read_log


def last_success(runs, job: str) -> datetime | None:
    ok = runs[(runs["job"] == job) & (runs["errors"].astype(int) == 0)] if not runs.empty else runs
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
