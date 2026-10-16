"""The owner's coupon, studied in depth: 10 games, system 3-4-5 (every treble, four-fold and five-fold, 582 combos at
1 unit). Which games and which bet per game give the best long-run result and the best chance of 3, 4, 5 hits?

One coupon per betting window (Turkey dates): weekend = Friday-Monday, midweek = Tuesday-Thursday (also per day).
Strategies = how the 10 games are chosen (pre-match odds only) x which bet each game gets (the "leg").
For every coupon: hits, the payout of each system size k = e_k(odds of the winning legs), stakes C(n, k).
Results per season (2024/25, 2025/26, 2026/27) with a bootstrap range over coupons.
Theory check: if every leg returns v per unit on average (v = hit rate x odds), a size-k combo returns v^k, so the
3-4-5 system returns (120 v^3 + 210 v^4 + 252 v^5) / 582.
Season view: 40 coupons drawn from the strategy's real coupons, 20,000 times -> chance to end a season up.
Writes cache/six_sys_study_coupons.parquet, cache/six_sys_study_summary.parquet, cache/six_sys_study_seasons.parquet.
"""
from math import comb
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import six_sys_data as sd  # noqa: E402
from htft_data import CACHE  # noqa: E402
from six_sys_backtest import esym  # noqa: E402
from six_sys_legs import window_ids  # noqa: E402

SEASON = {"A": "2024/25", "B": "2025/26", "C": "2026/27"}
N = 10
KMAX = 5
SYSTEMS = {"singles": (1,), "doubles": (2,), "system 3": (3,), "system 3-4-5": (3, 4, 5), "system 4-5": (4, 5),
           "system 5": (5,)}
LEGS = {"6+ goals": ("o6", "y6"), "draw & over 2.5": ("odds_xo", "y_xo"),
        "BTTS in both halves": ("odds_bb", "y_bb"), "half-time 1-1": ("odds_ht11", "y_ht11"),
        "half-time draw & 2+ goals": ("odds_htx15", "y_htx15"), "4-5 goals": ("odds_r45", "y_r45"),
        "over 4.5": ("odds_o45", "y_o45"), "over 3.5": ("odds_o35", "y_o35"),
        "1st-half over 1.5": ("odds_ht15", "y_ht15"), "BTTS": ("odds_btts", "y_btts"),
        "over 2.5": ("odds_o25", "y_o25")}


def system_value(v, sizes=(3, 4, 5), n=N):
    """Long-run return per unit staked when every leg returns v per unit."""
    return sum(comb(n, k) * v ** k for k in sizes) / sum(comb(n, k) for k in sizes)


# ---- how the games are chosen: each returns the chosen rows of one window with the leg's odds and outcome in
# columns _o / _y (empty if the window has too few games)
def with_leg(d, leg):
    oc, yc = LEGS[leg]
    return d.assign(_o=d[oc], _y=d[yc])


def lowest(col, lo=None, hi=None):
    def f(g, leg, rng):
        oc = LEGS[leg][0]
        d = g[g[col].notna() & g[oc].notna()]
        if lo is not None:
            d = d[(d[col] >= lo) & (d[col] <= hi)]
        return with_leg(d.nsmallest(N, col), leg) if len(d) >= N else d.iloc[:0]
    return f


def random_pick(g, leg, rng):
    d = g[g["o6"].notna() & g[LEGS[leg][0]].notna()]
    return with_leg(d.sample(N, random_state=int(rng.integers(1e9))), leg) if len(d) >= N else d.iloc[:0]


def portugal_only(g, leg, rng):
    oc = LEGS[leg][0]
    d = g[(g["league"] == "POR-1") & g[oc].notna()]
    return with_leg(d.nsmallest(N, oc), leg) if len(d) >= 3 else d.iloc[:0]


def portugal_first(rank_col="odds_xo", fill_leg="draw & over 2.5"):
    """Every Portugal game as 'draw & over 2.5', then the other leagues' games with the lowest rank_col, played as
    fill_leg, up to 10 legs."""
    def f(g, leg, rng):
        po = g[(g["league"] == "POR-1") & g["odds_xo"].notna()].nsmallest(N, "odds_xo")
        fo = LEGS[fill_leg][0]
        rest = g[(g["league"] != "POR-1") & g[rank_col].notna() & g[fo].notna()].nsmallest(N - len(po), rank_col)
        out = pd.concat([with_leg(po, "draw & over 2.5"), with_leg(rest, fill_leg)])
        return out if len(out) >= N else g.iloc[:0]
    return f


