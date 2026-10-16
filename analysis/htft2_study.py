"""HT/FT deep dive 2 (HTFT2_REPORT.md): which game ends in which HT/FT result, the half-time table, prices.

Everything is seen from the favourite's side (htft2_data.py): F = favourite by Nesine's 1X2 odds, U = underdog.
Seasons: A = 2024/25 + 2024 (find), B = 2025/26 + 2025 (confirm), C = 2026/27 + 2026 so far (exam).

Tables (cache/htft2_tables.pkl, a dict of DataFrames):
  map_fav / map_cells      share of each of the 9 outcomes by favourite strength (x goal expectation), by season
  spot                     how well each outcome can be spotted: best map cell vs top 10% by its own odds
  top_outcome              Nesine's most likely HT/FT outcome: how often it happens vs what Nesine says
  halftime / halftime_goals  full-time result and 2nd-half goals after each half-time score (live aid)
  transitions              Nesine's pre-match implied 'after half-time' chances vs what happened
  value_fav / value_ff     what 1 unit returns on each outcome by favourite strength / on F/F by its odds
  scan / scan_cells        cells (outcome x favourite x goals, outcome x own-odds decile, outcome x favourite) at or
                           above break-even in 2024/25 AND 2025/26, against a no-edge twin (luck control)
  family / family_fav      every half-time-related bet (HT result, 2nd-half result, HT score, HT goals, win either
                           / both halves, HT result & goals / BTTS, BTTS per half, HT/FT) - return per unit
  league_late              does a league keep scoring later (or earlier) than the odds expect? (persistence)
  hypotheses               Portugal 1/X and 2/X (from the Portugal 2-2 effect); draws by goal expectation
"""
from pathlib import Path
import pickle
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import htft2_data as h2  # noqa: E402
import rule_tester as rt  # noqa: E402
from htft_data import CACHE  # noqa: E402

FOUT = h2.FOUT
SEAS = {"A": "2024/25", "B": "2025/26", "C": "2026/27"}
FB = ([0, .4, .5, .6, .7, 1], ["under 40%", "40-50%", "50-60%", "60-70%", "70%+"])
GB = ([0, .45, .55, .65, 1], ["low (<45%)", "45-55%", "55-65%", "high (65%+)"])
HS = ["fav 2+ ahead", "fav 1 ahead", "0-0", "level with goals (1-1, 2-2)", "dog 1 ahead", "dog 2+ ahead"]
OUT = CACHE / "htft2_tables.pkl"


def bands(d):
    d = d.copy()
    d["fb"] = pd.cut(d["fav_p"], bins=FB[0], labels=FB[1]).astype(str)
    d["gb"] = pd.cut(d["over25_p"], bins=GB[0], labels=GB[1]).astype(str)
    d["hs"] = np.select([d["ht_d"] >= 2, d["ht_d"] == 1, (d["ht_d"] == 0) & (d["ht_goals"] == 0), d["ht_d"] == 0,
                         d["ht_d"] == -1], HS[:5], HS[5])
    d["ft"] = np.where(d["ft_d"] > 0, "fav wins", np.where(d["ft_d"] < 0, "dog wins", "draw"))
    return d


def shares(d, keys):
    t = pd.crosstab([d[k] for k in keys], d["htft_f"], normalize="index").reindex(columns=FOUT, fill_value=0) * 100
    t.insert(0, "matches", d.groupby(keys).size())
    return t


def map_tables(d):
    fav = shares(d, ["fb"])
    by = shares(d, ["fb", "per"]).reset_index()
    by["per"] = by["per"].map(SEAS)
    cells = shares(d, ["fb", "gb"])
    cells["most likely"] = cells[FOUT].idxmax(axis=1)
    return fav, by, cells


def spot(d):
    rows = []
    for fo in FOUT:
        y = d["htft_f"] == fo
        ab = d["per"].isin(["A", "B"])
        g = d[ab].assign(y=y[ab]).groupby(["fb", "gb"])["y"].agg(["mean", "size"])
        cell = g[g["size"] >= 200]["mean"].idxmax()
        m = (d["fb"] == cell[0]) & (d["gb"] == cell[1])
        thr = d.loc[ab, f"p_{fo}"].quantile(0.9)
        m2 = d[f"p_{fo}"] >= thr
        r = {"outcome (fav side)": fo, "best group of games (chosen on 2024/25 + 2025/26)":
             f"favourite {cell[0]}, over 2.5 chance {cell[1]}", "group share of matches %": m.mean() * 100,
             "its HT/FT odds are at most (top 10%)": d.loc[m2, f"o_{fo}"].max()}
        for p, nm in SEAS.items():
            sp = d["per"] == p
            r[f"normal % {nm}"] = y[sp].mean() * 100
            r[f"group % {nm}"] = y[m & sp].mean() * 100
            r[f"top 10% own odds % {nm}"] = y[m2 & sp].mean() * 100
        rows.append(r)
    return pd.DataFrame(rows)


