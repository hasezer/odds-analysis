"""HT/FT study 3, step 4: structural signs, team comeback profiles and two-way lookup maps for the six results.

1. Two-part score: each result = a half-time state AND a full-time outcome, both priced by Nesine separately, e.g.
   X/2 = level at half-time (1st-half result X) AND away wins (1X2 '2'). Score = chance(half-time state) x
   chance(full-time result); also the half-time state x the 2nd-half result chance (2H_1X2).
2. Team comeback profiles over longer windows (previous 20 matches and previous season, strictly earlier games):
   home/away team's rate of coming back, blowing leads, leads pegged back, half-time-level games won / lost,
   and a 'pair index' for each result (e.g. 2/1: home team's comeback rate + away team's blown-lead rate).
3. Lookup maps: hit rate of each result by its two natural drivers (half-time state chance x full-time result
   chance), cell bands from 2024/25 quantiles; the best cell chosen on 2024/25 + 2025/26 and checked on 2026/27.
Every score is reported as the hit rate of its top 10% / 5% (cut-offs from 2024/25) and its AUC per season, next
to the result's own HT/FT price. Writes cache/htft3_extra.pkl.
"""
from pathlib import Path
import pickle
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import htft3_data as h3  # noqa: E402
import load  # noqa: E402
from htft_data import CACHE  # noqa: E402
from six_plus import auc  # noqa: E402
from htft3_signs import SEAS, strat_auc  # noqa: E402

# result -> (half-time state market column, full-time result column, 2nd-half result column)
PARTS = {"1/X": ("f_HT_1X2__1", "f_1X2__X", "f_2H_1X2__2"), "2/X": ("f_HT_1X2__2", "f_1X2__X", "f_2H_1X2__1"),
         "X/1": ("f_HT_1X2__X", "f_1X2__1", "f_2H_1X2__1"), "X/2": ("f_HT_1X2__X", "f_1X2__2", "f_2H_1X2__2"),
         "1/2": ("f_HT_1X2__1", "f_1X2__2", "f_2H_1X2__2"), "2/1": ("f_HT_1X2__2", "f_1X2__1", "f_2H_1X2__1")}
HTNAME = {"f_HT_1X2__1": "home leads at half-time", "f_HT_1X2__2": "away leads at half-time",
          "f_HT_1X2__X": "level at half-time"}
FTNAME = {"f_1X2__1": "home wins", "f_1X2__2": "away wins", "f_1X2__X": "draw"}


def judge(d, score, ycol, pcol, name, lab):
    y = d[ycol].to_numpy(float)
    p = d[pcol].to_numpy(float)
    s = np.asarray(score, float)
    per = d["per"].to_numpy()
    A = per == "A"
    r = {"result": lab, "score": name}
    for share, tag in ((0.10, "top 10%"), (0.05, "top 5%")):
        thr = np.nanquantile(s[A], 1 - share)
        for k, nm in SEAS.items():
            m = (per == k) & (s >= thr)
            r[f"{tag} hit % {nm}"] = y[m].mean() * 100 if m.sum() else np.nan
            r[f"{tag} matches {nm}"] = int(m.sum())
    for k, nm in SEAS.items():
        m = per == k
        r[f"AUC {nm}"] = auc(s[m], y[m])
        r[f"beyond price AUC {nm}"] = strat_auc(s[m], y[m], p[m], 10 if y.mean() > .04 else 5)
    return r


def team_profiles():
    """Previous-20 and previous-season rates per team (strictly earlier matches)."""
    m = load.matches()
    m = m[(m["status"] == "finished") & m["ht_home"].notna() & m["ft_home"].notna()].copy()
    m["per"] = m["season"].map(h3.PER)
    rows = []
    for side, opp in (("home", "away"), ("away", "home")):
        h1, a1, h, a = m[f"ht_{side}"], m[f"ht_{opp}"], m[f"ft_{side}"], m[f"ft_{opp}"]
        rows.append(pd.DataFrame({
            "match_id": m["match_id"], "team": m[f"{side}_team_id"], "kick": m["kickoff_utc"], "side": side,
            "per": m["per"], "trailed": (h1 < a1).astype(float), "led": (h1 > a1).astype(float),
            "level": (h1 == a1).astype(float),
            "came_back": ((h1 < a1) & (h >= a)).astype(float), "won_from_behind": ((h1 < a1) & (h > a)).astype(float),
            "blew": ((h1 > a1) & (h <= a)).astype(float), "lost_lead_lost": ((h1 > a1) & (h < a)).astype(float),
            "pegged": ((h1 > a1) & (h == a)).astype(float), "trail_drew": ((h1 < a1) & (h == a)).astype(float),
            "lvl_won": ((h1 == a1) & (h > a)).astype(float), "lvl_lost": ((h1 == a1) & (h < a)).astype(float)}))
    t = pd.concat(rows).sort_values(["team", "kick"]).reset_index(drop=True)
    ev = ["came_back", "won_from_behind", "blew", "lost_lead_lost", "pegged", "trail_drew", "lvl_won", "lvl_lost"]
    base = {"came_back": "trailed", "won_from_behind": "trailed", "trail_drew": "trailed", "blew": "led",
            "lost_lead_lost": "led", "pegged": "led", "lvl_won": "level", "lvl_lost": "level"}
    g = t.groupby("team")
    for e in ev:                 # rate per opportunity (e.g. came back / times trailed), previous 20 matches
        num = g[e].transform(lambda s: s.shift(1).rolling(20, min_periods=10).sum())
        den = g[base[e]].transform(lambda s: s.shift(1).rolling(20, min_periods=10).sum())
        t[f"p20_{e}"] = num / den.where(den >= 3)
    # previous season (the team's whole previous period in our data)
    ps = t.groupby(["team", "per"])[ev + ["trailed", "led", "level"]].sum()
    for e in ev:
        ps[f"ps_{e}"] = ps[e] / ps[base[e]].where(ps[base[e]] >= 5)
    prev = {"B": "A", "C": "B"}
    ps = ps[[f"ps_{e}" for e in ev]].reset_index()
    ps["per"] = ps["per"].map({v: k for k, v in prev.items()})
    t = t.merge(ps.dropna(subset=["per"]), on=["team", "per"], how="left")
    feat = [c for c in t.columns if c.startswith(("p20_", "ps_"))]
    h = t[t["side"] == "home"].set_index("match_id")[feat].add_prefix("home_")
    a = t[t["side"] == "away"].set_index("match_id")[feat].add_prefix("away_")
    return h.join(a)


