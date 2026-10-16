"""HT/FT deep dive 2: one row per match, seen from the FAVOURITE's side (F = favourite, U = underdog), so that
'home favourite' and 'away favourite' matches can be pooled. Cached in cache/htft2.parquet.

Columns
- match info, season period (A = 2024/25 + 2024, B = 2025/26 + 2025, C = 2026/27 + 2026 so far), fav_home (bool)
- fav_p / draw_p / dog_p: Nesine's 1X2 chances (cut removed); over25_p: chance of over 2.5 goals
- ht_d / ft_d: goal difference from the favourite's side at half-time / full-time; ht_goals, sh_goals (2nd half)
- htft_f: actual HT/FT outcome from the favourite's side, e.g. 'X/F' = level at half-time, favourite wins
- o_<F-outcome> / p_<F-outcome>: HT/FT closing odds and cut-removed chance of each of the 9 outcomes, favourite side
- lam_1h / lam_2h: goals Nesine's prices expect in each half (goal model fitted to its core markets)
"""
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import htft_data as hd  # noqa: E402
import six_plus as sp  # noqa: E402
from htft_data import CACHE  # noqa: E402

OUT = CACHE / "htft2.parquet"
PER = {"2024/25": "A", "2024": "A", "2025/26": "B", "2025": "B", "2026/27": "C", "2026": "C"}
FOUT = ["F/F", "F/X", "F/U", "X/F", "X/X", "X/U", "U/F", "U/X", "U/U"]


def to_label(fo, fav_home):
    """Favourite-side outcome ('X/F') -> Nesine label ('X/1' when the favourite is at home)."""
    m = {"F": "1" if fav_home else "2", "U": "2" if fav_home else "1", "X": "X"}
    return "/".join(m[c] for c in fo.split("/"))


def res(d):
    return np.where(d > 0, "F", np.where(d < 0, "U", "X"))


def build(refresh=False):
    if OUT.exists() and not refresh:
        return pd.read_parquet(OUT)
    w = hd.build(refresh=refresh)
    w = w[~w["match_id"].str.startswith("macko")].copy()
    d = pd.DataFrame({"match_id": w["match_id"], "league": w["league_id"], "season": w["season"],
                      "per": w["season"].map(PER), "kickoff": w["kickoff_utc"],
                      "home": w["home_team_id"], "away": w["away_team_id"]})
    fh = w["f_1X2__1"] >= w["f_1X2__2"]
    d["fav_home"] = fh.to_numpy()
    d["fav_p"] = np.where(fh, w["f_1X2__1"], w["f_1X2__2"])
    d["dog_p"] = np.where(fh, w["f_1X2__2"], w["f_1X2__1"])
    d["draw_p"] = w["f_1X2__X"].to_numpy()
    d["over25_p"] = w["f_OU_2.5_OVER"].to_numpy()
    sgn = np.where(fh, 1, -1)
    d["ht_d"] = sgn * (w["ht_home"] - w["ht_away"]).to_numpy()
    d["ft_d"] = sgn * (w["ft_home"] - w["ft_away"]).to_numpy()
    d["ht_goals"] = (w["ht_home"] + w["ht_away"]).to_numpy()
    d["sh_goals"] = (w["ft_home"] + w["ft_away"] - w["ht_home"] - w["ht_away"]).to_numpy()
    d["ht_fav"], d["ht_dog"] = np.where(fh, w["ht_home"], w["ht_away"]), np.where(fh, w["ht_away"], w["ht_home"])
    d["htft_f"] = pd.Series(res(d["ht_d"]), index=d.index) + "/" + pd.Series(res(d["ft_d"]), index=d.index)
    for fo in FOUT:
        lab_h, lab_a = to_label(fo, True), to_label(fo, False)
        d[f"o_{fo}"] = np.where(fh, w[f"o_{lab_h}"], w[f"o_{lab_a}"])
        d[f"p_{fo}"] = np.where(fh, w[f"p_{lab_h}"], w[f"p_{lab_a}"])
    for k in ("HT_1X2", "2H_1X2"):          # half results from the favourite's side (chances, cut removed)
        d[f"{k}_F"] = np.where(fh, w[f"f_{k}__1"], w[f"f_{k}__2"])
        d[f"{k}_X"] = w[f"f_{k}__X"].to_numpy()
        d[f"{k}_U"] = np.where(fh, w[f"f_{k}__2"], w[f"f_{k}__1"])
    D, X, _ = sp.data()
    lam = X[["model: lam_h1", "model: lam_a1", "model: lam_h2", "model: lam_a2"]].reindex(d["match_id"])
    d["lam_1h"] = (lam["model: lam_h1"] + lam["model: lam_a1"]).to_numpy()
    d["lam_2h"] = (lam["model: lam_h2"] + lam["model: lam_a2"]).to_numpy()
    d = d[d["per"].notna() & d["o_F/F"].notna()].reset_index(drop=True)
    d.to_parquet(OUT)
    return d


if __name__ == "__main__":
    d = build(refresh=True)
    print(d.shape, d["per"].value_counts().to_dict())
    print(d["htft_f"].value_counts(normalize=True).round(3).to_dict())