def top_outcome(d):
    P = d[[f"p_{fo}" for fo in FOUT]].to_numpy()
    top = np.array(FOUT)[P.argmax(1)]
    x = d.assign(top=top, top_p=P.max(1))
    x["band"] = pd.cut(x["top_p"], [0, .25, .3, .35, .4, .5, 1],
                       labels=["up to 25%", "25-30%", "30-35%", "35-40%", "40-50%", "over 50%"]).astype(str)
    t = x.groupby("band").apply(lambda g: pd.Series({
        "matches": len(g), "Nesine's most likely outcome happened %": (g["top"] == g["htft_f"]).mean() * 100,
        "Nesine said % (cut removed)": g["top_p"].mean() * 100,
        "most often it is": g["top"].value_counts().index[0]}))
    P2 = np.argsort(-P, 1)[:, :2]
    hit2 = [h in (FOUT[a], FOUT[b]) for h, (a, b) in zip(d["htft_f"], P2)]
    t = t.reindex(["up to 25%", "25-30%", "30-35%", "35-40%", "40-50%", "over 50%"])
    t.loc["the 2 most likely together", "Nesine's most likely outcome happened %"] = np.mean(hit2) * 100
    return t.reset_index()


def halftime(d):
    g = d.groupby(["fb", "hs"])
    t = pd.crosstab([d["fb"], d["hs"]], d["ft"], normalize="index")[["fav wins", "draw", "dog wins"]] * 100
    t.insert(0, "matches", g.size())
    t["2nd-half goals (avg)"] = g["sh_goals"].mean()
    t["2nd half 1+ goals %"] = g["sh_goals"].apply(lambda s: (s >= 1).mean() * 100)
    t["2nd half 2+ goals %"] = g["sh_goals"].apply(lambda s: (s >= 2).mean() * 100)
    st = d.groupby(["fb", "hs", "per"]).apply(lambda x: (x["ft"] == "fav wins").mean() * 100).unstack("per")
    st.columns = [f"fav wins % {SEAS[c]}" for c in st.columns]
    t = t.join(st)
    t = t.reindex(pd.MultiIndex.from_product([FB[1], HS], names=["favourite", "half-time"]))
    return t.dropna(how="all").reset_index()


def halftime_goals(d):
    x = d.assign(htg=np.select([d["ht_goals"] == 0, d["ht_goals"] == 1, d["ht_goals"] == 2], ["0", "1", "2"], "3+"),
                 ftg=d["ht_goals"] + d["sh_goals"])
    g = x.groupby(["gb", "htg"])
    t = pd.DataFrame({"matches": g.size(), "2nd-half goals (avg)": g["sh_goals"].mean(),
                      "2nd half 1+ goals %": g["sh_goals"].apply(lambda s: (s >= 1).mean() * 100),
                      "2nd half 2+ goals %": g["sh_goals"].apply(lambda s: (s >= 2).mean() * 100),
                      "full time over 2.5 %": g["ftg"].apply(lambda s: (s >= 3).mean() * 100),
                      "full time over 3.5 %": g["ftg"].apply(lambda s: (s >= 4).mean() * 100)})
    st = x.groupby(["gb", "htg", "per"])["sh_goals"].apply(lambda s: (s >= 1).mean() * 100).unstack("per")
    st.columns = [f"2nd half 1+ goals % {SEAS[c]}" for c in st.columns]
    t = t.join(st)
    t = t.reindex(pd.MultiIndex.from_product([GB[1], ["0", "1", "2", "3+"]],
                                             names=["pre-match over 2.5 chance", "half-time goals"]))
    return t.dropna(how="all").reset_index()


