"""BTTS in both halves (both teams score in the 1st half AND both score in the 2nd half): feature table.

One row per finished match in scope (2024/25 + 2024, 2025/26 + 2025, 2026/27 + 2026), pre-match information only:
- odds_<label>            Nesine closing odds of every selection (rule_tester.wide(); the label-swapped Oct-Nov 2025
                          HT_2H_BTTS prices are blanked)
- f_<market>_<line>_<sel> cut-removed chances of every complete market (htft_data._fair)
- cs_<score> / hcs_<score> full-time / half-time correct-score chances (cut spread over the listed scores)
- lam_h1 .. lam_a2        four goal rates (home / away x 1st / 2nd half) fitted to the goal and result markets
                          (htft_poisson: team goals, total goals, 1X2 of each half). The BTTS markets are NOT used.
- p_bb / o_bb             Nesine's own chance / odds for BTTS in both halves (HT_2H_BTTS YES/YES): 2025/26 on only
- q_bb, q_b1, q_b2        BTTS in both halves / 1st half / 2nd half from the four goal rates (independent Poisson)
- s_*                     structural signs fixed in advance (weaker attack, both teams 2+ goals, half-market products)
- team habits             each team's last 10 / last 20 / previous season (strictly earlier matches): scored and
                          conceded in each half, scored / conceded in both halves, BTTS in the 1st / 2nd / both halves
- league history          league's BTTS-both-halves rate over its previous 300 matches, raw and minus q_bb
- calendar                kick-off hour (Turkey), weekday, month, days into the league season, rest days
Targets: y_bb (BTTS in both halves), y_b1 (1st-half BTTS), y_b2 (2nd-half BTTS).
Periods: A = 2024/25 + 2024, B = 2025/26 + 2025, C = 2026/27 + 2026. Writes cache/bb.parquet.
"""
from concurrent.futures import ProcessPoolExecutor
import os
from pathlib import Path
import re
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import htft_data as hd  # noqa: E402
import htft_poisson as hp  # noqa: E402
import load  # noqa: E402
import rule_tester as rt  # noqa: E402
from htft3_data import PER  # noqa: E402

CACHE = hd.CACHE
OUT = CACHE / "bb.parquet"
EVENTS = ["s1", "s2", "sb", "c1", "c2", "cb", "b1", "b2", "bb", "g1f", "g1a", "g2f", "g2a"]


def scope():
    m = load.matches()
    m = m[(m["status"] == "finished") & m["ht_home"].notna() & m["ft_home"].notna()]
    m = m[~m["match_id"].astype(str).str.startswith("macko")].copy()
    m["per"] = m["season"].map(PER)
    return m[m["per"].notna()].reset_index(drop=True)


def fair_wide(ids):
    """Cut-removed chances of every complete market, one column per selection (htft_data naming)."""
    f = load.flat()
    f = f[f["in_default_analysis"] & f["closing_odds"].notna() & f["match_id"].isin(ids)]
    f = f[f["market_key"].isin(hd.HINT_MARKETS)]
    f = hd._fair(f[["match_id", "market_key", "line", "selection_key", "closing_odds", "hit"]])
    x = f[f["fair"].notna()]
    x = x.assign(col="f_" + x["market_key"] + "_" + x["line"].map(lambda v: "" if pd.isna(v) else f"{v:g}") + "_"
                 + x["selection_key"])
    return x.pivot_table(index="match_id", columns="col", values="fair")


def goal_rates(f):
    """The four goal rates per match (htft_poisson.fit), in parallel."""
    w = f.reindex(columns=hp.TARGETS)
    w = w[w.notna().sum(axis=1) >= 6]                  # enough goal / result markets to fit four rates
    parts = [w.iloc[ix] for ix in np.array_split(np.arange(len(w)), (os.cpu_count() or 1) * 4)]
    with ProcessPoolExecutor() as ex:
        q = pd.concat(ex.map(hp.fit, parts))
    return q[["lam_h1", "lam_a1", "lam_h2", "lam_a2", "fit_rmse"]]


