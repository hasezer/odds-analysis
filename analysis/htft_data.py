"""Build one row per match for the HT/FT study (cached in analysis/cache/htft_wide.parquet).

Columns
- match info: match_id, league_id, season, kickoff_utc, home/away team, ht/ft score, htft (actual outcome, e.g. "2/1")
- o_<sel>  : HT/FT closing odds for the 9 outcomes (o_1/1 … o_X/X)
- p_<sel>  : HT/FT fair probability (cut removed within the HT/FT market)
- f_<market>_<line>_<selection> : fair probability of every other complete market (the "hints")
- team-history columns (previous league match of each team inside the analysed seasons), see add_history()
"""
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import load  # noqa: E402

CACHE = Path(__file__).resolve().parent / "cache"
HTFT = ["1/1", "1/X", "1/2", "X/1", "X/X", "X/2", "2/1", "2/X", "2/2"]
DISCOVERY = {"2024/25", "2024"}

# markets used as hints (key -> lines); fair probabilities are recomputed here from closing odds
HINT_MARKETS = ["1X2", "HT_1X2", "2H_1X2", "DC", "BTTS", "HT_BTTS", "2H_BTTS", "OU", "HT_OU", "TEAM_OU_HOME",
                "TEAM_OU_AWAY", "HT_TEAM_OU_HOME", "HT_TEAM_OU_AWAY", "GOAL_RANGE", "BOTH_HALVES_OVER",
                "TEAM_WIN_EITHER_HALF_HOME", "TEAM_WIN_EITHER_HALF_AWAY", "TEAM_WIN_BOTH_HALVES_HOME",
                "TEAM_WIN_BOTH_HALVES_AWAY", "1X2_AND_OU", "1X2_AND_BTTS", "HT_1X2_AND_HT_OU", "HT_1X2_AND_HT_BTTS",
                "OU_AND_BTTS", "HT_2H_BTTS", "CORNERS_OU"]
EXPECTED_SIZE = {"1X2": 3, "HT_1X2": 3, "2H_1X2": 3, "DC": 3, "GOAL_RANGE": 4, "1X2_AND_OU": 6, "1X2_AND_BTTS": 6,
                 "HT_1X2_AND_HT_OU": 6, "HT_1X2_AND_HT_BTTS": 6, "OU_AND_BTTS": 4, "HT_2H_BTTS": 4, "HT_FT": 9}


def _fair(d: pd.DataFrame) -> pd.DataFrame:
    """Fair probability within each match x market x line, only when the market is complete."""
    key = ["match_id", "market_key", "line"]
    d = d.assign(imp=1 / d["closing_odds"])
    n = d.groupby(key, dropna=False)["imp"].transform("size")
    need = d["market_key"].map(EXPECTED_SIZE).fillna(2)
    s = d.groupby(key, dropna=False)["imp"].transform("sum")
    div = np.where(d["market_key"] == "DC", s / 2, s)
    d["fair"] = np.where(n == need, d["imp"] / div, np.nan)
    return d


def build(refresh: bool = False) -> pd.DataFrame:
    CACHE.mkdir(exist_ok=True)
    out = CACHE / "htft_wide.parquet"
    if out.exists() and not refresh:
        return pd.read_parquet(out)

    f = load.flat()
    f = f[f["in_default_analysis"] & f["closing_odds"].notna()]
    f = f[f["market_key"].isin(HINT_MARKETS + ["HT_FT"])]
    f = _fair(f[["match_id", "market_key", "line", "selection_key", "closing_odds", "hit"]])

    h = f[f["market_key"] == "HT_FT"]
    h = h[h.groupby("match_id")["fair"].transform("count") == 9]           # complete HT/FT market only
    o = h.pivot(index="match_id", columns="selection_key", values="closing_odds").add_prefix("o_")
    p = h.pivot(index="match_id", columns="selection_key", values="fair").add_prefix("p_")
    actual = h[h["hit"].astype(bool)].set_index("match_id")["selection_key"].rename("htft")

    x = f[(f["market_key"] != "HT_FT") & f["fair"].notna() & f["match_id"].isin(o.index)]
    x = x.assign(col="f_" + x["market_key"] + "_" + x["line"].map(lambda v: "" if pd.isna(v) else f"{v:g}") + "_"
                 + x["selection_key"])
    hints = x.pivot_table(index="match_id", columns="col", values="fair")

    m = load.matches().set_index("match_id")
    info = m.loc[o.index, ["league_id", "season", "season_type", "kickoff_utc", "home_team_id", "away_team_id",
                           "ht_home", "ht_away", "ft_home", "ft_away"]]
    w = info.join([actual, o, p, hints]).reset_index()
    w = w[w["htft"].notna()].copy()
    w["period"] = np.where(w["season"].isin(DISCOVERY), "discovery", "check")
    w = add_history(w, m.reset_index())
    w.to_parquet(out)
    return w