def transitions(d):
    x = d.copy()
    for hh in "FXU":
        den = sum(x[f"p_{hh}/{f}"] for f in "FXU")
        for f in "FXU":
            x[f"c_{hh}{f}"] = x[f"p_{hh}/{f}"] / den
    x["ht"], x["ftr"] = x["htft_f"].str[0], x["htft_f"].str[2]
    name = {"F": "fav leads", "X": "level", "U": "dog leads"}
    fname = {"F": "fav wins", "X": "draw", "U": "dog wins"}
    rows = []
    for (fb, p), g0 in x.groupby(["fb", "per"]):
        for hh in "FXU":
            g = g0[g0["ht"] == hh]
            if len(g) < 30:
                continue
            r = {"favourite": fb, "season": SEAS[p], "half-time": name[hh], "matches": len(g)}
            for f in "FXU":
                r[f"{fname[f]}: happened %"] = (g["ftr"] == f).mean() * 100
                r[f"{fname[f]}: Nesine's HT/FT said %"] = g[f"c_{hh}{f}"].mean() * 100
            rows.append(r)
    return pd.DataFrame(rows)


def value_fav(d):
    rows = []
    for fo in FOUT:
        y = (d["htft_f"] == fo).astype(float)
        for (fb, p), g in d.assign(y=y, v=y * d[f"o_{fo}"]).groupby(["fb", "per"]):
            rows.append({"outcome": fo, "favourite": fb, "season": SEAS[p], "bets": len(g), "won %": g["y"].mean() * 100,
                         "avg odds": g[f"o_{fo}"].mean(), "returns per 1 unit": g["v"].mean()})
    r = pd.DataFrame(rows)
    allp = r.groupby(["outcome", "favourite"]).apply(lambda x: pd.Series({
        "bets": x["bets"].sum(), "won %": np.average(x["won %"], weights=x["bets"]),
        "avg odds": np.average(x["avg odds"], weights=x["bets"]),
        "returns per 1 unit": np.average(x["returns per 1 unit"], weights=x["bets"])})).reset_index()
    wide = r.pivot_table(index=["outcome", "favourite"], columns="season", values="returns per 1 unit").reset_index()
    return allp.merge(wide, on=["outcome", "favourite"])


def value_ff(d):
    y = (d["htft_f"] == "F/F").astype(float)
    x = d.assign(y=y, v=y * d["o_F/F"], ob=pd.cut(d["o_F/F"], [1, 1.5, 1.7, 1.9, 2.2, 2.6, 3.2, 4, 100]).astype(str))
    t = x.groupby(["ob", "per"]).agg(bets=("v", "size"), won=("y", "mean"), value=("v", "mean")).unstack("per")
    t.columns = [f"{a} {SEAS[b]}" for a, b in t.columns]
    return t.reset_index().rename(columns={"ob": "F/F odds"})


def scan(d, sims=20, seed=2):
    """Cells at or above break-even in 2024/25 AND 2025/26 (>= 100 bets each), vs a no-edge twin: results drawn with
    chance = (that outcome's own season return per unit) / odds, so no cell has a real edge."""
    L = []
    for fo in FOUT:
        x = pd.DataFrame({"outcome": fo, "o": d[f"o_{fo}"], "y": (d["htft_f"] == fo).astype(float), "per": d["per"],
                          "favourite": d["fb"], "goals": d["gb"]})
        x["own-odds decile"] = pd.qcut(x["o"], 10, duplicates="drop").astype(str)
        L.append(x)
    L = pd.concat(L, ignore_index=True)
    L = L[L["o"].notna()]
    c = (L["y"] * L["o"]).groupby([L["outcome"], L["per"]]).mean()
    pnull = np.clip(c.reindex(pd.MultiIndex.from_arrays([L["outcome"], L["per"]])).to_numpy() / L["o"].to_numpy(), 0, 1)
    rng = np.random.default_rng(seed)

    def cells(y, keys):
        v = pd.Series(y * L["o"].to_numpy(), index=L.index)
        return v.groupby([L[k] for k in keys] + [L["per"]]).agg(["mean", "size"]).unstack("per")

    def passing(g, thr):
        return g[g[("mean", "A")].ge(thr) & g[("mean", "B")].ge(thr) & g[("size", "A")].ge(100) &
                 g[("size", "B")].ge(100)]
    rows, keep = [], []
    for name, keys in (("outcome x favourite x goals", ["outcome", "favourite", "goals"]),
                       ("outcome x own-odds decile", ["outcome", "own-odds decile"]),
                       ("outcome x favourite", ["outcome", "favourite"])):
        g = cells(L["y"].to_numpy(), keys)
        for thr in (0.95, 1.0):
            real = passing(g, thr)
            nulls = [len(passing(cells((rng.random(len(L)) < pnull).astype(float), keys), thr)) for _ in range(sims)]
            rows.append({"cells": name, "how many cells": len(g), "break-even level": thr,
                         "cells passing 2024/25 and 2025/26": len(real), "luck twin: average": np.mean(nulls),
                         "luck twin: most": max(nulls),
                         "of those, also 2026/27": int((real[("mean", "C")] >= thr).sum()) if len(real) else 0})
            if len(real) and thr == 1.0:
                r = real.copy()
                r.columns = [f"{'returns per 1 unit' if a == 'mean' else 'bets'} {SEAS[b]}" for a, b in r.columns]
                keep.append(r.reset_index().assign(cells=name))
    return pd.DataFrame(rows), (pd.concat(keep, ignore_index=True) if keep else pd.DataFrame())


