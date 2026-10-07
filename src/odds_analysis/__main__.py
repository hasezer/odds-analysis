"""CLI: python -m odds_analysis {snapshot,results,backfill,export,health,analyze} [--raw-dir DIR]

snapshot / results / export work on the SCHEMA.md tables (src/odds_analysis/daily.py, flat.py).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from . import http as H
from .config import iso, now_utc
from .runs import run_status
from .storage import append_log


def _run_job(job: str, raw_dir: Path | None, limit: int | None = None, full: bool | None = None) -> int:
    started = time.monotonic()
    run_at = iso(now_utc())
    stats: dict = {}
    crash = None
    with H.MackolikClient(raw_dir=raw_dir) as client:
        try:
            from . import daily, migrate

            if job in ("backfill", "results") and migrate.legacy_present():  # snapshots may be paused
                logging.info("migration: %s", migrate.migrate(client))
            if job == "backfill":
                from . import backfill

                stats = backfill.run(client)
                Path(".touched_partitions").write_text(json.dumps(stats.get("touched", [])))
            elif job == "snapshot":
                if migrate.legacy_present():  # one time: convert the pre-SCHEMA.md CSV tables
                    logging.info("migration: %s", migrate.migrate(client))
                stats = daily.snapshot_run(client, full=full)
            else:
                stats = daily.results_run(client, limit=limit)
                Path(".touched_partitions").write_text(json.dumps(stats.get("touched", [])))
        except Exception as exc:  # noqa: BLE001
            logging.exception("job crashed")
            crash = repr(exc)
    requests, calls, failed = client.requests, client.calls, client.failed
    # requests skipped because Mackolik was unreachable count as failed ones
    calls, failed = calls + stats.get("not_tried", 0), failed + stats.get("not_tried", 0)
    errors = stats.get("errors", 0) + (1 if crash else 0)
    detail = stats.get("error_detail", [])[:20] + ([crash] if crash else [])
    status = run_status(calls=calls, failed=failed, saved=stats.get("saved", 0), due=stats.get("due", 0),
                        crashed=crash is not None, item_errors=errors + stats.get("failed_items", 0))
    append_log("runs", [{
        "run_at": run_at,
        "job": job,
        "dates": " ".join(stats.get("dates", [])),
        "matches": stats.get("fetched", stats.get("final", 0)),
        "errors": errors,
        "requests": requests,
        "status": status,
        "calls": calls,
        "failed_requests": failed,
        "failed_items": stats.get("failed_items", 0),
        "duration_s": round(time.monotonic() - started),
        "summary": json.dumps({k: v for k, v in stats.items() if k not in ("dates", "error_detail")}, ensure_ascii=False),
        "error_detail": " || ".join(detail)[:2000],
    }])
    _log_run(job, run_at, status, requests, errors, stats.get("saved", 0), stats, detail)
    if stats.get("stopped_early"):
        Path(".continue_results").write_text("time budget reached\n")  # the workflow starts a follow-up run
    if job == "backfill" and status != "failed" and (stats.get("stopped") or stats.get("note")) \
            and not stats.get("paused") and not stats.get("finished") and not stats.get("quiet"):
        Path(".continue_backfill").write_text("job time limit reached\n")  # the workflow starts the next job
    print(json.dumps({k: v for k, v in stats.items() if k != "dates"}, ensure_ascii=False, indent=1))
    share = f"{failed}/{calls} requests failed after retries"
    if status == "failed":
        print(f"::error title={job} failed::{share}; saved {stats.get('saved', 0)} of {stats.get('due', 0)} due. "
              + " || ".join(detail)[:900], file=sys.stderr)
        return 1
    if status == "partial":  # visible in the Actions summary, but the run stays green; failed items are retried next run
        print(f"::warning title={job} partial::{share}; {stats.get('failed_items', 0)} item(s) logged in "
              "data/failed_items.csv and queued for the next run", file=sys.stderr)
    return 0


def _log_run(job: str, run_at: str, status: str, requests: int, errors: int, saved: int, stats: dict, detail: list) -> None:
    """The SCHEMA.md runs table (data/runs.csv stays the human-readable log)."""
    from . import store

    notes = json.dumps({k: v for k, v in stats.items() if k in ("matches_listed", "fetched", "listed", "final", "void",
                                                                   "deferred", "failed_items", "morebets_fallback",
                                                                   "no_odds", "cursor", "paused", "stopped")})
    store.upsert("runs", [{"run_id": f"{job}-{run_at}", "job": job, "started_at_utc": run_at,
                           "finished_at_utc": iso(now_utc()), "status": status, "requests": requests,
                           "errors": errors, "matches_saved": saved,
                           "notes": (notes + (" | " + " || ".join(detail)[:500] if detail else ""))}])


def _export(seasons: list[str]) -> int:
    """exports/<season>/: oranlar_<season>.xlsx + <league_id>.csv.gz for the current season of every league,
    the seasons the last results run touched, and --season values."""
    from datetime import date

    from . import flat
    from .leagues import competitions, season_for

    today = date.today()
    wanted: dict[str, set[str]] = {}
    for comp in competitions().values():
        if not comp.special:
            wanted.setdefault(season_for(comp, today), set()).add(comp.league["league_id"])
    touched = Path(".touched_partitions")
    for item in json.loads(touched.read_text()) if touched.exists() else []:
        lid, season = item.split(" ", 1)
        wanted.setdefault(season, set()).add(lid)
    for season in seasons:
        wanted.setdefault(season, set()).update(c.league["league_id"] for c in competitions().values())
    out = {}
    for season, lids in sorted(wanted.items()):
        for lid in sorted(lids):
            flat.rebuild(season, lid)
        out[season] = [str(p) for p in flat.export(season, sorted(lids))]
    print(json.dumps(out, indent=1, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="odds_analysis")
    ap.add_argument("command", choices=["snapshot", "results", "backfill", "export", "analyze", "health"])
    ap.add_argument("--raw-dir", type=Path, default=None, help="save raw responses here (Actions artifact)")
    ap.add_argument("--limit", type=int, default=None, help="results: process at most N matches (testing)")
    ap.add_argument("--full", action="store_true", default=None, help="snapshot: list every day ahead (default: morning run)")
    ap.add_argument("--season", action="append", default=[], help="export: also export this season (e.g. 2025/26)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if args.command in ("snapshot", "results", "backfill"):
        return _run_job(args.command, args.raw_dir, args.limit, args.full)
    if args.command == "export":
        return _export(args.season)
    if args.command == "analyze":
        from .analysis import analyze
        print(json.dumps(analyze(), indent=1))
        return 0
    from .health import check
    return check()


if __name__ == "__main__":
    sys.exit(main())