def _outcome(a, b):
    return np.where(a > b, "W", np.where(a < b, "L", "D"))


def add_history(w: pd.DataFrame, m: pd.DataFrame) -> pd.DataFrame:
    """Previous league match of each team (any venue), from the analysed seasons only."""
    m = m[(m["status"] == "finished") & m["ht_home"].notna()].copy()
    home = pd.DataFrame({"match_id": m["match_id"], "team": m["home_team_id"], "kick": m["kickoff_utc"],
                         "gf": m["ft_home"], "ga": m["ft_away"], "hgf": m["ht_home"], "hga": m["ht_away"], "venue": "H"})
    away = pd.DataFrame({"match_id": m["match_id"], "team": m["away_team_id"], "kick": m["kickoff_utc"],
                         "gf": m["ft_away"], "ga": m["ft_home"], "hgf": m["ht_away"], "hga": m["ht_home"], "venue": "A"})
    t = pd.concat([home, away]).sort_values(["team", "kick"]).reset_index(drop=True)
    t["ht_res"] = _outcome(t["hgf"], t["hga"])
    t["ft_res"] = _outcome(t["gf"], t["ga"])
    t["score"] = t["gf"].astype(int).astype(str) + "-" + t["ga"].astype(int).astype(str)   # from the team's view
    t["htft_team"] = t["ht_res"] + "/" + t["ft_res"]                                      # e.g. L/W = came back
    t["comeback_win"] = (t["ht_res"] == "L") & (t["ft_res"] == "W")
    t["blown_lead"] = (t["ht_res"] == "W") & (t["ft_res"] == "L")
    t["goals_total"] = t["gf"] + t["ga"]
    t["second_half_goals"] = t["goals_total"] - t["hgf"] - t["hga"]
    g = t.groupby("team")
    prev = ["score", "htft_team", "comeback_win", "blown_lead", "goals_total", "second_half_goals", "ft_res", "kick"]
    for c in prev:
        t[f"prev_{c}"] = g[c].shift(1)
    # rolling share of reversals over the previous 10 matches (excluding the current one)
    for c in ["comeback_win", "blown_lead"]:
        t[f"last10_{c}"] = g[c].transform(lambda s: s.astype(float).shift(1).rolling(10, min_periods=5).sum())
    t["last10_2h_goals"] = g["second_half_goals"].transform(lambda s: s.shift(1).rolling(10, min_periods=5).mean())
    t["days_rest"] = (t["kick"] - t["prev_kick"]).dt.total_seconds() / 86400
    keep = [c for c in t.columns if c.startswith(("prev_", "last10_"))] + ["days_rest"]
    keep.remove("prev_kick")
    hh = t[t["venue"] == "H"].set_index("match_id")[keep].add_prefix("home_")
    aa = t[t["venue"] == "A"].set_index("match_id")[keep].add_prefix("away_")
    return w.join(hh, on="match_id").join(aa, on="match_id")


if __name__ == "__main__":
    w = build(refresh=True)
    print(w.shape)
    print(w["htft"].value_counts())