FAMILY = ("HT_1X2|", "2H_1X2|", "HT_FT|", "TEAM_WIN_BOTH_HALVES", "TEAM_WIN_EITHER_HALF", "HT_1X2_AND_HT_BTTS|",
          "HT_1X2_AND_HT_OU|", "HT_OU|", "HT_BTTS|", "2H_BTTS|", "HT_2H_BTTS|", "BOTH_HALVES_OVER|", "HT_TEAM_OU",
          "HT_CORRECT_SCORE|")
SWAP = ("HT_1X2", "2H_1X2", "HT_FT", "HT_1X2_AND_HT_BTTS", "HT_1X2_AND_HT_OU")


def fav_name(lab, fav_home):
    """A bet label seen from the favourite's side: 1 -> F, 2 -> U, HOME -> FAV, AWAY -> DOG, scores fav-first."""
    mk, line, sk = lab.split("|")
    if not fav_home:
        mk = mk.replace("HOME", "@").replace("AWAY", "HOME").replace("@", "AWAY")
        if mk == "HT_CORRECT_SCORE" and "-" in sk:
            a, b = sk.split("-")
            sk = f"{b}-{a}"
        elif mk in SWAP:
            sk = sk.replace("1", "#").replace("2", "1").replace("#", "2")
    if mk in SWAP:
        sk = sk.replace("1", "F").replace("2", "U")
    if mk == "HT_CORRECT_SCORE" and "-" in sk:
        sk = f"fav {sk}"
    return f"{mk.replace('HOME', 'FAV').replace('AWAY', 'DOG')}|{line}|{sk}"


def family():
    W = rt.wide()
    W = W[~W.index.str.startswith("macko")]
    per = W["period"].map({v: k for k, v in SEAS.items()})
    p1, p2, px = 1 / W["1X2||1"], 1 / W["1X2||2"], 1 / W["1X2||X"]
    fh = (p1 >= p2).to_numpy()
    fb = pd.cut(pd.Series(np.where(fh, p1, p2) / (p1 + p2 + px), index=W.index), bins=FB[0], labels=FB[1]).astype(str)
    parts = []
    for lab in [c for c in W.columns if "|" in c and c.startswith(FAMILY)]:
        o = W[lab]
        try:
            y = rt.outcome(W, lab)
        except TypeError:
            continue
        ok = (o.notna() & y.notna()).to_numpy()
        if ok.sum() < 2000:
            continue
        parts.append(pd.DataFrame({"bet": [fav_name(lab, f) for f in fh[ok]], "o": o[ok].to_numpy(),
                                   "y": y[ok].to_numpy(), "per": per[ok].to_numpy(), "favourite": fb[ok].to_numpy()}))
    D = pd.concat(parts, ignore_index=True)
    D["v"] = D["o"] * D["y"]
    tot = D.groupby("bet").agg(bets=("v", "size"), **{"won %": ("y", "mean")}, **{"avg odds": ("o", "mean")},
                               **{"returns per 1 unit": ("v", "mean")})
    tot["won %"] *= 100
    s = D.groupby(["bet", "per"])["v"].mean().unstack()
    s.columns = [f"returns per 1 unit {SEAS[c]}" for c in s.columns]
    fam = tot.join(s).sort_values("returns per 1 unit", ascending=False).reset_index()
    fav = D.groupby(["bet", "favourite", "per"])["v"].agg(["mean", "size"]).unstack("per")
    fav.columns = [f"{'returns per 1 unit' if a == 'mean' else 'bets'} {SEAS[b]}" for a, b in fav.columns]
    fav = fav.reset_index()
    return fam, fav