def xo_leagues(S, pers, k=8, min_n=150):
    """The k leagues where 'draw & over 2.5' returned most per unit in the given periods (>= min_n bets)."""
    d = S[S["per"].isin(pers) & S["odds_xo"].notna()]
    t = (d["y_xo"] * d["odds_xo"]).groupby(d["league"]).agg(["mean", "size"])
    return list(t[t["size"] >= min_n]["mean"].nlargest(k).index)


def top_xo_leagues(S, k=8):
    """Out of sample: 2025/26 uses the ranking of 2024/25, 2026/27 the ranking of 2024/25 + 2025/26.
    2024/25 has no earlier season: it uses its own ranking (in-sample, flagged in the report)."""
    return {"A": xo_leagues(S, ["A"], k), "B": xo_leagues(S, ["A"], k), "C": xo_leagues(S, ["A", "B"], k)}


TOP_XO = {}


def top_leagues_lowest(portugal_first=False):
    def f(g, leg, rng):
        top = TOP_XO[g["per"].iloc[0]]
        d = g[g["league"].isin(top) & g["odds_xo"].notna()]
        if portugal_first:
            po = d[d["league"] == "POR-1"].nsmallest(N, "odds_xo")
            d = pd.concat([po, d[d["league"] != "POR-1"].nsmallest(N - len(po), "odds_xo")])
        else:
            d = d.nsmallest(N, "odds_xo")
        return with_leg(d, "draw & over 2.5") if len(d) >= N else g.iloc[:0]
    return f


GOAL_LEGS = ["6+ goals", "draw & over 2.5", "BTTS in both halves", "half-time 1-1", "half-time draw & 2+ goals",
             "4-5 goals", "over 4.5", "over 3.5", "1st-half over 1.5", "BTTS", "over 2.5"]
PT_XO = "Portugal 'draw & over 2.5'"
STRATEGIES = (
    [("10 lowest 6+ odds", lowest("o6"), leg) for leg in GOAL_LEGS]
    + [("10 random games", random_pick, "6+ goals"), ("10 random games", random_pick, "draw & over 2.5"),
       ("10 lowest 6+ odds, 6+ odds 7.50-9.00", lowest("o6", 7.5, 9.0), "6+ goals"),
       ("10 lowest 6+ odds, 6+ odds 8.35 or more", lowest("o6", 8.35, 1e9), "6+ goals")]
    + [("10 lowest odds of the bet itself", lowest(LEGS[leg][0]), leg)
       for leg in ["draw & over 2.5", "BTTS in both halves", "half-time 1-1", "half-time draw & 2+ goals"]]
    + [("10 lowest 'draw & over 2.5' odds within 13.50-20", lowest("odds_xo", 13.5, 20.0), "draw & over 2.5"),
       ("Portugal only (all its games in the window, 3-10)", portugal_only, "draw & over 2.5"),
       ("Portugal first, then lowest 'draw & over 2.5' odds", portugal_first("odds_xo"), "draw & over 2.5"),
       ("Portugal first, then lowest 6+ odds", portugal_first("o6"), PT_XO + " + 'draw & over 2.5'"),
       ("Portugal first, then lowest 6+ odds", portugal_first("o6", "half-time 1-1"), PT_XO + " + 'half-time 1-1'"),
       ("Portugal first, then lowest 6+ odds", portugal_first("o6", "6+ goals"), PT_XO + " + '6+ goals'"),
       ("8 best 'draw & over 2.5' leagues of earlier seasons, lowest odds", top_leagues_lowest(), "draw & over 2.5"),
       ("Portugal first, then 8 best 'draw & over 2.5' leagues, lowest odds", top_leagues_lowest(True),
        "draw & over 2.5")])


def coupons(S, window_col):
    rng = np.random.default_rng(7)
    rows = []
    for win, g in S.groupby(window_col, sort=True):
        for strat, pick, leg in STRATEGIES:
            p = pick(g, leg if leg in LEGS else "draw & over 2.5", rng)
            if not len(p):
                continue
            p = p[p["_o"].notna() & p["_y"].notna()]
            n = len(p)
            if n < 3:
                continue
            odds, hits = p["_o"].to_numpy(float), p["_y"].to_numpy(float)
            e = esym(odds[hits == 1], KMAX)
            row = {"window": win, "first day": p["date"].min(), "season": SEASON[p["per"].iloc[0]],
                   "strategy": strat, "leg": leg, "legs": n, "hits": int(hits.sum()), "avg odds": odds.mean(),
                   "leg value": (odds * hits).mean(),
                   "expected 6+ hits (calibrated)": p["p6_cal"].sum() if leg == "6+ goals" else np.nan}
            for k in range(1, KMAX + 1):
                row[f"stake {k}"] = comb(n, k)
                row[f"return {k}"] = e[k]
            rows.append(row)
    return pd.DataFrame(rows)


