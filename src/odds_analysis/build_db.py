"""Build a local SQLite database from data/ (on demand, never committed)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .config import DATA
from .storage import read_log, read_table

TABLES = ["matches", "odds", "snapshots", "results", "events", "stats", "official", "settled"]
LOGS = ["runs", "unmapped_markets", "score_mismatches", "event_score_mismatches", "settlement_mismatches",
        "extra_time_matches"]


def build(db_path: Path, root: Path = DATA) -> dict[str, int]:
    if db_path.exists():
        db_path.unlink()
    counts = {}
    with sqlite3.connect(db_path) as con:
        for t in TABLES:
            df = read_table(t, root=root)
            if not df.empty:
                df.to_sql(t, con, index=False)
                counts[t] = len(df)
        for name in LOGS:
            df = read_log(name, root=root)
            if not df.empty:
                df.to_sql(name, con, index=False)
                counts[name] = len(df)
        for t, cols in {"odds": "event_code, market_id", "official": "event_code", "results": "match_id",
                        "matches": "match_id", "events": "match_id", "settled": "match_id"}.items():
            if t in counts:
                con.execute(f"CREATE INDEX idx_{t} ON {t} ({cols})")
    for t, n in counts.items():
        print(f"{t:24s} {n:>10,} rows")
    print(f"-> {db_path}")
    return counts
