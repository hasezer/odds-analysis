"""HT/FT study 3: the six 'changing' results 1/X, 2/X, X/1, X/2, 1/2, 2/1 - feature table (cache/htft3.parquet).

One row per finished match with all 9 HT/FT prices. Pre-match information only:
- odds_<label>     Nesine closing odds of every selection (readable thresholds for rules)
- f_<market>       cut-removed chances of every complete market (htft_data.py)
- cs_<score> / hcs_<score>   cut-removed full-time / half-time correct-score chances (listed scores)
- p_<htft> / o_<htft>        HT/FT chances (cut removed) and odds
- q_<htft>, lam_h1 .. lam_a2 HT/FT chances implied by the OTHER markets (htft_poisson.py) and the four goal rates
- d_<htft>         log(p / q): HT/FT price vs the other markets (disagreement)
- c_<ht><ft>       Nesine's 'after half-time' chances: P(full-time ft | half-time ht) from the HT/FT prices
- shape features   2nd-half share of each team's expected goals, favourite strength, goal expectation
- team history     each team's last 10 matches (strictly before): led / trailed / level at half-time, blew a lead,
                   came back, half-time-draw outcomes, 1st- and 2nd-half goals for and against
- league prior     each league's rate of each result over its previous 300 matches, minus what the prices said
- calendar         kick-off hour (Turkey), weekday, days into the league season, days of rest
Targets y_1X, y_2X, y_X1, y_X2, y_12, y_21 (1/0). Period: A = 2024/25 + 2024, B = 2025/26 + 2025, C = 2026/27 + 2026.
"""
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import htft_poisson as hp  # noqa: E402
import load  # noqa: E402
import rule_tester as rt  # noqa: E402
from htft_data import CACHE, HTFT  # noqa: E402

OUT = CACHE / "htft3.parquet"
PER = {"2024/25": "A", "2024": "A", "2025/26": "B", "2025": "B", "2026/27": "C", "2026": "C"}
TARGETS = {"1/X": "y_1X", "2/X": "y_2X", "X/1": "y_X1", "X/2": "y_X2", "1/2": "y_12", "2/1": "y_21"}


def team_history(m):
    """Rolling last-10 tendencies per team from all finished matches in scope (strictly earlier kick-offs)."""
    m = m[(m["status"] == "finished") & m["ht_home"].notna() & m["ft_home"].notna()].copy()
    rows = []
    for side, opp in (("home", "away"), ("away", "home")):
        gf1, ga1 = m[f"ht_{side}"], m[f"ht_{opp}"]
        gf, ga = m[f"ft_{side}"], m[f"ft_{opp}"]
        rows.append(pd.DataFrame({
            "match_id": m["match_id"], "team": m[f"{side}_team_id"], "kick": m["kickoff_utc"], "side": side,
            "led": (gf1 > ga1).astype(float), "trailed": (gf1 < ga1).astype(float), "level": (gf1 == ga1).astype(float),
            "blew": ((gf1 > ga1) & (gf <= ga)).astype(float), "came_back": ((gf1 < ga1) & (gf >= ga)).astype(float),
            "lvl_won": ((gf1 == ga1) & (gf > ga)).astype(float), "lvl_lost": ((gf1 == ga1) & (gf < ga)).astype(float),
            "led_drew": ((gf1 > ga1) & (gf == ga)).astype(float), "trail_drew": ((gf1 < ga1) & (gf == ga)).astype(float),
            "g1f": gf1, "g1a": ga1, "g2f": gf - gf1, "g2a": ga - ga1}))
    t = pd.concat(rows).sort_values(["team", "kick"]).reset_index(drop=True)
    cols = ["led", "trailed", "level", "blew", "came_back", "lvl_won", "lvl_lost", "led_drew", "trail_drew",
            "g1f", "g1a", "g2f", "g2a"]
    g = t.groupby("team")
    roll = g[cols].transform(lambda s: s.shift(1).rolling(10, min_periods=5).mean())
    t[[f"t10_{c}" for c in cols]] = roll.to_numpy()
    t["t10_late_share_f"] = t["t10_g2f"] / (t["t10_g1f"] + t["t10_g2f"]).replace(0, np.nan)
    t["t10_late_share_a"] = t["t10_g2a"] / (t["t10_g1a"] + t["t10_g2a"]).replace(0, np.nan)
    t["rest_days"] = g["kick"].diff().dt.total_seconds() / 86400
    feat = [c for c in t.columns if c.startswith("t10_")] + ["rest_days"]
    h = t[t["side"] == "home"].set_index("match_id")[feat].add_prefix("home_")
    a = t[t["side"] == "away"].set_index("match_id")[feat].add_prefix("away_")
    return h.join(a)