def summarise(C, boot=400):
    rng = np.random.default_rng(11)
    out = []
    for (wk, strat, leg), g in C.groupby(["windows", "strategy", "leg"], sort=False):
        for season in ["all"] + list(SEASON.values()):
            x = g if season == "all" else g[g["season"] == season]
            if len(x) < 5:
                continue
            r = {"windows": wk, "strategy": strat, "leg": leg, "season": season, "coupons": len(x),
                 "avg legs": x["legs"].mean(), "avg odds per leg": x["avg odds"].mean(),
                 "hit rate per leg %": x["hits"].sum() / x["legs"].sum() * 100,
                 "value per leg": (x["leg value"] * x["legs"]).sum() / x["legs"].sum(),
                 "avg hits": x["hits"].mean()}
            for h in (3, 4, 5):
                r[f"coupons with {h}+ hits %"] = (x["hits"] >= h).mean() * 100
            for name, sizes in SYSTEMS.items():
                st = sum(x[f"stake {k}"] for k in sizes)
                ret = sum(x[f"return {k}"] for k in sizes)
                r[f"{name}: return per 100"] = (ret.sum() / st.sum() - 1) * 100
                r[f"{name}: profitable coupons %"] = (ret > st).mean() * 100
                if name == "system 3-4-5":
                    idx = np.arange(len(x))
                    b = [(ret.iloc[i].sum() / st.iloc[i].sum() - 1) * 100
                         for i in (rng.choice(idx, len(idx)) for _ in range(boot))]
                    r["system 3-4-5: 90% range low"], r["system 3-4-5: 90% range high"] = np.percentile(b, [5, 95])
                    r["system 3-4-5: best coupon (x stake)"] = (ret / st).max()
                    r["system 3-4-5: theory from leg value"] = (system_value(r["value per leg"], sizes,
                                                                            int(round(r["avg legs"]))) - 1) * 100
            out.append(r)
    return pd.DataFrame(out)


def season_odds(C, n_coupons=40, sims=20000):
    """What one season of n_coupons coupons could look like: coupons drawn at random (with replacement) from the
    strategy's real coupons. Chance to end the season up, median and average season result (per 100 staked)."""
    rng = np.random.default_rng(5)
    out = []
    for (wk, strat, leg), g in C.groupby(["windows", "strategy", "leg"], sort=False):
        for name, sizes in SYSTEMS.items():
            st = sum(g[f"stake {k}"] for k in sizes).to_numpy(float)
            ret = sum(g[f"return {k}"] for k in sizes).to_numpy(float)
            i = rng.integers(0, len(g), size=(sims, n_coupons))
            res = (ret[i].sum(1) / st[i].sum(1) - 1) * 100
            out.append({"windows": wk, "strategy": strat, "leg": leg, "system": name, "coupons per season": n_coupons,
                        "chance to end the season up %": (res > 0).mean() * 100,
                        "median season result per 100": np.median(res), "average season result per 100": res.mean(),
                        "chance to lose 80%+ %": (res <= -80).mean() * 100,
                        "best 5% of seasons: at least": np.percentile(res, 95)})
    return pd.DataFrame(out)


def legs_of(S, strategy, leg, kind="weekend"):
    """Every leg of a strategy's coupons (one coupon per window of the given kind): window, league, odds, hit."""
    pick = next(f for st, f, lg in STRATEGIES if st == strategy and lg == leg)
    rng = np.random.default_rng(7)
    rows = []
    for win, g in S[S["week part"].str.endswith(kind)].groupby("week part", sort=True):
        p = pick(g, leg if leg in LEGS else "draw & over 2.5", rng)
        if len(p):
            p = p[p["_o"].notna() & p["_y"].notna()]
            rows.append(p.assign(window=win)[["window", "per", "league", "_o", "_y"]])
    return pd.concat(rows, ignore_index=True)


