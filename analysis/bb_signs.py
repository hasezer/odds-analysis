"""BTTS in both halves, step 1: every single pre-match sign (about 470).

For each sign: direction and cut-offs are set on the first season where the sign exists for at least 30% of the
matches ('found on': 2024/25, or 2025/26 for Nesine's own both-halves price and the 2nd-half BTTS market, which
start then). Then the hit rate of its top 10% / 5% / 2% is measured in every season, with the AUC (0.5 = no
information), the 'beyond the model' AUC (inside groups of matches with the same chance from the goal markets, q_bb,
which exists in every season) and the 'beyond the price' AUC (inside groups with the same Nesine both-halves price,
2025/26 on). Writes cache/bb_signs.parquet.
"""
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bb_data  # noqa: E402
from htft3_signs import pretty as pretty3, strat_auc  # noqa: E402
from six_plus import auc  # noqa: E402

SEAS = {"A": "2024/25", "B": "2025/26", "C": "2026/27"}
META = {"match_id", "league", "season", "per", "kickoff", "home", "away", "ht_home", "ht_away", "ft_home", "ft_away"}
SHARES = ((0.10, "top 10%"), (0.05, "top 5%"), (0.02, "top 2%"))
EV = {"s1": "scored in the 1st half", "s2": "scored in the 2nd half", "sb": "scored in both halves",
      "c1": "conceded in the 1st half", "c2": "conceded in the 2nd half", "cb": "conceded in both halves",
      "b1": "both scored in the 1st half", "b2": "both scored in the 2nd half", "bb": "both scored in both halves",
      "g1f": "1st-half goals scored", "g1a": "1st-half goals conceded", "g2f": "2nd-half goals scored",
      "g2a": "2nd-half goals conceded"}
WIN = {"t10": "last 10", "t20": "last 20", "v10": "last 10 at this venue", "ps": "previous season"}
OWN = {"q_bb": "BTTS both halves: chance from the goal markets (model)",
       "q_b1": "1st-half BTTS: chance from the goal markets (model)",
       "q_b2": "2nd-half BTTS: chance from the goal markets (model)",
       "p_bb": "BTTS both halves: Nesine's own chance", "o_bb": "BTTS both halves: Nesine's own odds",
       "lam_home": "expected goals, home team", "lam_away": "expected goals, away team",
       "lam_tot": "expected goals in the match",
       "s_weaker_attack": "expected goals of the weaker attack",
       "s_weakest_half_rate": "smallest of the four half goal rates",
       "s_balance": "balance: weaker attack / stronger attack",
       "s_both2_model": "both teams 2+ goals (model)", "s_both2_market": "both teams 2+ goals (team-goals markets)",
       "s_both2_market_min": "the smaller of the two teams' 2+ goal chances",
       "s_half_markets": "1st-half BTTS chance x 2nd-half BTTS chance (Nesine's half markets)",
       "s_1h_market_x_2h_model": "1st-half BTTS chance (market) x 2nd-half BTTS chance (model)",
       "s_cs_both2": "correct scores with both teams on 2+ goals (total chance)",
       "s_nesine_2h_given_1h": "Nesine: 2nd-half BTTS chance if both score in the 1st half",
       "s_nesine_dependence": "Nesine: how much it links the two halves",
       "lg_bb_rate": "league's BTTS-both-halves rate, previous 300 matches",
       "lg_bb_extra": "league's BTTS-both-halves rate beyond the model, previous 300 matches",
       "lg_b1_rate": "league's 1st-half BTTS rate, previous 300 matches",
       "lg_b2_rate": "league's 2nd-half BTTS rate, previous 300 matches",
       "month": "month", "fit_rmse": "goal-markets model fit error"}


def pretty(c):
    if c in OWN:
        return OWN[c]
    for side in ("home", "away"):
        for w, wn in WIN.items():
            pre = f"{side}_{w}_"
            if c.startswith(pre) and c[len(pre):] in EV:
                return f"{side} team, {wn}: {EV[c[len(pre):]]}"
    return pretty3(c)


