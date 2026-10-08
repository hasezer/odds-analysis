"""GitHub Actions minutes: what this repository used this month, and whether the backfill may run.

GitHub bills every job rounded up to the next minute. The used minutes are counted from the repository's own
workflow runs and their jobs (GitHub API, GITHUB_TOKEN with actions: read) and cached in
data/actions_minutes.csv, so each finished run is fetched only once.

config/backfill.yaml: monthly_minutes (the plan's included minutes) and daily_reserve (minutes kept for the daily
jobs). The backfill pauses when monthly_minutes - used < daily_reserve.
"""

from __future__ import annotations

import logging
import math
import os
from datetime import datetime, timedelta, timezone

import httpx
import pandas as pd

from .config import DATA, load
from .storage import read_log, write_log_frame

log = logging.getLogger(__name__)
API = "https://api.github.com"
LEDGER = "actions_minutes"
COLUMNS = ["run_id", "workflow", "created_at", "minutes"]


def _client() -> httpx.Client | None:
    token, repo = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        return None
    return httpx.Client(base_url=f"{API}/repos/{repo}", timeout=30,
                        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})


def job_minutes(jobs: list[dict]) -> int:
    """Billable minutes of a run: every job rounded up to a whole minute (skipped jobs cost nothing)."""
    total = 0
    for j in jobs:
        if not j.get("started_at") or not j.get("completed_at"):
            continue
        a = datetime.fromisoformat(j["started_at"].replace("Z", "+00:00"))
        b = datetime.fromisoformat(j["completed_at"].replace("Z", "+00:00"))
        secs = (b - a).total_seconds()
        if secs > 0:
            total += math.ceil(secs / 60)
    return total


def refresh_ledger(now: datetime | None = None, root=DATA) -> pd.DataFrame:
    """Add this month's finished runs that are not in data/actions_minutes.csv yet."""
    now = now or datetime.now(timezone.utc)
    ledger = read_log(LEDGER, root)
    if ledger.empty:
        ledger = pd.DataFrame(columns=COLUMNS)
    c = _client()
    if c is None:
        log.info("no GitHub token: minutes ledger not refreshed")
        return ledger
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    known = set(ledger["run_id"].astype(str))
    new = []
    with c:
        page = 1
        while True:
            r = c.get("/actions/runs", params={"created": f">={month_start.date().isoformat()}", "status": "completed",
                                               "per_page": 100, "page": page})
            r.raise_for_status()
            runs = r.json().get("workflow_runs") or []
            for run in runs:
                if str(run["id"]) in known:
                    continue
                jr = c.get(f"/actions/runs/{run['id']}/jobs", params={"per_page": 100})
                jr.raise_for_status()
                new.append({"run_id": str(run["id"]), "workflow": run.get("name"), "created_at": run["created_at"],
                            "minutes": job_minutes(jr.json().get("jobs") or [])})
            if len(runs) < 100:
                break
            page += 1
    if new:
        ledger = pd.concat([ledger, pd.DataFrame(new)], ignore_index=True)
        cutoff = (month_start - timedelta(days=62)).isoformat()  # keep ~2 months
        ledger = ledger[ledger["created_at"] >= cutoff].sort_values("created_at")
        write_log_frame(LEDGER, ledger, root)
    return ledger


def used_this_month(ledger: pd.DataFrame, now: datetime) -> int:
    if ledger.empty:
        return 0
    month = now.strftime("%Y-%m")
    return int(pd.to_numeric(ledger.loc[ledger["created_at"].str[:7] == month, "minutes"]).sum())


def daily_usage(ledger: pd.DataFrame, now: datetime, days: int = 7) -> float | None:
    """Average minutes per day of every workflow except the backfill over the last `days` full days."""
    if ledger.empty:
        return None
    since = (now - timedelta(days=days)).isoformat()
    recent = ledger[(ledger["created_at"] >= since) & (ledger["workflow"] != "Backfill")]
    if recent.empty:
        return None
    return round(pd.to_numeric(recent["minutes"]).sum() / days, 1)


def repo_is_public() -> bool:
    """True only when the GitHub API says so (public repositories use Actions minutes for free); False when the
    repository is private or its visibility cannot be read."""
    c = _client()
    if c is None:
        return False
    try:
        with c:
            r = c.get("")
            return r.status_code == 200 and r.json().get("private") is False
    except httpx.HTTPError:
        return False


def allowance(now: datetime | None = None, running_minutes: float = 0, root=DATA) -> dict:
    """{'used', 'left', 'reserve', 'ok'}: ok = the backfill may (continue to) run. Always ok while the repository
    is public (no minutes limit); the limit applies again as soon as it is private."""
    now = now or datetime.now(timezone.utc)
    cfg = load("backfill")
    ledger = refresh_ledger(now, root)
    used = used_this_month(ledger, now) + math.ceil(running_minutes)
    left = cfg["monthly_minutes"] - used
    public = repo_is_public()
    return {"used": used, "left": left, "reserve": cfg["daily_reserve"], "monthly": cfg["monthly_minutes"],
            "public": public, "ok": public or left >= cfg["daily_reserve"], "daily_usage_7d": daily_usage(ledger, now)}
