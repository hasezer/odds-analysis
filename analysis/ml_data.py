"""Data for the all-markets machine-learning study (cached in analysis/cache/).

ml_match.parquet  one row per match: info, the four fitted goal rates (home/away x 1st/2nd half, see
                  htft_poisson.py), expected corners, pre-match team form (only matches played BEFORE kickoff)
ml_sel.parquet    one row per priced, settled selection of every collected market: closing odds, fair probability
                  (cut removed within the market), market margin, result, and q = the selection's probability under
                  the goal-rate model (an independent price built from the core markets)
"""
from pathlib import Path
import os
import sys

import numpy as np
import pandas as pd
from scipy.optimize import brentq
from scipy.stats import poisson

sys.path.insert(0, str(Path(__file__).resolve().parent))
import load  # noqa: E402
import htft_poisson as hp  # noqa: E402
from htft_data import CACHE, DISCOVERY, EXPECTED_SIZE  # noqa: E402

G = 8                                                     # 0..7 goals per team per half
_g = np.arange(G)
H1, A1, H2, A2 = [a.ravel() for a in np.meshgrid(_g, _g, _g, _g, indexing="ij")]
HH, AA = H1 + H2, A1 + A2
T, T1, T2 = HH + AA, H1 + A1, H2 + A2


def _res(h, a):
    return np.where(h > a, "1", np.where(h == a, "X", "2"))


FT, HT, SH = _res(HH, AA), _res(H1, A1), _res(H2, A2)


def predicate(market, line, sel, all_keys):
    """Boolean mask over the 4096 (h1, a1, h2, a2) cells where the selection wins; None if not modelled."""
    L = line
    yes = lambda m, s: m if s == "YES" else ~m
    ou = lambda x, s: (x > L) if s == "OVER" else (x < L)
    if market == "1X2":
        return FT == sel
    if market == "HT_1X2":
        return HT == sel
    if market == "2H_1X2":
        return SH == sel
    if market == "DC":
        return np.isin(FT, list(sel.replace("X", "X")))
    if market == "OU":
        return ou(T, sel)
    if market == "HT_OU":
        return ou(T1, sel)
    if market == "TEAM_OU_HOME":
        return ou(HH, sel)
    if market == "TEAM_OU_AWAY":
        return ou(AA, sel)
    if market == "HT_TEAM_OU_HOME":
        return ou(H1, sel)
    if market == "HT_TEAM_OU_AWAY":
        return ou(A1, sel)
    if market == "BTTS":
        return yes((HH > 0) & (AA > 0), sel)
    if market == "HT_BTTS":
        return yes((H1 > 0) & (A1 > 0), sel)
    if market == "2H_BTTS":
        return yes((H2 > 0) & (A2 > 0), sel)
    if market == "HT_2H_BTTS":
        a, b = sel.split("/")
        return yes((H1 > 0) & (A1 > 0), a) & yes((H2 > 0) & (A2 > 0), b)
    if market == "GOAL_RANGE":
        lo, hi = (6, 99) if sel == "6+" else map(int, sel.split("-"))
        return (T >= lo) & (T <= hi)
    if market == "BOTH_HALVES_OVER":
        return yes((T1 > 1.5) & (T2 > 1.5), sel)
    if market == "TEAM_WIN_EITHER_HALF_HOME":
        return yes((H1 > A1) | (H2 > A2), sel)
    if market == "TEAM_WIN_EITHER_HALF_AWAY":
        return yes((A1 > H1) | (A2 > H2), sel)
    if market == "TEAM_WIN_BOTH_HALVES_HOME":
        return yes((H1 > A1) & (H2 > A2), sel)
    if market == "TEAM_WIN_BOTH_HALVES_AWAY":
        return yes((A1 > H1) & (A2 > H2), sel)
    if market in ("1X2_AND_OU", "1X2_AND_BTTS", "HT_1X2_AND_HT_OU", "HT_1X2_AND_HT_BTTS", "OU_AND_BTTS"):
        a, b = sel.split("&")
        if market == "1X2_AND_OU":
            return (FT == a) & ou(T, b)
        if market == "1X2_AND_BTTS":
            return (FT == a) & yes((HH > 0) & (AA > 0), b)
        if market == "HT_1X2_AND_HT_OU":
            return (HT == a) & ou(T1, b)
        if market == "HT_1X2_AND_HT_BTTS":
            return (HT == a) & yes((H1 > 0) & (A1 > 0), b)
        return ou(T, a) & yes((HH > 0) & (AA > 0), b)
    if market == "HT_FT":
        a, b = sel.split("/")
        return (HT == a) & (FT == b)
    if market in ("CORRECT_SCORE", "HT_CORRECT_SCORE"):
        hs, as_ = (HH, AA) if market == "CORRECT_SCORE" else (H1, A1)
        if sel == "OTHER":
            m = np.ones_like(hs, dtype=bool)
            for k in all_keys:
                if k != "OTHER":
                    x, y = map(int, k.split("-"))
                    m &= ~((hs == x) & (as_ == y))
            return m
        x, y = map(int, sel.split("-"))
        return (hs == x) & (as_ == y)
    return None