def league_late(d):
    x = d[d["lam_1h"].notna()].assign(late=lambda z: (z["sh_goals"] - z["lam_2h"]) - (z["ht_goals"] - z["lam_1h"]))
    t = x.groupby(["league", "per"])["late"].agg(["mean", "size"]).unstack("per")
    t.columns = [f"{'late goals beyond the odds' if a == 'mean' else 'matches'} {SEAS[b]}" for a, b in t.columns]
    v = x.groupby(["league", "per"])["late"].mean().unstack()
    corr = pd.DataFrame([{"seasons compared": "2024/25 -> 2025/26", "correlation between leagues": v["A"].corr(v["B"])},
                         {"seasons compared": "2025/26 -> 2026/27", "correlation between leagues": v["B"].corr(v["C"])},
                         {"seasons compared": "2024/25 -> 2026/27", "correlation between leagues": v["A"].corr(v["C"])}])
    share = pd.DataFrame([{"2nd-half share of goals: happened %":
                           x["sh_goals"].sum() / (x["sh_goals"].sum() + x["ht_goals"].sum()) * 100,
                           "2nd-half share of goals: Nesine's prices expect %":
                           x["lam_2h"].sum() / (x["lam_1h"].sum() + x["lam_2h"].sum()) * 100}])
    return t.reset_index(), corr, share


def hypotheses(d):
    rows = []
    for fo in ("F/X", "U/X", "X/X", "F/F"):
        x = d[d["league"] == "POR-1"]
        y = x["htft_f"] == fo
        for p, nm in SEAS.items():
            m = x["per"] == p
            rows.append({"test": f"Portugal: HT/FT {fo} (fav side)", "season": nm, "bets": int(m.sum()),
                         "won %": y[m].mean() * 100, "returns per 1 unit": (y[m] * x.loc[m, f"o_{fo}"]).mean()})
    # Nesine labels in Portugal (home side), the direct test of the 2-2 hypothesis
    hd = pd.read_parquet(CACHE / "htft_wide.parquet")
    hd = hd[hd["league_id"] == "POR-1"]
    for lab in ("1/X", "2/X", "X/X"):
        y = hd["htft"] == lab
        for p, nm in SEAS.items():
            m = hd["season"].map(h2.PER) == p
            rows.append({"test": f"Portugal: HT/FT {lab} (Nesine label)", "season": nm, "bets": int(m.sum()),
                         "won %": y[m].mean() * 100, "returns per 1 unit": (y[m] * hd.loc[m, f"o_{lab}"]).mean()})
    for fo in ("F/X", "U/X", "X/X"):
        y = d["htft_f"] == fo
        for (gb, p), g in d.assign(y=y, v=y * d[f"o_{fo}"]).groupby(["gb", "per"]):
            rows.append({"test": f"HT/FT {fo} by goal expectation: {gb}", "season": SEAS[p], "bets": len(g),
                         "won %": g["y"].mean() * 100, "returns per 1 unit": g["v"].mean()})
    return pd.DataFrame(rows)


def run():
    d = bands(h2.build())
    T = {}
    T["map_fav"], T["map_fav_by_season"], T["map_cells"] = map_tables(d)
    T["spot"] = spot(d)
    T["top_outcome"] = top_outcome(d)
    T["halftime"] = halftime(d)
    T["halftime_goals"] = halftime_goals(d)
    T["transitions"] = transitions(d)
    T["value_fav"] = value_fav(d)
    T["value_ff"] = value_ff(d)
    T["scan"], T["scan_cells"] = scan(d)
    T["family"], T["family_fav"] = family()
    T["league_late"], T["league_late_corr"], T["half_share"] = league_late(d)
    T["hypotheses"] = hypotheses(d)
    T["n_matches"] = pd.DataFrame([{"matches": len(d), **{SEAS[p]: int((d["per"] == p).sum()) for p in SEAS}}])
    with open(OUT, "wb") as fh:
        pickle.dump(T, fh)
    return T


if __name__ == "__main__":
    T = run()
    pd.set_option("display.width", 250)
    for k in ("scan", "scan_cells", "top_outcome", "league_late_corr", "half_share"):
        print("==", k)
        print(T[k].round(3).to_string())