PAIR_INDEX = {  # result -> (home team habit, away team habit) that should make it more likely
    "2/1": ("came_back", "blew"), "1/2": ("blew", "came_back"), "1/X": ("pegged", "trail_drew"),
    "2/X": ("trail_drew", "pegged"), "X/1": ("lvl_won", "lvl_lost"), "X/2": ("lvl_lost", "lvl_won")}


def maps(d):
    out, best = [], []
    for lab, (ht, ft, _) in PARTS.items():
        y = h3.TARGETS[lab]
        A = d["per"] == "A"
        qa = np.nanquantile(d.loc[A, ht], [0, .2, .4, .6, .8, 1])
        qb = np.nanquantile(d.loc[A, ft], [0, .2, .4, .6, .8, 1])
        qa[0], qb[0], qa[-1], qb[-1] = 0, 0, 1, 1
        x = d.assign(a=pd.cut(d[ht], qa, include_lowest=True), b=pd.cut(d[ft], qb, include_lowest=True))
        g = x.groupby(["a", "b", "per"], observed=True)[y].agg(["mean", "size"]).unstack("per")
        g.columns = [f"{'hit %' if a == 'mean' else 'matches'} {SEAS[b]}" for a, b in g.columns]
        for c in g.columns:
            if c.startswith("hit"):
                g[c] *= 100
        g = g.reset_index()
        g["a"] = g["a"].map(lambda iv: f"{HTNAME[ht]} {iv.left * 100:.0f}-{iv.right * 100:.0f}%")
        g["b"] = g["b"].map(lambda iv: f"{FTNAME[ft]} {iv.left * 100:.0f}-{iv.right * 100:.0f}%")
        g.insert(0, "result", lab)
        out.append(g)
        ab = g[(g["matches 2024/25"] >= 100) & (g["matches 2025/26"] >= 100)].copy()
        ab["score"] = (ab["hit % 2024/25"] * ab["matches 2024/25"] + ab["hit % 2025/26"] * ab["matches 2025/26"]) / \
            (ab["matches 2024/25"] + ab["matches 2025/26"])
        best.append(ab.sort_values("score", ascending=False).head(3))
    return pd.concat(out, ignore_index=True), pd.concat(best, ignore_index=True)


def run():
    d = h3.build()
    tp = team_profiles()
    d = d.join(tp, on="match_id")
    rows = []
    for lab, (ht, ft, sh) in PARTS.items():
        y, p = h3.TARGETS[lab], f"p_{lab}"
        rows.append(judge(d, d[p], y, p, "own HT/FT price (baseline)", lab))
        rows.append(judge(d, d[ht] * d[ft], y, p, f"two-part: {HTNAME[ht]} x {FTNAME[ft]}", lab))
        rows.append(judge(d, d[ht] * d[sh], y, p, f"two-part: {HTNAME[ht]} x 2nd half the same way", lab))
        rows.append(judge(d, np.sqrt(d[p] * d[ht] * d[ft]), y, p, "own price x two-part (geometric mean)", lab))
        hh, aa = PAIR_INDEX[lab]
        for w in ("p20", "ps"):
            hs, as_ = d[f"home_{w}_{hh}"], d[f"away_{w}_{aa}"]
            nm = "previous 20 matches" if w == "p20" else "previous season"
            rows.append(judge(d, hs, y, p, f"home team habit '{hh}' ({nm})", lab))
            rows.append(judge(d, as_, y, p, f"away team habit '{aa}' ({nm})", lab))
            rows.append(judge(d, hs.fillna(hs.mean()) + as_.fillna(as_.mean()), y, p,
                              f"pair index {hh} + {aa} ({nm})", lab))
    J = pd.DataFrame(rows)
    M, best = maps(d)
    T = {"scores": J, "maps": M, "best_cells": best}
    with open(CACHE / "htft3_extra.pkl", "wb") as fh:
        pickle.dump(T, fh)
    return T


if __name__ == "__main__":
    T = run()
    pd.set_option("display.width", 260)
    pd.set_option("display.max_rows", 200)
    cols = ["result", "score", "top 10% hit % 2024/25", "top 10% hit % 2025/26", "top 10% hit % 2026/27",
            "top 5% hit % 2025/26", "top 5% hit % 2026/27", "beyond price AUC 2024/25", "beyond price AUC 2025/26",
            "beyond price AUC 2026/27"]
    print(T["scores"][cols].round(2).to_string(index=False))
    print(T["best_cells"].round(1).to_string(index=False))
