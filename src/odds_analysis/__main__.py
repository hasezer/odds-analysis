"""CLI: python -m odds_analysis {snapshot,results,health,build-db} [--raw-dir DIR]"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from . import http as H
from .config import iso, now_utc
from .storage import append_log


def _run_job(job: str, raw_dir: Path | None, limit: int | None = None) -> int:
    started = time.monotonic()
    run_at = iso(now_utc())
    stats: dict = {}
    crash = None
    with H.MackolikClient(raw_dir=raw_dir) as client:
        try:
            if job == "snapshot":
                from .snapshot import run
                stats = run(client)
            else:
                from .results import run
                stats = run(client, limit=limit)
        except Exception as exc:  # noqa: BLE001
            logging.exception("job crashed")
            crash = repr(exc)
        requests = client.requests
    errors = stats.get("errors", 0) + (1 if crash else 0)
    detail = stats.get("error_detail", [])[:20] + ([crash] if crash else [])
    append_log("runs", [{
        "run_at": run_at,
        "job": job,
        "dates": " ".join(stats.get("dates", [])),
        "matches": stats.get("fetched", stats.get("final", 0)),
        "errors": errors,
        "requests": requests,
        "duration_s": round(time.monotonic() - started),
        "summary": json.dumps({k: v for k, v in stats.items() if k not in ("dates", "error_detail")}, ensure_ascii=False),
        "error_detail": " || ".join(detail)[:2000],
    }])
    print(json.dumps({k: v for k, v in stats.items() if k != "dates"}, ensure_ascii=False, indent=1))
    if errors:
        print(f"{errors} error(s): " + " || ".join(detail), file=sys.stderr)
    return 1 if errors else 0


def _settle(days: int, all_dates: bool) -> int:
    from datetime import timedelta

    from .config import DATA, TR
    from .settle import settle_dates

    started = time.monotonic()
    run_at = iso(now_utc())
    if all_dates:
        dates = sorted(p.name[:10] for p in (DATA / "results").glob("*.csv.gz"))
    else:
        today = now_utc().astimezone(TR).date()
        dates = [(today - timedelta(days=d)).isoformat() for d in range(days, -1, -1)]
    try:
        stats = settle_dates(dates)
        error = None
    except Exception as exc:  # noqa: BLE001
        logging.exception("settlement crashed")
        stats, error = {}, repr(exc)
    append_log("runs", [{"run_at": run_at, "job": "settle", "dates": " ".join(stats.get("dates", [])),
                         "matches": "", "errors": 1 if error else 0, "requests": 0,
                         "duration_s": round(time.monotonic() - started),
                         "summary": json.dumps({k: v for k, v in stats.items() if k != "dates"}),
                         "error_detail": error or ""}])
    print(json.dumps(stats, indent=1))
    return 1 if error else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="odds_analysis")
    ap.add_argument("command", choices=["snapshot", "results", "settle", "health", "build-db"])
    ap.add_argument("--days", type=int, default=7, help="settle: match dates from today-N to today")
    ap.add_argument("--all", action="store_true", help="settle: every date that has results")
    ap.add_argument("--raw-dir", type=Path, default=None, help="save raw responses here (Actions artifact)")
    ap.add_argument("--limit", type=int, default=None, help="results: process at most N matches (testing)")
    ap.add_argument("--db", type=Path, default=Path("odds.sqlite"))
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if args.command in ("snapshot", "results"):
        return _run_job(args.command, args.raw_dir, args.limit)
    if args.command == "settle":
        return _settle(args.days, args.all)
    if args.command == "health":
        from .health import check
        return check()
    from .build_db import build
    build(args.db)
    return 0


if __name__ == "__main__":
    sys.exit(main())
