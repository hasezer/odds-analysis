"""Keep the morning odds the daily scan collects (they used to be thrown away with the scan's copy of data/).

The daily scan runs the project's own snapshot command on a copy of data/ (ODDS_DATA_DIR) and scans it. This script
takes the prices that run captured (data/odds/.../date=<today>/, captured during this run) plus the kick-off times
of those matches and writes two small files that analysis/push_snapshot.sh pushes to the `odds-snapshots` branch:
    <out>/odds_<YYYY-MM-DDTHHMMZ>.parquet      one row per selection and price at capture time
    <out>/matches_<YYYY-MM-DDTHHMMZ>.parquet   match_id, league, season, kick-off, teams
Later, analysis/movement.py compares these morning prices with Nesine's closing prices (results / backfill jobs).

    python analysis/keep_snapshot.py <scan data dir> <out dir> [--since ISO-UTC]
"""
import argparse
from pathlib import Path
import sys

import pandas as pd

ODDS_COLS = ["match_id", "market_type_id", "market_key", "line", "handicap_home", "handicap_away", "selection_key",
             "odds", "captured_at_utc", "minutes_before_kickoff"]
MATCH_COLS = ["match_id", "league_id", "season", "kickoff_utc", "home_team_id", "away_team_id"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data_dir")
    ap.add_argument("out_dir")
    ap.add_argument("--since", help="keep only prices captured at or after this UTC time (the run's start)")
    a = ap.parse_args()
    data, out = Path(a.data_dir), Path(a.out_dir)
    files = sorted(data.glob("odds/season=*/league=*/date=*/*.parquet"))
    if not files:
        print("no snapshot files found")
        return 1
    o = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    o["captured_at_utc"] = pd.to_datetime(o["captured_at_utc"], utc=True)
    since = pd.Timestamp(a.since).tz_convert("UTC") if a.since else o["captured_at_utc"].max().normalize()
    o = o[o["captured_at_utc"] >= since]
    if o.empty:
        print(f"no prices captured since {since}")
        return 1
    o = o[[c for c in ODDS_COLS if c in o.columns]].drop_duplicates(
        ["match_id", "market_type_id", "line", "handicap_home", "handicap_away", "selection_key", "captured_at_utc"])
    m = pd.concat([pd.read_parquet(f) for f in data.glob("matches/season=*/league=*/*.parquet")], ignore_index=True)
    m = m[m["match_id"].isin(o["match_id"])][[c for c in MATCH_COLS if c in m.columns]].drop_duplicates("match_id")
    stamp = o["captured_at_utc"].min().strftime("%Y-%m-%dT%H%MZ")
    out.mkdir(parents=True, exist_ok=True)
    o.to_parquet(out / f"odds_{stamp}.parquet", compression="zstd", index=False)
    m.to_parquet(out / f"matches_{stamp}.parquet", compression="zstd", index=False)
    print(f"kept {len(o):,} prices for {o['match_id'].nunique()} matches captured {stamp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
