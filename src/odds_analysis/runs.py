"""Run status (ok / partial / failed), the failed-items log and the retry queue.

A run is
  failed  - it crashed, more than `max_failed_share` of its requests failed after all retries, or it saved
            nothing although there was something to save;
  partial - some requests or items failed (they are logged and retried by the next run);
  ok      - everything worked.

data/failed_items.csv : append-only history of every item that failed (audit).
data/retry_queue.csv  : items still waiting for a retry, rewritten by every run of the job.
"""

from __future__ import annotations

import pandas as pd

from .config import DATA, load
from .storage import append_log, read_log, write_log_frame

QUEUE_COLUMNS = ["job", "kind", "key", "match_id", "match_date", "kickoff_utc", "first_failed_utc",
                 "last_failed_utc", "attempts", "last_error"]


def run_status(*, calls: int, failed: int, saved: int, due: int, crashed: bool = False,
               item_errors: int = 0, max_failed_share: float | None = None) -> str:
    """saved = matches written by this run; due = matches it should have written (0 = nothing to do)."""
    if max_failed_share is None:
        max_failed_share = load("pipeline").get("runs", {}).get("max_failed_share", 0.20)
    if crashed:
        return "failed"
    if calls and failed / calls > max_failed_share:
        return "failed"
    if due and not saved:
        return "failed"
    if failed or item_errors:
        return "partial"
    return "ok"


def load_queue(job: str, root=DATA) -> list[dict]:
    q = read_log("retry_queue", root)
    if q.empty:
        return []
    return q[q["job"] == job].to_dict("records")


def save_queue(job: str, items: list[dict], root=DATA) -> None:
    """Replace this job's pending items (other jobs' items are kept)."""
    q = read_log("retry_queue", root)
    keep = q[q["job"] != job] if not q.empty else pd.DataFrame(columns=QUEUE_COLUMNS)
    new = pd.DataFrame([{c: it.get(c, "") for c in QUEUE_COLUMNS} for it in items], columns=QUEUE_COLUMNS)
    out = pd.concat([keep, new], ignore_index=True).reindex(columns=QUEUE_COLUMNS).fillna("")
    write_log_frame("retry_queue", out.sort_values(["job", "kind", "key"], kind="stable"), root)


class FailedItems:
    """Collects one run's failed items; `finish` logs them and rewrites the job's retry queue."""

    def __init__(self, job: str, run_at: str, root=DATA):
        self.job, self.run_at, self.root = job, run_at, root
        self.previous = {(i["kind"], str(i["key"])): i for i in load_queue(job, root)}
        self.items: dict[tuple[str, str], dict] = {}

    def add(self, kind: str, key, error: str, **info) -> None:
        prev = self.previous.get((kind, str(key)), {})
        self.items[(kind, str(key))] = {
            "job": self.job, "kind": kind, "key": str(key), **{k: "" if v is None else str(v) for k, v in info.items()},
            "first_failed_utc": prev.get("first_failed_utc") or self.run_at, "last_failed_utc": self.run_at,
            "attempts": int(prev.get("attempts") or 0) + 1, "last_error": str(error)[:300]}

    def pending(self, kind: str) -> list[dict]:
        """Items of the previous runs still waiting for a retry."""
        return [i for (k, _), i in self.previous.items() if k == kind]

    def finish(self) -> int:
        items = list(self.items.values())
        append_log("failed_items", [{"logged_at_utc": self.run_at, "job": i["job"], "kind": i["kind"],
                                     "key": i["key"], "match_id": i.get("match_id", ""),
                                     "attempts": i["attempts"], "error": i["last_error"]} for i in items], self.root)
        save_queue(self.job, items, self.root)
        return len(items)
