"""Test hand-written betting rules (e.g. from tipsters) on all our matches.

A rule = a condition on the match's Nesine closing odds (and, if needed, the teams' previous matches) + a bet.
For every rule: matches that fit, hit rate per season vs normal, hit rate needed to break even at the odds paid,
return per 100 staked, and a luck check (z-score of the return: |z| < 2 is within normal luck).
Seasons: 2024/25 + 2024, 2025/26 + 2025, 2026/27 + 2026 so far. Outcomes are computed from the scores.

    import rule_tester as rt
    W = rt.wide()                       # one row per finished match: odds of every selection + scores
    rt.test(W, condition_mask, bet_key_or_series, odds_series)
"""
from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hi_data  # noqa: E402
import load  # noqa: E402
import miner_data as mdat  # noqa: E402
import ml_data as md  # noqa: E402

PER = {"2024/25": "2024/25", "2024": "2024/25", "2025/26": "2025/26", "2025": "2025/26", "2026/27": "2026/27",
       "2026": "2026/27"}


def wide():
    f = load.flat()
    f = f[f["closing_odds"].notna()]
    f["lab"] = [mdat.label(a, b, c) for a, b, c in zip(f["market_key"], f["line"], f["selection_key"])]
    W = f.pivot_table(index="match_id", columns="lab", values="closing_odds", aggfunc="last")
    m = load.matches().set_index("match_id")
    m = m[(m["status"] == "finished") & m["ft_home"].notna() & m["ht_home"].notna()]
    W = W.join(m[["league_id", "season", "kickoff_utc", "home_team_id", "away_team_id", "ht_home", "ht_away",
                  "ft_home", "ft_away"]], how="inner")
    # known data error: half-by-half BTTS labels swapped in Oct-Nov 2025 -> drop that market there
    hb = [c for c in W.columns if c.startswith("HT_2H_BTTS|")]
    swap = W.get("HT_2H_BTTS||NO/NO") > W.get("HT_2H_BTTS||YES/YES")
    W.loc[swap.fillna(False), hb] = np.nan
    W["period"] = W["season"].map(PER)
    W["home_fav"] = W["1X2||1"] <= W["1X2||2"]
    W["fav_odds"] = np.minimum(W["1X2||1"], W["1X2||2"])
    idx, ok = hi_data.cells(W.reset_index())
    W["_cell"], W["_ok"] = idx, ok
    return W


def outcome(W, key):
    """1/0 per match for a selection label (e.g. 'BTTS||YES', 'OU|3.5|OVER'), from the scores."""
    mk, line, sk = key.split("|")
    keys = {"CORRECT_SCORE": [c.split("|")[-1] for c in W.columns if c.startswith("CORRECT_SCORE|")],
            "HT_CORRECT_SCORE": [c.split("|")[-1] for c in W.columns if c.startswith("HT_CORRECT_SCORE|")]}
    pm = md.predicate(mk, float(line) if line else None, sk, keys.get(mk, []))
    return pd.Series(np.where(W["_ok"], pm[W["_cell"].to_numpy()], np.nan), index=W.index)


def test(W, cond, hit, odds, name=""):
    """cond: bool Series; hit: 1/0 Series; odds: odds paid Series (NaN = bet not offered)."""
    cond = cond.fillna(False).astype(bool)
    priced = odds.notna() & hit.notna()
    rows = []
    for p in ["2024/25", "2025/26", "2026/27", "all"]:
        inp = (W["period"] == p) if p != "all" else pd.Series(True, index=W.index)
        sel = cond & priced & inp
        base = priced & inp
        n = int(sel.sum())
        r = (hit[sel] * odds[sel] - 1) if n else pd.Series(dtype=float)
        rows.append({"rule": name, "period": p, "matches": n, "hits": int(hit[sel].sum()) if n else 0,
                     "hit_pct": hit[sel].mean() * 100 if n else np.nan,
                     "normal_pct": hit[base].mean() * 100 if base.any() else np.nan,
                     "breakeven_pct": (1 / odds[sel]).mean() * 100 if n else np.nan,
                     "avg_odds": odds[sel].mean() if n else np.nan,
                     "return_per_100": r.mean() * 100 if n else np.nan,
                     "z": r.sum() / np.sqrt(((r - r.mean()) ** 2).sum()) if n > 2 and r.std() > 0 else np.nan})
    return pd.DataFrame(rows)


def team_history(W):
    """Per match: each team's previous match (HT/FT result) and 1-1 draws in its last 5, prior matches only."""
    m = load.matches()
    m = m[(m["status"] == "finished") & m["ft_home"].notna() & m["ht_home"].notna()].sort_values("kickoff_utc")
    res = lambda h, a: np.where(h > a, "1", np.where(h == a, "X", "2"))
    m["htft"] = pd.Series(res(m["ht_home"], m["ht_away"]), index=m.index) + "/" + \
        pd.Series(res(m["ft_home"], m["ft_away"]), index=m.index)
    m["one_one"] = ((m["ft_home"] == 1) & (m["ft_away"] == 1)).astype(int)
    rows = []
    for side in ("home", "away"):
        rows.append(pd.DataFrame({"match_id": m["match_id"], "team": m[f"{side}_team_id"], "kick": m["kickoff_utc"],
                                  "venue": side, "htft": m["htft"], "one_one": m["one_one"]}))
    t = pd.concat(rows).sort_values(["team", "kick"]).reset_index(drop=True)
    g = t.groupby("team")
    t["prev_htft"] = g["htft"].shift(1)
    t["one_one_last5"] = g["one_one"].shift(1).groupby(t["team"]).transform(
        lambda v: v.rolling(5, min_periods=5).sum())
    h = t[t["venue"] == "home"].set_index("match_id")[["prev_htft", "one_one_last5"]].add_prefix("h_")
    a = t[t["venue"] == "away"].set_index("match_id")[["prev_htft", "one_one_last5"]].add_prefix("a_")
    return W.join(h).join(a)