def _fair(d):
    key = ["match_id", "market_key", "line"]
    d = d.assign(implied=1 / d["closing_odds"])
    n = d.groupby(key, dropna=False)["implied"].transform("size")
    s = d.groupby(key, dropna=False)["implied"].transform("sum")
    need = d["market_key"].map(EXPECTED_SIZE).fillna(2)
    complete = (n == need) | d["market_key"].isin(["CORRECT_SCORE", "HT_CORRECT_SCORE"])
    d["fair"] = np.where(complete & (n >= 2), d["implied"] / np.where(d["market_key"] == "DC", s / 2, s), np.nan)
    d["overround"] = np.where(complete & (n >= 2), np.where(d["market_key"] == "DC", s / 2, s), np.nan)
    return d


def _corner_lambda(line, p_over):
    """Poisson rate whose P(total > line) equals p_over."""
    try:
        return brentq(lambda lam: poisson.sf(int(line), lam) - p_over, 0.5, 40)
    except ValueError:
        return np.nan


def build(refresh=False):
    CACHE.mkdir(exist_ok=True)
    fm, fs = CACHE / "ml_match.parquet", CACHE / "ml_sel.parquet"
    if fm.exists() and fs.exists() and not refresh:
        return pd.read_parquet(fm), pd.read_parquet(fs)

    f = load.flat()
    f = f[f["in_default_analysis"] & f["closing_odds"].notna()]
    sel = _fair(f[["match_id", "market_key", "market_type_id", "line", "selection_key", "closing_odds", "hit"]].copy())
    sel["hit"] = sel["hit"].astype(bool)

    # ---- goal-rate fit for every match (same model as the HT/FT study)
    x = sel[sel["fair"].notna()]
    x = x.assign(col="f_" + x["market_key"] + "_" + x["line"].map(lambda v: "" if pd.isna(v) else f"{v:g}") + "_"
                 + x["selection_key"])
    wide = x[x["col"].isin(hp.TARGETS)].pivot_table(index="match_id", columns="col", values="fair")
    wide = wide.reindex(columns=hp.TARGETS)
    wide = wide[wide.notna().sum(axis=1) >= 10]        # need enough core markets to fit four rates
    from concurrent.futures import ProcessPoolExecutor
    parts = [wide.iloc[ix] for ix in np.array_split(np.arange(len(wide)), (os.cpu_count() or 1) * 4)]
    with ProcessPoolExecutor() as ex:
        lam = pd.concat(ex.map(hp._fit_chunk, parts))[["lam_h1", "lam_a1", "lam_h2", "lam_a2", "fit_rmse"]]

    # ---- model probability q for every selection
    keys = sel.groupby("market_key")["selection_key"].unique().to_dict()
    combos = sel[["market_key", "line", "selection_key"]].drop_duplicates()
    masks, cols = [], []
    for r in combos.itertuples(index=False):
        m = predicate(r.market_key, r.line, r.selection_key, keys.get(r.market_key, []))
        if m is not None:
            masks.append(m.astype(np.float32)); cols.append((r.market_key, r.line, r.selection_key))
    M = np.stack(masks, axis=1)                                                     # 4096 x S
    L_ = lam.to_numpy()[:, :4]
    qs = []
    for ix in np.array_split(np.arange(len(L_)), max(1, len(L_) // 1500)):
        pm = [poisson.pmf(_g[None, :], L_[ix, j][:, None]).astype(np.float32) for j in range(4)]
        joint = (pm[0][:, :, None, None, None] * pm[1][:, None, :, None, None] * pm[2][:, None, None, :, None]
                 * pm[3][:, None, None, None, :]).reshape(len(ix), -1)
        qs.append(joint @ M)
    Q = pd.DataFrame(np.vstack(qs), index=lam.index, columns=pd.MultiIndex.from_tuples(cols))
    q_long = Q.stack(level=[0, 1, 2], future_stack=True).rename("q").reset_index()
    q_long.columns = ["match_id", "market_key", "line", "selection_key", "q"]
    sel["line_k"] = sel["line"].fillna(-1)
    q_long["line_k"] = q_long["line"].fillna(-1)
    sel = sel.merge(q_long.drop(columns="line"), on=["match_id", "market_key", "line_k", "selection_key"], how="left")
    sel = sel.drop(columns="line_k")

    # ---- match table
    m = load.matches().set_index("match_id")
    mt = m.loc[m.index.isin(sel["match_id"].unique()) & (m["status"] == "finished")].join(lam, how="inner")
    mt = mt[["league_id", "season", "season_type", "kickoff_utc", "home_team_id", "away_team_id", "ht_home",
             "ht_away", "ft_home", "ft_away"] + list(lam.columns)]
    mt["period"] = np.where(mt["season"].isin(DISCOVERY), "discovery", "check")
    cs = x[(x["market_key"] == "CORNERS_OU") & (x["selection_key"] == "OVER")].copy()
    cs["gap"] = (cs["fair"] - .5).abs()
    cs = cs.sort_values("gap").drop_duplicates("match_id")
    cs["corners_exp"] = [_corner_lambda(l, p) for l, p in zip(cs["line"], cs["fair"])]
    mt = mt.join(cs.set_index("match_id")[["corners_exp"]])
    mt = add_form(mt.reset_index())
    mt.to_parquet(fm)
    sel.to_parquet(fs)
    return mt, sel


def add_form(mt):
    """Rolling pre-match team form from results, statistics and the market's own expectations."""
    st = load._read("stats").pivot(index="match_id", columns="team_side",
                                   values=["corners", "shots", "shots_on_target", "possession_pct"])
    st.columns = [f"{a}_{b}" for a, b in st.columns]
    d = mt.join(st, on="match_id")
    rows = []
    for side, opp in (("home", "away"), ("away", "home")):
        h1, h2 = ("lam_h1", "lam_h2") if side == "home" else ("lam_a1", "lam_a2")
        o1, o2 = ("lam_a1", "lam_a2") if side == "home" else ("lam_h1", "lam_h2")
        gf, ga = ("ft_home", "ft_away") if side == "home" else ("ft_away", "ft_home")
        hf, ha = ("ht_home", "ht_away") if side == "home" else ("ht_away", "ht_home")
        rows.append(pd.DataFrame({
            "match_id": d["match_id"], "team": d[f"{side}_team_id"], "kick": d["kickoff_utc"], "venue": side,
            "gf": d[gf], "ga": d[ga], "ht_gf": d[hf], "ht_ga": d[ha],
            "xgf": d[h1] + d[h2], "xga": d[o1] + d[o2],                 # market-expected goals for / against
            "sh": d[f"shots_{side}"], "sha": d[f"shots_{opp}"],
            "sot": d[f"shots_on_target_{side}"], "sota": d[f"shots_on_target_{opp}"],
            "cor": d[f"corners_{side}"], "cora": d[f"corners_{opp}"], "poss": d[f"possession_pct_{side}"],
            "cor_tot": d["corners_home"] + d["corners_away"], "cor_exp": d["corners_exp"],
        }))
    t = pd.concat(rows).sort_values(["team", "kick"]).reset_index(drop=True)
    t["res_gf"] = t["gf"] - t["xgf"]                    # scored more than the market expected
    t["res_ga"] = t["ga"] - t["xga"]
    t["res_cor"] = t["cor_tot"] - t["cor_exp"]
    t["pts"] = np.where(t["gf"] > t["ga"], 3, np.where(t["gf"] == t["ga"], 1, 0))
    t["sot_share"] = t["sot"] / (t["sot"] + t["sota"])
    t["conv"] = t["gf"] - 0.3 * t["sot"]                # goals above a flat 30% shot-on-target conversion
    t["sh2"] = t["gf"] - t["ht_gf"]
    feats = ["gf", "ga", "xgf", "xga", "res_gf", "res_ga", "sh", "sha", "sot", "sota", "sot_share", "cor", "cora",
             "res_cor", "poss", "pts", "conv", "sh2"]
    g = t.groupby("team")
    out = t[["match_id", "venue"]].copy()
    for c in feats:
        s = g[c].shift(1)
        out[f"r6_{c}"] = s.groupby(t["team"]).transform(lambda v: v.rolling(6, min_periods=3).mean())
        if c in ("res_gf", "res_ga", "sot", "sota", "sot_share", "res_cor", "conv"):
            out[f"r15_{c}"] = s.groupby(t["team"]).transform(lambda v: v.rolling(15, min_periods=6).mean())
    out["rest"] = (t["kick"] - g["kick"].shift(1)).dt.total_seconds() / 86400
    out["n_prev"] = g.cumcount()
    hh = out[out["venue"] == "home"].drop(columns="venue").set_index("match_id").add_prefix("h_")
    aa = out[out["venue"] == "away"].drop(columns="venue").set_index("match_id").add_prefix("a_")
    mt = mt.join(hh, on="match_id").join(aa, on="match_id")
    mt["phase"] = mt.groupby(["league_id", "season"])["kickoff_utc"].rank(pct=True)
    mt["hour_utc"] = mt["kickoff_utc"].dt.hour
    mt["weekday"] = mt["kickoff_utc"].dt.weekday
    return mt


if __name__ == "__main__":
    mt, sel = build(refresh=True)
    print(mt.shape, sel.shape)
    print(sel["q"].notna().groupby(sel["market_key"]).mean().round(3).to_string())
