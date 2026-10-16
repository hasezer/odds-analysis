"""Backtest of the owner's coupon: pick 10 games a day, play a system 3-4-5 (all trebles, four-folds and five-folds:
120 + 210 + 252 = 582 combos, 1 unit each) at Nesine's closing odds. Also 3-only / 4-only / 5-only systems.

A combo pays the product of its legs' odds only when all its legs win: payout(size k) = e_k(odds of the winning legs)
(elementary symmetric polynomial). Days: every Turkey date with enough candidate games for the picking rule.
Picking rules (pre-match information only):
  most likely      10 lowest 6+ odds of the day
  value band       6+ odds 7.50-9.00 (best value per leg in the 6+ ladder), lowest odds first
  other score      10 cheapest 'other' correct-score odds (close to tipster rule 9b)
  random           10 random games with 6+ odds (seeded) - baseline
  most likely x over 3.5 / over 4.5 / 1st-half over 1.5   same 10 games as 'most likely', different leg
Writes cache/six_sys_days.parquet (one row per day x rule) and cache/six_sys_summary.parquet.
"""
from math import comb
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import six_sys_data as sd  # noqa: E402
from htft_data import CACHE  # noqa: E402

SIZES = (3, 4, 5)
N = 10
SEASON = {"A": "2024/25", "B": "2025/26", "C": "2026/27"}


def esym(odds, kmax=5):
    e = np.zeros(kmax + 1)
    e[0] = 1.0
    for o in odds:
        for k in range(kmax, 0, -1):
            e[k] += e[k - 1] * o
    return e


def picks(day, rule, rng):
    d = day[day["o6"].notna()]
    if rule == "most likely":
        return d.nsmallest(N, "o6")
    if rule == "value band":
        return d[(d["o6"] >= 7.5) & (d["o6"] <= 9.0)].nsmallest(N, "o6")
    if rule == "other score":
        return d[d["odds_other"].notna()].nsmallest(N, "odds_other")
    if rule == "random":
        return d.sample(min(N, len(d)), random_state=int(rng.integers(1e9))) if len(d) >= N else d.iloc[:0]
    raise ValueError(rule)


LEGS = {"6+": ("o6", "y6"), "over 3.5": ("odds_o35", "y_o35"), "over 4.5": ("odds_o45", "y_o45"),
        "1st-half over 1.5": ("odds_ht15", "y_ht15")}
RULES = [("most likely", "6+"), ("value band", "6+"), ("other score", "6+"), ("random", "6+"),
         ("most likely", "over 3.5"), ("most likely", "over 4.5"), ("most likely", "1st-half over 1.5")]


def run():
    S = sd.build()
    rng = np.random.default_rng(42)
    rows = []
    for date, day in S.groupby("date"):
        for rule, leg in RULES:
            p = picks(day, rule, rng)
            oc, yc = LEGS[leg]
            p = p[p[oc].notna()]
            if len(p) < N:
                continue
            odds, hits = p[oc].to_numpy(), p[yc].to_numpy()
            e = esym(odds[hits == 1])
            row = {"date": date, "season": SEASON[p["per"].iloc[0]], "rule": rule, "leg": leg, "hits": int(hits.sum()),
                   "avg odds": odds.mean(),
                   "expected hits (calibrated)": p["p6_cal"].sum() if leg == "6+" else np.nan}
            for k in SIZES:
                row[f"stake {k}"] = comb(N, k)
                row[f"return {k}"] = e[k]
            row["stake 3-4-5"] = sum(comb(N, k) for k in SIZES)
            row["return 3-4-5"] = sum(e[k] for k in SIZES)
            rows.append(row)
    days = pd.DataFrame(rows)
    out = []
    for (rule, leg), g in days.groupby(["rule", "leg"], sort=False):
        for season in ["all"] + list(SEASON.values()):
            x = g if season == "all" else g[g["season"] == season]
            if not len(x):
                continue
            r = {"rule": rule, "leg": leg, "season": season, "days": len(x), "avg odds per leg": x["avg odds"].mean(),
                 "avg hits of 10": x["hits"].mean(), "days with 3+ hits %": (x["hits"] >= 3).mean() * 100,
                 "days with 4+ hits %": (x["hits"] >= 4).mean() * 100,
                 "days with 5+ hits %": (x["hits"] >= 5).mean() * 100}
            for s in ("3", "4", "5", "3-4-5"):
                st, ret = x[f"stake {s}"].sum(), x[f"return {s}"].sum()
                r[f"system {s}: return per 100"] = (ret / st - 1) * 100
                r[f"system {s}: profitable days %"] = (x[f"return {s}"] > x[f"stake {s}"]).mean() * 100
            r["3-4-5: best day (x stake)"] = (x["return 3-4-5"] / x["stake 3-4-5"]).max()
            out.append(r)
    summ = pd.DataFrame(out)
    days.to_parquet(CACHE / "six_sys_days.parquet")
    summ.to_parquet(CACHE / "six_sys_summary.parquet")
    return days, summ


if __name__ == "__main__":
    days, summ = run()
    pd.set_option("display.width", 280)
    cols = ["rule", "leg", "season", "days", "avg odds per leg", "avg hits of 10", "days with 3+ hits %",
            "days with 4+ hits %", "days with 5+ hits %", "system 3: return per 100", "system 4: return per 100",
            "system 5: return per 100", "system 3-4-5: return per 100", "system 3-4-5: profitable days %",
            "3-4-5: best day (x stake)"]
    print(summ[cols].round(1).to_string())
