"""Which bet should each leg of a 10-game system be? For the games a 6+ player picks (the 10 lowest 6+ odds of each
betting window), the value of every bet Nesine offers: value per leg = average of (hit x odds) = what 1 unit returns.
A system multiplies leg values (a treble of 0.8 legs is worth 0.8^3 = 0.51), so the best leg is the one whose value is
closest to 1 - steadily, in every season.

Betting windows (Turkey dates): weekend = Friday to Monday, midweek = Tuesday to Thursday, or a single day.
Find on 2024/25, confirm on 2025/26, exam on 2026/27. Luck control: the same scan on 10 random games per window.
Writes cache/six_sys_legs.parquet.
"""
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rule_tester as rt  # noqa: E402
import six_sys_data as sd  # noqa: E402
from htft_data import CACHE  # noqa: E402

SEASON = {"A": "2024/25", "B": "2025/26", "C": "2026/27"}
N = 10


def window_ids(dates):
    """Turkey date -> (weekend|midweek window id, kind). Weekend = Fri..Mon (id = the Friday)."""
    d = pd.to_datetime(pd.Series(dates))
    dow = d.dt.dayofweek                                   # Mon=0 .. Sun=6
    back = np.where(dow >= 4, dow - 4, np.where(dow == 0, 3, dow - 1))   # days back to Fri (weekend) / Tue (midweek)
    start = d - pd.to_timedelta(back, unit="D")
    kind = np.where((dow >= 4) | (dow == 0), "weekend", "midweek")
    return (start.dt.strftime("%Y-%m-%d") + " " + kind).to_numpy(), kind


def pick_lowest(S, by="window", n=N, col="o6"):
    d = S[S[col].notna()]
    g = d.groupby(by)
    ok = g[col].transform("size") >= n
    rank = g[col].rank(method="first")
    return d[ok & (rank <= n)]


def pick_random(S, by="window", n=N, seed=0):
    d = S[S["o6"].notna()].copy()
    d["_r"] = np.random.default_rng(seed).random(len(d))
    g = d.groupby(by)
    ok = g["o6"].transform("size") >= n
    return d[ok & (g["_r"].rank(method="first") <= n)]


def scan(W, ids, labs):
    rows = []
    sub = W.loc[W.index.intersection(ids)]
    for lab in labs:
        o = sub[lab]
        if o.notna().sum() < 100:
            continue
        try:
            y = rt.outcome(sub, lab)
        except TypeError:                                  # no score rule for this bet (e.g. corners)
            continue
        ok = o.notna() & y.notna()
        for p in ["all", "A", "B", "C"]:
            m = ok & ((sub["per"] == p) if p != "all" else True)
            if m.sum() < 20:
                continue
            r = y[m] * o[m]
            rows.append({"bet": lab, "season": SEASON.get(p, "all"), "legs": int(m.sum()), "hit %": y[m].mean() * 100,
                         "avg odds": o[m].mean(), "value per leg": r.mean(),
                         "z": (r.mean() - 1) / (r.std(ddof=1) / np.sqrt(m.sum())) if r.std() > 0 else np.nan})
    return pd.DataFrame(rows)


def run():
    S = sd.build()
    S["window"], S["wkind"] = window_ids(S["date"])
    W = rt.wide()
    per = S["per"]
    W = W.loc[W.index.intersection(S.index)]
    W["per"] = per.reindex(W.index)
    labs = [c for c in W.columns if "|" in c]
    out = []
    for name, ids in [("10 lowest 6+ odds per weekend/midweek", pick_lowest(S).index),
                      ("10 lowest 6+ odds per day", pick_lowest(S, by="date").index),
                      ("10 random games per weekend/midweek (luck control)", pick_random(S).index),
                      ("all matches", S.index)]:
        r = scan(W, ids, labs)
        r.insert(0, "games", name)
        out.append(r)
    res = pd.concat(out, ignore_index=True)
    res.to_parquet(CACHE / "six_sys_legs.parquet")
    return res


if __name__ == "__main__":
    res = run()
    pd.set_option("display.width", 250)
    for g, x in res.groupby("games", sort=False):
        w = x.pivot_table(index="bet", columns="season", values="value per leg")
        n = x[x["season"] == "all"].set_index("bet")[["legs", "hit %", "avg odds"]]
        w = w.join(n).sort_values("all", ascending=False)
        print("==", g)
        print(w.head(25).round(3).to_string())