def league_prior(d, window=300):
    """League's earlier rate of each result minus what the HT/FT prices said (previous `window` matches)."""
    d = d.sort_values("kickoff")
    out = pd.DataFrame(index=d.index)
    for lab, y in TARGETS.items():
        r = d[y] - d[f"p_{lab}"]
        out[f"lg_{y}"] = r.groupby(d["league"]).transform(lambda s: s.shift(1).rolling(window, min_periods=100).mean())
    return out


def build(refresh=False):
    if OUT.exists() and not refresh:
        return pd.read_parquet(OUT)
    q = hp.build()
    q = q[~q["match_id"].str.startswith("macko")].set_index("match_id")
    W = rt.wide()
    W = W.loc[W.index.intersection(q.index)]
    labs = [c for c in W.columns if "|" in c and not c.startswith("HT_FT|")]
    d = pd.DataFrame(index=q.index)
    d["league"], d["season"] = q["league_id"], q["season"]
    d["per"] = d["season"].map(PER)
    d["kickoff"] = q["kickoff_utc"]
    d["home"], d["away"] = q["home_team_id"], q["away_team_id"]
    for c in ("ht_home", "ht_away", "ft_home", "ft_away", "htft"):
        d[c] = q[c]
    for lab, y in TARGETS.items():
        d[y] = (q["htft"] == lab).astype(int)
    od = W[labs].reindex(d.index)
    od.columns = [f"odds_{c}" for c in labs]
    for k in HTFT:
        d[f"o_{k}"], d[f"p_{k}"], d[f"q_{k}"] = q[f"o_{k}"], q[f"p_{k}"], q[f"q_{k}"]
        d[f"d_{k}"] = np.log(q[f"p_{k}"] / q[f"q_{k}"].clip(lower=1e-4))
    for ht in "1X2":
        den = sum(q[f"p_{ht}/{ft}"] for ft in "1X2")
        for ft in "1X2":
            d[f"c_{ht}{ft}"] = q[f"p_{ht}/{ft}"] / den
    fcols = [c for c in q.columns if c.startswith("f_")]
    f = q[fcols].copy()
    swapped = od["odds_HT_2H_BTTS||YES/YES"].isna() if "odds_HT_2H_BTTS||YES/YES" in od else None
    if swapped is not None:                 # rule_tester.wide() blanks the label-swapped Oct-Nov 2025 prices
        f.loc[swapped, [c for c in fcols if c.startswith("f_HT_2H_BTTS")]] = np.nan
    # correct-score chances (listed scores, cut spread over them)
    cs = {}
    for mk, pre, need in (("CORRECT_SCORE", "cs_", 20), ("HT_CORRECT_SCORE", "hcs_", 8)):
        cols = [c for c in W.columns if c.startswith(f"{mk}|")]
        inv = 1 / W.loc[d.index, cols]
        ok = inv.notna().sum(axis=1) >= need
        p = inv.div(inv.sum(axis=1), axis=0).where(ok, np.nan)
        p.columns = [pre + c.split("|")[-1] for c in cols]
        cs[mk] = p
    d = pd.concat([d, od, f, cs["CORRECT_SCORE"], cs["HT_CORRECT_SCORE"]], axis=1)
    for c in ("lam_h1", "lam_a1", "lam_h2", "lam_a2", "fit_rmse"):
        d[c] = q[c]
    d["lam_tot"] = d[["lam_h1", "lam_a1", "lam_h2", "lam_a2"]].sum(axis=1)
    d["lam_1h_share"] = (d["lam_h1"] + d["lam_a1"]) / d["lam_tot"]
    d["home_2h_share"] = d["lam_h2"] / (d["lam_h1"] + d["lam_h2"])
    d["away_2h_share"] = d["lam_a2"] / (d["lam_a1"] + d["lam_a2"])
    d["home_minus_away"] = q["f_1X2__1"] - q["f_1X2__2"]
    d["fav_p"] = np.maximum(q["f_1X2__1"], q["f_1X2__2"])
    # team history, league prior, calendar
    th = team_history(load.matches())
    d = d.join(th)
    d = d.join(league_prior(d))
    kt = pd.DatetimeIndex(d["kickoff"]).tz_convert("Europe/Istanbul")
    d["kick_hour_tr"] = kt.hour + kt.minute / 60
    d["weekday"] = kt.dayofweek
    first = d.groupby(["league", "season"])["kickoff"].transform("min")
    d["season_day"] = (d["kickoff"] - first).dt.total_seconds() / 86400
    d = d[d["per"].notna()]
    d.reset_index(names="match_id").to_parquet(OUT)
    return d.reset_index(names="match_id")


if __name__ == "__main__":
    d = build(refresh=True)
    print(d.shape, d["per"].value_counts().to_dict())
    print({y: round(d[y].mean() * 100, 2) for y in TARGETS.values()})