def sensitivity(L, scenarios, n_coupons=30, sims=4000):
    """How a strategy would do if each leg's true value per unit were v (Portugal legs v_pt, others v_other), on the
    strategy's real coupons (their real odds). Long run: exact (a size-k combo of independent legs returns the product
    of their values, so the system returns sum_k e_k(v) / sum_k C(n, k)). Season view: outcomes simulated with
    chance v / odds, n_coupons coupons per season."""
    rng = np.random.default_rng(9)
    wins = L["window"].unique()
    odds = [L.loc[L["window"] == w, "_o"].to_numpy(float) for w in wins]
    is_pt = [(L.loc[L["window"] == w, "league"] == "POR-1").to_numpy() for w in wins]
    systems = (("singles", (1,)), ("doubles", (2,)), ("system 3", (3,)), ("system 3-4-5", (3, 4, 5)))
    out = []
    for v_pt, v_other in scenarios:
        vals = [np.where(p, v_pt, v_other) for p in is_pt]
        res = {name: [] for name, _ in systems}
        for _ in range(sims):
            st = dict.fromkeys(res, 0.0)
            ret = dict.fromkeys(res, 0.0)
            for c in rng.integers(0, len(wins), n_coupons):
                o = odds[c]
                hit = rng.random(len(o)) < np.clip(vals[c] / o, 0, 1)
                e = esym(o[hit], KMAX)
                for name, sizes in systems:
                    st[name] += sum(comb(len(o), k) for k in sizes)
                    ret[name] += sum(e[k] for k in sizes)
            for k in res:
                res[k].append((ret[k] / st[k] - 1) * 100)
        for name, sizes in systems:
            ev = sum(sum(esym(v, KMAX)[k] for k in sizes) for v in vals)
            stake = sum(sum(comb(len(v), k) for k in sizes) for v in vals)
            r = np.array(res[name])
            out.append({"Portugal leg value": v_pt, "other leg value": v_other, "system": name,
                        "long-run return per 100": (ev / stake - 1) * 100,
                        "chance to end a season up %": (r > 0).mean() * 100,
                        "median season per 100": float(np.median(r))})
    return pd.DataFrame(out)


def theory_table():
    rows = []
    for v in np.round(np.arange(0.60, 1.31, 0.05), 2):
        r = {"value per leg": v}
        for name, sizes in SYSTEMS.items():
            r[f"{name}: return per 100"] = (system_value(v, sizes) - 1) * 100
        rows.append(r)
    return pd.DataFrame(rows)


def run():
    S = sd.build()
    S["week part"], _ = window_ids(S["date"])
    TOP_XO.update(top_xo_leagues(S))
    C = pd.concat([coupons(S, "week part").assign(windows="weekend / midweek"),
                   coupons(S, "date").assign(windows="day")], ignore_index=True)
    C["window kind"] = np.where(C["windows"] == "day", "day", C["window"].str.split(" ").str[-1])
    summ = summarise(C)
    seas = season_odds(C)
    scen = [(0.86, 0.86), (1.0, 0.86), (1.15, 0.86), (1.3, 0.86), (1.5, 0.86)]
    sens = []
    for name, strat in (("Portugal only (weekend)", "Portugal only (all its games in the window, 3-10)"),
                        ("Portugal + best leagues to 10 (weekend)",
                         "Portugal first, then 8 best 'draw & over 2.5' leagues, lowest odds")):
        L = legs_of(S, strat, "draw & over 2.5")
        L.to_parquet(CACHE / f"six_sys_study_legs_{'pt' if 'only' in strat else 'pt10'}.parquet")
        sens.append(sensitivity(L, scen).assign(coupon=name))
    L6 = legs_of(S, "10 lowest 6+ odds", "6+ goals").assign(league="-")
    sens.append(sensitivity(L6, [(0.71, 0.71)]).assign(coupon="10 lowest 6+ odds, 6+ legs (weekend)"))
    pd.concat(sens, ignore_index=True).to_parquet(CACHE / "six_sys_study_sensitivity.parquet")
    C.to_parquet(CACHE / "six_sys_study_coupons.parquet")
    summ.to_parquet(CACHE / "six_sys_study_summary.parquet")
    seas.to_parquet(CACHE / "six_sys_study_seasons.parquet")
    return C, summ


if __name__ == "__main__":
    C, summ = run()
    pd.set_option("display.width", 300)
    pd.set_option("display.max_rows", 500)
    cols = ["windows", "strategy", "leg", "season", "coupons", "avg legs", "avg odds per leg", "hit rate per leg %",
            "value per leg", "avg hits", "coupons with 3+ hits %", "coupons with 4+ hits %", "coupons with 5+ hits %",
            "singles: return per 100", "system 3: return per 100", "system 3-4-5: return per 100",
            "system 3-4-5: 90% range low", "system 3-4-5: 90% range high", "system 3-4-5: theory from leg value",
            "system 3-4-5: best coupon (x stake)"]
    print(summ[summ["season"] == "all"][cols].round(1).to_string())
