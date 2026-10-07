"""One-time conversion of the CSV tables collected before SCHEMA.md (2026-10-06 ->) into the Parquet tables.

Kept: our own odds snapshots (opening and later price changes) of the 26 leagues and the 45 selected markets,
matched to www.mackolik.com matches by iddaa code via the date listing. Not kept: post-match prices, results,
settlements, events and statistics - the results job collects those again from the new site. Afterwards the old
CSV tables are removed (git history keeps them).
"""

from __future__ import annotations

import logging
import shutil
from datetime import date, datetime

import pandas as pd

from . import ingest, store
from . import http as H
from .config import DATA
from .daily import list_matches, save_markets, save_matches
from .runs import FailedItems
from .storage import read_table

log = logging.getLogger(__name__)
LEGACY_TABLES = ("matches", "odds", "snapshots", "results", "events", "stats", "official", "settled")
LEGACY_LOGS = ("settlement_mismatches.csv", "event_score_mismatches.csv", "unmapped_markets.csv")


def legacy_present() -> bool:
    return any((DATA / "odds").glob("*.csv.gz"))


def migrate(c: H.MackolikClient) -> dict:
    odds = read_table("odds")
    stats = {"legacy_rows": len(odds), "converted_rows": 0, "matches": 0, "dates": [], "error_detail": []}
    if odds.empty:
        _remove_legacy()
        return stats
    odds = odds[odds["snapshot_type"].isin(["opening", "update"])]
    legacy_matches = read_table("matches")
    days = sorted({date.fromisoformat(d) for d in legacy_matches["date"].dropna()})
    failures = FailedItems("migrate", datetime.now().isoformat())
    matches = list_matches(c, days, failures, stats)
    failures.finish()
    if len(stats["dates"]) < len(days):
        raise RuntimeError(f"date listing failed for {len(days) - len(stats['dates'])} dates - migration not done, retried next run")
    by_code = {m["iddaa_event_code"]: m for m in matches if m["iddaa_event_code"]}
    save_matches([m for m in matches if m["iddaa_event_code"] in set(odds["event_code"])])
    rows_out = []
    for code, grp in odds.groupby("event_code"):
        m = by_code.get(str(code))
        if m is None:
            continue  # not one of the 26 leagues
        stats["matches"] += 1
        grp = grp.sort_values("snapshot_utc")
        seen = set()
        for snap, g in grp.groupby("snapshot_utc", sort=True):
            captured = datetime.fromisoformat(snap.replace("Z", "+00:00"))
            outcomes = [{"market_name": r["market_tr"], "market_type_id": r["market_type_id"], "selection": r["selection_tr"],
                         "odds": None if pd.isna(r["odds"]) else float(r["odds"]), "mbs": None if pd.isna(r["mbs"]) else int(r["mbs"]),
                         "highlight": False} for r in g.to_dict("records")]
            rows, outs = ingest.odds_rows_from(m, outcomes, price_type="opening_snapshot", captured_at=captured)
            save_markets(outs, m["season"])
            for r in rows:
                k = (r["market_type_id"], r["line"], r["handicap_home"], r["selection_key"])
                rows_out.append({**r, "price_type": "intraday_snapshot" if k in seen else "opening_snapshot",
                                 "season": m["season"], "league_id": m["league_id"]})
                seen.add(k)
    store.upsert("odds", rows_out)
    stats["converted_rows"] = len(rows_out)
    _remove_legacy()
    return stats


def _remove_legacy() -> None:
    for t in LEGACY_TABLES:
        for f in (DATA / t).glob("*.csv.gz"):
            f.unlink()
        d = DATA / t
        if d.exists() and not any(d.iterdir()):
            shutil.rmtree(d)
    for name in LEGACY_LOGS:
        (DATA / name).unlink(missing_ok=True)