def team_habits(m):
    """Per team and match: rates over the team's previous 10 and 20 matches and its previous season."""
    rows = []
    for side, opp in (("home", "away"), ("away", "home")):
        gf1, ga1 = m[f"ht_{side}"], m[f"ht_{opp}"]
        gf2, ga2 = m[f"ft_{side}"] - gf1, m[f"ft_{opp}"] - ga1
        rows.append(pd.DataFrame({
            "match_id": m["match_id"], "team": m[f"{side}_team_id"], "kick": m["kickoff_utc"], "side": side,
            "per": m["per"],
            "s1": (gf1 > 0).astype(float), "s2": (gf2 > 0).astype(float), "sb": ((gf1 > 0) & (gf2 > 0)).astype(float),
            "c1": (ga1 > 0).astype(float), "c2": (ga2 > 0).astype(float), "cb": ((ga1 > 0) & (ga2 > 0)).astype(float),
            "b1": ((gf1 > 0) & (ga1 > 0)).astype(float), "b2": ((gf2 > 0) & (ga2 > 0)).astype(float),
            "bb": ((gf1 > 0) & (ga1 > 0) & (gf2 > 0) & (ga2 > 0)).astype(float),
            "g1f": gf1, "g1a": ga1, "g2f": gf2, "g2a": ga2}))
    t = pd.concat(rows).sort_values(["team", "kick"]).reset_index(drop=True)
    g = t.groupby("team")
    for n in (10, 20):
        roll = g[EVENTS].transform(lambda s: s.shift(1).rolling(n, min_periods=n // 2).mean())
        t[[f"t{n}_{e}" for e in EVENTS]] = roll.to_numpy()
    # the same side only (a home team's previous home games, an away team's previous away games)
    gv = t.groupby(["team", "side"])
    roll = gv[EVENTS].transform(lambda s: s.shift(1).rolling(10, min_periods=5).mean())
    t[[f"v10_{e}" for e in EVENTS]] = roll.to_numpy()
    ps = t.groupby(["team", "per"])[EVENTS].mean()
    ps.columns = [f"ps_{e}" for e in EVENTS]
    ps = ps.reset_index()
    ps["per"] = ps["per"].map({"A": "B", "B": "C"})            # last season's rates are known this season
    t = t.merge(ps.dropna(subset=["per"]), on=["team", "per"], how="left")
    t["rest_days"] = t.groupby("team")["kick"].diff().dt.total_seconds() / 86400
    feat = [c for c in t.columns if c.startswith(("t10_", "t20_", "v10_", "ps_"))] + ["rest_days"]
    h = t[t["side"] == "home"].set_index("match_id")[feat].add_prefix("home_")
    a = t[t["side"] == "away"].set_index("match_id")[feat].add_prefix("away_")
    return h.join(a)


def p_score(lam, k):
    """P(at least k goals) for a Poisson rate."""
    lam = np.asarray(lam, float)
    return 1 - sum(np.exp(-lam) * lam ** i / np.prod(range(1, i + 1)) for i in range(k))


def structural(d):
    """Signs fixed in advance from what the result needs: each team scores in each half."""
    s = pd.DataFrame(index=d.index)
    l1h, l1a, l2h, l2a = (d[c] for c in ("lam_h1", "lam_a1", "lam_h2", "lam_a2"))
    s["q_b1"] = p_score(l1h, 1) * p_score(l1a, 1)
    s["q_b2"] = p_score(l2h, 1) * p_score(l2a, 1)
    s["q_bb"] = s["q_b1"] * s["q_b2"]
    lh, la = l1h + l2h, l1a + l2a
    s["lam_home"], s["lam_away"], s["lam_tot"] = lh, la, lh + la
    s["s_weaker_attack"] = np.minimum(lh, la)
    s["s_weakest_half_rate"] = np.minimum.reduce([l1h, l1a, l2h, l2a])
    s["s_balance"] = np.minimum(lh, la) / np.maximum(lh, la)
    s["s_both2_model"] = p_score(lh, 2) * p_score(la, 2)
    tt_h, tt_a = d.get("f_TEAM_OU_HOME_1.5_OVER"), d.get("f_TEAM_OU_AWAY_1.5_OVER")
    s["s_both2_market"] = tt_h * tt_a
    s["s_both2_market_min"] = np.minimum(tt_h, tt_a)
    s["s_half_markets"] = d.get("f_HT_BTTS__YES") * d.get("f_2H_BTTS__YES")      # 2025/26 on mostly
    s["s_1h_market_x_2h_model"] = d.get("f_HT_BTTS__YES") * s["q_b2"]
    cs = [c for c in d.columns if c.startswith("cs_")]
    both2 = [c for c in cs if re.fullmatch(r"\d+-\d+", c[3:]) and min(map(int, c[3:].split("-"))) >= 2]
    s["s_cs_both2"] = d[both2].sum(axis=1, min_count=1).where(d[cs].notna().any(axis=1))
    # Nesine's own view of the halves (2025/26 on): P(2nd-half BTTS | 1st-half BTTS) and the dependence it assumes
    yy, yn, ny = (d.get(f"f_HT_2H_BTTS__{k}") for k in ("YES/YES", "YES/NO", "NO/YES"))
    if yy is not None:
        s["s_nesine_2h_given_1h"] = yy / (yy + yn)
        s["s_nesine_dependence"] = yy / ((yy + yn) * (yy + ny))
    return s


def league_history(d, window=300):
    d = d.sort_values("kickoff")
    out = pd.DataFrame(index=d.index)
    g = d.groupby("league")
    out["lg_bb_rate"] = g["y_bb"].transform(lambda s: s.shift(1).rolling(window, min_periods=100).mean())
    r = d["y_bb"] - d["q_bb"]
    out["lg_bb_extra"] = r.groupby(d["league"]).transform(lambda s: s.shift(1).rolling(window, min_periods=100).mean())
    out["lg_b1_rate"] = g["y_b1"].transform(lambda s: s.shift(1).rolling(window, min_periods=100).mean())
    out["lg_b2_rate"] = g["y_b2"].transform(lambda s: s.shift(1).rolling(window, min_periods=100).mean())
    return out


def build(refresh=False):
    if OUT.exists() and not refresh:
        return pd.read_parquet(OUT)
    m = scope()
    ids = m["match_id"]
    f = fair_wide(ids)
    W = rt.wide().reindex(ids)
    labs = [c for c in W.columns if "|" in c]
    od = W[labs].copy()
    od.columns = [f"odds_{c}" for c in labs]
    if "HT_2H_BTTS||YES/YES" in W:                     # wide() blanks the label-swapped Oct-Nov 2025 prices
        raw = f.reindex(ids)
        swapped = raw["f_HT_2H_BTTS__YES/YES"].notna() & W["HT_2H_BTTS||YES/YES"].isna()
        f.loc[swapped[swapped].index.intersection(f.index), [c for c in f.columns if c.startswith("f_HT_2H_BTTS")]] = \
            np.nan
    cs = {}
    for mk, pre, need in (("CORRECT_SCORE", "cs_", 20), ("HT_CORRECT_SCORE", "hcs_", 8)):
        cols = [c for c in W.columns if c.startswith(f"{mk}|")]
        inv = 1 / W[cols]
        ok = inv.notna().sum(axis=1) >= need
        p = inv.div(inv.sum(axis=1), axis=0).where(ok, np.nan)
        p.columns = [pre + c.split("|")[-1] for c in cols]
        cs[mk] = p
    d = m.set_index("match_id")[["league_id", "season", "per", "kickoff_utc", "home_team_id", "away_team_id",
                                 "ht_home", "ht_away", "ft_home", "ft_away"]]
    d = d.rename(columns={"league_id": "league", "kickoff_utc": "kickoff", "home_team_id": "home",
                          "away_team_id": "away"})
    h1, a1 = d["ht_home"], d["ht_away"]
    h2, a2 = d["ft_home"] - h1, d["ft_away"] - a1
    d["y_b1"] = ((h1 > 0) & (a1 > 0)).astype(int)
    d["y_b2"] = ((h2 > 0) & (a2 > 0)).astype(int)
    d["y_bb"] = d["y_b1"] * d["y_b2"]
    d = pd.concat([d, od, f.reindex(d.index), cs["CORRECT_SCORE"], cs["HT_CORRECT_SCORE"]], axis=1)
    d = d.join(goal_rates(f))
    d["p_bb"] = d.get("f_HT_2H_BTTS__YES/YES")
    d["o_bb"] = d.get("odds_HT_2H_BTTS||YES/YES")
    d = pd.concat([d, structural(d)], axis=1)
    d = d.join(team_habits(m))
    d = d.join(league_history(d))
    d = d.copy()                                       # de-fragment before adding the calendar columns
    kt = pd.DatetimeIndex(d["kickoff"]).tz_convert("Europe/Istanbul")
    d["kick_hour_tr"] = kt.hour + kt.minute / 60
    d["weekday"] = kt.dayofweek
    d["month"] = kt.month
    first = d.groupby(["league", "season"])["kickoff"].transform("min")
    d["season_day"] = (d["kickoff"] - first).dt.total_seconds() / 86400
    d = d.reset_index(names="match_id")
    d.to_parquet(OUT)
    return d


if __name__ == "__main__":
    d = build(refresh=True)
    print(d.shape, d["per"].value_counts().to_dict())
    print({y: round(d[y].mean() * 100, 2) for y in ("y_bb", "y_b1", "y_b2")})
    print("own price present:", d.groupby("per")["p_bb"].apply(lambda s: round(s.notna().mean(), 3)).to_dict())
    print("goal rates present:", d.groupby("per")["lam_h1"].apply(lambda s: round(s.notna().mean(), 3)).to_dict())
