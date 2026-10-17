"""Own play: what a year of betting the strategy book looks like for the owner (money, losing runs, bankroll).

Each plan is replayed on every match since 1 July 2025, which is after the 2024/25 + 2024 'find' seasons, at
Nesine's closing odds: single bets with the tracker's own code (tracker.replay: the same criteria the daily scan
uses); system coupons from the system study's own weekend coupons (six_sys_study.py), whose leagues were chosen
from earlier seasons only (the stored coupon's league list used every season, so replaying it on past seasons
would flatter it). Stakes: 1 stake per pick (a score pack is 1 stake split over its scores); a system coupon counts
as 1 stake for the whole coupon (582 combinations of 3, 4 and 5 for 10 games). Caveat: these seasons were also the
strategies' confirm and exam seasons, so the replay is somewhat flattering; the tracker shows the real picks.
For each plan:
- the real record: picks a month, hit rate, average odds, return per 100 (and without its single best result),
  profit per month, losing months, the longest losing run and the deepest fall from a high point (drawdown);
- 5,000 simulated years: picks drawn at random from the real record, the real number of picks a month: the median
  year, a bad year (1 in 10), a good year (1 in 10), the chance of ending the year ahead, the longest losing run,
  and the bankroll needed to ride out the deepest fall in 19 years out of 20.
The Goals coupon is shown twice: since July 2025, and over every season since August 2024 (one 512x weekend in
~110 decides it, so the longer record gives the fairer chance of hitting one).
Writes output/own_play.xlsx and output/own_play.png.

    python analysis/own_play.py
"""
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import yaml  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import tracker  # noqa: E402
from htft_data import CACHE  # noqa: E402

START = "2025-07-01"
YEARS = 5000
PLANS = {
    "Your 10-game system: Goals coupon": lambda s: s["id"] == "system-goals-coupon",
    "Your old 6+ coupon (comparison)": lambda s: s["id"] == "system-6plus-lowest",
    "Portugal draw & over 2.5": lambda s: s["id"] == "money-POR-1-1X2_AND_OU|2.5|X&OVER",
    "Both teams score in both halves": lambda s: s["id"].startswith("bb-"),
    "High-scoring score pack (3-2, 2-3, 3-3, 2-4, 4-2)": lambda s: s["id"] == "pack-CORRECT_SCORE-high-3-5",
    "Correct-score bands and rules": lambda s: s["id"].startswith("cs-"),
    "Every single-bet strategy, 1 stake each": lambda s: s["kind"] != "system",
}
GOALS_ALL = "Your 10-game system: Goals coupon, all seasons since Aug 2024"
STUDY = {"system-goals-coupon": ("Portugal first, then 8 best 'draw & over 2.5' leagues, lowest odds",
                                 "draw & over 2.5"),
         "system-6plus-lowest": ("10 lowest 6+ odds", "6+ goals")}


def study_coupons(sid, since=START):
    """The system study's own weekend coupons since `since` (leagues chosen from earlier seasons only; 2024/25 used
    its own ranking, the study's one in-sample season)."""
    C = pd.read_parquet(CACHE / "six_sys_study_coupons.parquet")
    strat, leg = STUDY[sid]
    C = C[(C["windows"] == "weekend / midweek") & (C["window kind"] == "weekend") & (C["strategy"] == strat)
          & (C["leg"] == leg) & (pd.to_datetime(C["first day"]) >= since)]
    st, ret = C[["stake 3", "stake 4", "stake 5"]].sum(axis=1), C[["return 3", "return 4", "return 5"]].sum(axis=1)
    return pd.DataFrame({"when": pd.to_datetime(C["first day"]), "odds": C["avg odds"], "won": (ret > 0).astype(int),
                         "bet": "coupon: " + C["hits"].astype(str) + " of " + C["legs"].astype(str) + " won",
                         "profit": ret / st - 1})


def replay():
    book = yaml.safe_load((HERE / "strategies.yaml").read_text())["strategies"]
    used = [dict(s, first_added=str(pd.Timestamp(START) - pd.Timedelta(days=1))[:10], retired_on=None)
            for s in book if any(f(s) for f in PLANS.values())]
    honest = (CACHE / "six_sys_study_coupons.parquet").exists()
    if not honest:
        print("cache/six_sys_study_coupons.parquet missing (run six_sys_study.py): coupons replayed from the stored "
              "league list instead, which flatters them")
    m, o = tracker.finished_since(pd.Timestamp(START, tz="UTC"))
    picks, sysr = tracker.replay([s for s in used if not (honest and s["kind"] == "system")], m, o)
    rows = []
    for plan, f in PLANS.items():
        ids = {s["id"] for s in used if f(s)}
        if honest and ids <= set(STUDY):
            rows += [study_coupons(i).assign(plan=plan) for i in ids]
        elif any(s["kind"] == "system" for s in used if s["id"] in ids):
            g = sysr[sysr["strategy"].isin(ids)]
            rows.append(pd.DataFrame({"plan": plan, "when": pd.to_datetime(g["weekend"]),
                                      "bet": "coupon: " + g["hits"].astype(str) + " of " + g["games"].astype(str)
                                             + " won", "odds": np.nan, "won": (g["system_return"] > 0).astype(int),
                                      "profit": g["system_return"] / g["system_stake"] - 1}))
        else:
            g = picks[picks["strategy"].isin(ids) & picks["closing_odds"].notna()]
            g = g.drop_duplicates(["match_id", "bet"])               # one stake per match and bet across strategies
            rows.append(pd.DataFrame({"plan": plan, "when": g["kickoff"], "bet": g["bet"], "league": g["league"],
                                      "odds": g["closing_odds"], "won": g["hit"], "profit": g["return"]}))
    if honest:
        rows.append(study_coupons("system-goals-coupon", "2024-07-01").assign(plan=GOALS_ALL))
    order = list(PLANS)
    order.insert(1, GOALS_ALL)
    b = pd.concat(rows, ignore_index=True)
    b["order"] = b["plan"].map({p: i for i, p in enumerate(order)})
    return b.sort_values(["order", "when"]).drop(columns="order").reset_index(drop=True)


