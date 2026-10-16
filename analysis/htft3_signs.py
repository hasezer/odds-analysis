"""HT/FT study 3, step 1: every single sign for the six changing results (and three natural pairs).

For each result and each pre-match signal (about 400: every market's odds and chances, correct scores, the HT/FT
prices, the other-markets HT/FT model, Nesine's 'after half-time' chances, team last-10 habits, league history,
calendar): the direction and the cut-offs are set on 2024/25 (+2024) only, then the hit rate of the signal's top 10%
and top 5% is measured in every season, with the AUC (0.5 = no information) and the 'beyond the price' AUC (inside
groups of matches with the same HT/FT price for that result). Writes cache/htft3_signs.parquet.
"""
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import htft3_data as h3  # noqa: E402
from htft_data import CACHE, HINT_MARKETS  # noqa: E402
from rule_miner import nice  # noqa: E402
from six_plus import auc  # noqa: E402

SEAS = {"A": "2024/25", "B": "2025/26", "C": "2026/27"}
PAIRS = {"X/1 or X/2": ["y_X1", "y_X2"], "1/X or 2/X": ["y_1X", "y_2X"], "1/2 or 2/1": ["y_12", "y_21"]}
META = {"match_id", "league", "season", "per", "kickoff", "home", "away", "ht_home", "ht_away", "ft_home", "ft_away",
        "htft"}
MARKETS = sorted(HINT_MARKETS + ["HT_FT"], key=len, reverse=True)
HALF = {"h1": "home 1st half", "a1": "away 1st half", "h2": "home 2nd half", "a2": "away 2nd half"}
TEAM = {"led": "led at half-time", "trailed": "trailed at half-time", "level": "level at half-time",
        "blew": "blew a half-time lead", "came_back": "came back from behind", "lvl_won": "won after level at HT",
        "lvl_lost": "lost after level at HT", "led_drew": "led at HT then drew", "trail_drew": "trailed at HT then drew",
        "g1f": "1st-half goals scored", "g1a": "1st-half goals conceded", "g2f": "2nd-half goals scored",
        "g2a": "2nd-half goals conceded", "late_share_f": "share of its goals scored after half-time",
        "late_share_a": "share of goals conceded after half-time"}


def label_of_f(col):
    s = col[2:]
    for mk in MARKETS:
        if s.startswith(mk + "_"):
            line, _, sel = s[len(mk) + 1:].partition("_")
            return f"{mk}|{line}|{sel}"
    return None


def pretty(c):
    if c.startswith("odds_"):
        return f"odds: {nice(c[5:])}"
    if c.startswith("f_"):
        lab = label_of_f(c)
        return f"chance: {nice(lab)}" if lab else c
    if c.startswith("hcs_"):
        return f"chance: 1st-half score {c[4:]}"
    if c.startswith("cs_"):
        return f"chance: score {c[3:]}"
    for pre, txt in (("p_", "HT/FT {} chance (its own price)"), ("o_", "HT/FT {} odds"),
                     ("q_", "HT/FT {} chance from the other markets"),
                     ("d_", "HT/FT {}: own price vs the other markets")):
        if c.startswith(pre) and "/" in c:
            return txt.format(c[len(pre):])
    if c.startswith("c_") and len(c) == 4:
        return f"Nesine: after half-time {c[2]}, chance full-time is {c[3]}"
    if c.startswith("lam_") and c[4:] in HALF:
        return f"expected goals {HALF[c[4:]]}"
    for side in ("home", "away"):
        if c.startswith(f"{side}_t10_"):
            return f"{side} team, last 10: {TEAM.get(c[len(side) + 5:], c)}"
        if c == f"{side}_rest_days":
            return f"{side} team: days since last match"
    if c.startswith("lg_y_"):
        return f"league's recent extra {c[5:6]}/{c[6:7]} beyond the prices"
    return {"lam_tot": "expected goals in the match", "lam_1h_share": "share of goals expected in the 1st half",
            "home_2h_share": "home: share of its expected goals after half-time",
            "away_2h_share": "away: share of its expected goals after half-time",
            "home_minus_away": "home win chance minus away win chance", "fav_p": "favourite's win chance",
            "kick_hour_tr": "kick-off hour (Turkey)", "weekday": "weekday (0 = Monday)",
            "season_day": "days into the league season", "fit_rmse": "other-markets model fit error"}.get(c, c)


def features(d):
    out = []
    for c in d.columns:
        if c in META or c.startswith("y_") or not pd.api.types.is_numeric_dtype(d[c]):
            continue
        if d[c].notna().mean() < 0.3 or d[c].nunique() < 5:
            continue
        out.append(c)
    return out


def strat_auc(s, y, p, nb):
    ok = ~np.isnan(s) & ~np.isnan(p)
    s, y, p = s[ok], y[ok], p[ok]
    if len(s) < 200:
        return np.nan
    b = pd.qcut(p, nb, labels=False, duplicates="drop")
    num = den = 0.0
    for k in np.unique(b):
        m = b == k
        a = auc(s[m], y[m]) if 5 <= y[m].sum() < m.sum() - 5 else np.nan
        if a == a:
            num += a * y[m].sum()
            den += y[m].sum()
    return num / den if den else np.nan


def scan(d, ycol, pcol, cols):
    y = d[ycol].to_numpy(float)
    p = d[pcol].to_numpy(float)
    per = d["per"].to_numpy()
    A = per == "A"
    nb = 10 if np.nanmean(y) > 0.04 else 5
    rows = []
    for c in cols:
        x = d[c].to_numpy(float)
        a = auc(x[A], y[A])
        if a != a:
            continue
        s = x if a >= 0.5 else -x
        r = {"sign": c, "what": pretty(c), "direction": "high" if a >= 0.5 else "low"}
        for share, tag in ((0.10, "top 10%"), (0.05, "top 5%")):
            thr = np.nanquantile(s[A], 1 - share)
            r[f"{tag} cut-off"] = thr if a >= 0.5 else -thr
            for k, nm in SEAS.items():
                m = (per == k) & (s >= thr)
                r[f"{tag} matches {nm}"] = int(m.sum())
                r[f"{tag} hit % {nm}"] = y[m].mean() * 100 if m.sum() else np.nan
        for k, nm in SEAS.items():
            m = per == k
            r[f"AUC {nm}"] = auc(s[m], y[m])
            r[f"beyond price AUC {nm}"] = strat_auc(s[m], y[m], p[m], nb) if c != pcol else 0.5
        rows.append(r)
    return pd.DataFrame(rows)


def run():
    d = h3.build()
    for name, ys in PAIRS.items():
        d["y_" + name] = d[ys].max(axis=1)
        a, b = (y[2:] for y in ys)
        d["p_" + name] = d[f"p_{a[0]}/{a[1]}"] + d[f"p_{b[0]}/{b[1]}"]
    cols = features(d)
    targets = [(lab, y, f"p_{lab}") for lab, y in h3.TARGETS.items()] + \
              [(name, "y_" + name, "p_" + name) for name in PAIRS]
    out = []
    for lab, y, p in targets:
        r = scan(d, y, p, cols)
        r.insert(0, "result", lab)
        for k, nm in SEAS.items():
            r.insert(1, f"normal % {nm}", d.loc[d["per"] == k, y].mean() * 100)
        out.append(r)
        print(lab, len(r), flush=True)
    res = pd.concat(out, ignore_index=True)
    res.to_parquet(CACHE / "htft3_signs.parquet")
    return res


if __name__ == "__main__":
    run()