def features(d):
    out = []
    for c in d.columns:
        if c in META or c.startswith("y_") or not pd.api.types.is_numeric_dtype(d[c]):
            continue
        if c.startswith("odds_HT_2H_BTTS") or c.startswith("f_HT_2H_BTTS"):
            if c not in ("odds_HT_2H_BTTS||YES/YES", "f_HT_2H_BTTS__YES/YES"):
                continue                       # the other three both-halves selections only restate the price
        cover = d.groupby("per")[c].apply(lambda s: s.notna().mean())
        if cover.max() < 0.3 or d[c].nunique() < 5:
            continue
        out.append(c)
    return out


def found_on(d, c):
    """The first season where the sign exists for >= 30% of matches."""
    for k in "ABC":
        if d.loc[d["per"] == k, c].notna().mean() >= 0.3:
            return k
    return None


def scan(d, ycol="y_bb", cols=None):
    y = d[ycol].to_numpy(float)
    per = d["per"].to_numpy()
    q = d["q_bb"].to_numpy(float)
    p = d["p_bb"].to_numpy(float)
    rows = []
    for c in cols:
        k0 = found_on(d, c)
        if k0 is None or k0 == "C":
            continue
        x = d[c].to_numpy(float)
        F = per == k0
        a = auc(x[F], y[F])
        if a != a:
            continue
        s = x if a >= 0.5 else -x
        r = {"sign": c, "what": pretty(c), "found on": SEAS[k0], "direction": "high" if a >= 0.5 else "low"}
        for share, tag in SHARES:
            thr = np.nanquantile(s[F], 1 - share)
            r[f"{tag} cut-off"] = thr if a >= 0.5 else -thr
            for k, nm in SEAS.items():
                m = (per == k) & (s >= thr)
                r[f"{tag} matches {nm}"] = int(m.sum())
                r[f"{tag} hit % {nm}"] = y[m].mean() * 100 if m.sum() else np.nan
        for k, nm in SEAS.items():
            m = per == k
            r[f"cover {nm}"] = float(np.mean(~np.isnan(x[m])))
            r[f"AUC {nm}"] = auc(s[m], y[m])
            r[f"beyond model AUC {nm}"] = strat_auc(s[m], y[m], q[m], 10) if c != "q_bb" else 0.5
            r[f"beyond price AUC {nm}"] = (strat_auc(s[m], y[m], p[m], 5) if k != "A" and c not in ("p_bb", "o_bb")
                                           else np.nan)
        rows.append(r)
    return pd.DataFrame(rows)


def run():
    d = bb_data.build()
    cols = features(d)
    out = []
    for ycol, lab in (("y_bb", "BTTS both halves"), ("y_b1", "1st-half BTTS"), ("y_b2", "2nd-half BTTS")):
        r = scan(d, ycol, cols)
        r.insert(0, "target", lab)
        for k, nm in SEAS.items():
            r.insert(1, f"normal % {nm}", d.loc[d["per"] == k, ycol].mean() * 100)
        out.append(r)
        print(lab, len(r), "signs", flush=True)
    S = pd.concat(out, ignore_index=True)
    S.to_parquet(bb_data.CACHE / "bb_signs.parquet")
    return S


if __name__ == "__main__":
    S = run()
    pd.set_option("display.width", 250)
    pd.set_option("display.max_colwidth", 70)
    s = S[S["target"] == "BTTS both halves"].copy()
    s["later top10"] = s[["top 10% hit % 2025/26", "top 10% hit % 2026/27"]].mean(axis=1)
    cols = ["what", "found on", "direction", "top 10% hit % 2024/25", "top 10% hit % 2025/26",
            "top 10% hit % 2026/27", "AUC 2024/25", "AUC 2025/26", "AUC 2026/27", "beyond model AUC 2025/26",
            "beyond model AUC 2026/27"]
    print(s.sort_values("AUC 2024/25", ascending=False)[cols].head(40).round(3).to_string(index=False))