def runs(won):
    """Longest run of losing picks."""
    w = np.r_[1, np.asarray(won, int), 1]
    hits = np.flatnonzero(w)
    return int((np.diff(hits) - 1).max()) if len(hits) > 1 else len(won)


def drawdown(profit):
    c = np.r_[0, np.cumsum(profit)]
    return float((np.maximum.accumulate(c) - c).max())


def simulate(g, months, rng):
    lam = len(g) / months
    p, w = g["profit"].to_numpy(float), g["won"].to_numpy(int)
    out = np.empty((YEARS, 5))
    paths = np.empty((min(YEARS, 200), 13))
    for i in range(YEARS):
        k = rng.poisson(lam, 12)
        idx = rng.integers(0, len(p), k.sum())
        pp = p[idx]
        mon = np.bincount(np.repeat(np.arange(12), k), weights=pp, minlength=12)
        out[i] = [pp.sum(), drawdown(pp), runs(w[idx]), mon.min(), (mon > 0).sum()]
        if i < len(paths):
            paths[i] = np.r_[0, np.cumsum(mon)]
    return pd.DataFrame(out, columns=["profit", "drawdown", "losing run", "worst month", "months ahead"]), paths


def summarise(b):
    rng = np.random.default_rng(1)
    S, M, P = [], [], {}
    for plan, g in b.groupby("plan", sort=False):
        if not len(g):
            continue
        months = max((g["when"].max() - min(g["when"].min(), pd.Timestamp(START))).days / 30.44, 1.0)
        mon = g.groupby(g["when"].dt.to_period("M")).agg(picks=("won", "size"), won=("won", "sum"),
                                                          profit=("profit", "sum")).reset_index()
        mon.insert(0, "plan", plan)
        mon["when"] = mon["when"].astype(str)
        M.append(mon)
        sim, P[plan] = simulate(g, months, rng)
        S.append({"plan": plan, "picks": len(g), "picks a month": len(g) / months,
                  "hit %": g["won"].mean() * 100, "average odds": g["odds"].mean(),
                  "return per 100": g["profit"].mean() * 100,
                  "return per 100 without its best result": (g["profit"].sum() - g["profit"].max())
                                                             / max(len(g) - 1, 1) * 100,
                  "profit (stakes)": g["profit"].sum(),
                  "losing months %": (mon["profit"] < 0).mean() * 100,
                  "longest losing run": runs(g["won"]), "deepest fall (stakes)": drawdown(g["profit"]),
                  "year: median result": sim["profit"].median(), "year: bad (1 in 10)": sim["profit"].quantile(0.1),
                  "year: good (1 in 10)": sim["profit"].quantile(0.9),
                  "chance to end the year ahead %": (sim["profit"] > 0).mean() * 100,
                  "year: longest losing run (1 in 20)": sim["losing run"].quantile(0.95),
                  "bankroll needed (stakes, 19 years in 20)": sim["drawdown"].quantile(0.95)})
    return pd.DataFrame(S), pd.concat(M, ignore_index=True), P


def chart(S, P, path):
    n = len(S)
    fig, axes = plt.subplots((n + 1) // 2, 2, figsize=(13, 3.4 * ((n + 1) // 2)))
    for ax, (_, r) in zip(axes.flat, S.iterrows()):
        paths = P[r["plan"]]
        for row in paths[:60]:
            ax.plot(range(13), row, color="#9aa5b1", lw=0.6, alpha=0.6)
        for q, lw in ((0.1, 1.5), (0.5, 2.5), (0.9, 1.5)):
            ax.plot(range(13), np.quantile(paths, q, axis=0), color="#1f4e79", lw=lw)
        ax.axhline(0, color="black", lw=0.8)
        ax.set_title(f"{r['plan']}\n{r['picks a month']:.0f} a month, return {r['return per 100']:+.0f} per 100 "
                     f"({r['return per 100 without its best result']:+.0f} without its best result), bankroll for a "
                     f"bad year {r['bankroll needed (stakes, 19 years in 20)']:.0f} stakes", fontsize=9)
        ax.set_xlabel("month of the year")
        ax.set_ylabel("profit (stakes)")
    for ax in list(axes.flat)[n:]:
        ax.axis("off")
    fig.suptitle("A simulated year of each plan (grey: 60 possible years; blue: middle and 1-in-10 bad / good years)",
                 fontsize=12)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def main():
    b = replay()
    S, M, P = summarise(b)
    out = HERE / "output" / "own_play.xlsx"
    out.parent.mkdir(exist_ok=True)
    with pd.ExcelWriter(out) as xw:
        S.round(1).to_excel(xw, sheet_name="Summary", index=False)
        M.round(2).to_excel(xw, sheet_name="By month", index=False)
        b.assign(when=b["when"].astype(str)).round(3).to_excel(xw, sheet_name="Every pick", index=False)
    chart(S, P, out.with_suffix(".png"))
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)
    print(S.round(1).T.to_string())
    return S, M, b


if __name__ == "__main__":
    main()
