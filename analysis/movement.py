"""Odds movement: the morning prices the daily scan keeps (branch odds-snapshots) against Nesine's closing prices.

For every finished match with a kept morning price and a closing price (results / backfill jobs), per selection:
- move % = closing / morning - 1 (the earliest kept morning price of the match);
- groups: shortened by 5%+, about the same, drifted by 5%+ (and finer bands);
- per group and market: hit rate, the chance the morning odds implied, the chance the closing odds implied, and the
  return per 100 staked at the morning odds vs at the closing odds.
Questions: do prices move toward the result (closing more accurate than morning)? Does betting the morning price
beat the closing price (and for which markets)? Do selections that shorten win more than even the closing price says?
Prints a sample-size warning below MIN_MATCHES finished matches. Writes cache/movement.parquet.

    python analysis/movement.py
"""
import io
from pathlib import Path
import subprocess
import sys
import tarfile

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import load  # noqa: E402
from htft_data import CACHE  # noqa: E402

BRANCH = "origin/odds-snapshots"
MIN_MATCHES = 300
KEY = ["match_id", "market_key", "line", "selection_key"]


def snapshots():
    """All kept morning prices (git archive of the data branch; nothing is checked out)."""
    subprocess.run(["git", "fetch", "-q", "origin", "odds-snapshots"], check=False)
    raw = subprocess.run(["git", "archive", BRANCH, "snapshots"], capture_output=True, check=True).stdout
    odds = []
    with tarfile.open(fileobj=io.BytesIO(raw)) as tar:
        for mem in tar.getmembers():
            if mem.name.startswith("snapshots/odds_") and mem.name.endswith(".parquet"):
                odds.append(pd.read_parquet(io.BytesIO(tar.extractfile(mem).read())))
    o = pd.concat(odds, ignore_index=True)
    o = o[o["odds"].notna()].sort_values("captured_at_utc")
    first = o.groupby(KEY, dropna=False).first().reset_index()           # earliest kept price per selection
    return first.rename(columns={"odds": "morning_odds", "minutes_before_kickoff": "morning_minutes_before"})


def run():
    s = snapshots()
    f = load.flat()
    f = f[f["match_id"].isin(s["match_id"]) & f["closing_odds"].notna() & f["hit"].notna() & f["in_default_analysis"]]
    x = s.merge(f[KEY + ["closing_odds", "hit", "league_id"]], on=KEY, how="inner")
    x["move_pct"] = (x["closing_odds"] / x["morning_odds"] - 1) * 100
    x["group"] = pd.cut(x["move_pct"], [-1000, -5, 5, 1000], labels=["shortened 5%+", "about the same", "drifted 5%+"])
    x["band"] = pd.cut(x["move_pct"], [-1000, -15, -5, -1, 1, 5, 15, 1000],
                       labels=["-15% or more", "-15 to -5%", "-5 to -1%", "-1 to +1%", "+1 to +5%", "+5 to +15%",
                               "+15% or more"])
    n = x["match_id"].nunique()
    print(f"kept morning prices for {s['match_id'].nunique()} matches; finished with closing prices: {n}")
    if n == 0:
        print("nothing to compare yet: the kept matches have not finished (or have no closing prices) yet")
        return pd.DataFrame()
    if n < MIN_MATCHES:
        print(f"too few finished matches for conclusions (need {MIN_MATCHES}); tables below are only a preview")

    def summary(g):
        return pd.Series({
            "selections": len(g), "matches": g["match_id"].nunique(), "hit %": g["hit"].mean() * 100,
            "morning implied %": (1 / g["morning_odds"]).mean() * 100,
            "closing implied %": (1 / g["closing_odds"]).mean() * 100,
            "return per 100 at morning odds": ((g["hit"] * g["morning_odds"]).sum() / len(g) - 1) * 100,
            "return per 100 at closing odds": ((g["hit"] * g["closing_odds"]).sum() / len(g) - 1) * 100})
    by_group = x.groupby("group", observed=True).apply(summary).reset_index()
    by_band = x.groupby("band", observed=True).apply(summary).reset_index()
    by_market = x.groupby("market_key").apply(summary).reset_index().sort_values("selections", ascending=False)
    moved = x.groupby("market_key")["move_pct"].apply(lambda v: (v.abs() >= 1).mean() * 100).rename("% of prices moved")
    by_market = by_market.merge(moved.reset_index(), on="market_key")
    out = pd.concat([by_group.assign(table="by move"), by_band.assign(table="by move band"),
                     by_market.assign(table="by market")], ignore_index=True)
    out.to_parquet(CACHE / "movement.parquet")
    pd.set_option("display.width", 250)
    for t in ("by move", "by move band", "by market"):
        print(f"\n== {t}")
        print(out[out["table"] == t].dropna(axis=1, how="all").round(2).head(30).to_string(index=False))
    return out


if __name__ == "__main__":
    run()
