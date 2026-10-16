"""Data for the 6+ system-coupon study: one row per finished match with the Turkey date, league, kick-off, the 6+
odds and outcome, Nesine's 6+ chance (p6), a calibrated 6+ chance, expected goals, and alternative 'many goals' legs.
Cached to cache/six_sys.parquet.
"""
from pathlib import Path
import sys

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression

sys.path.insert(0, str(Path(__file__).resolve().parent))
import load  # noqa: E402
import six_plus as sp  # noqa: E402
from htft_data import CACHE  # noqa: E402

OUT = CACHE / "six_sys.parquet"


def build(refresh=False):
    if OUT.exists() and not refresh:
        return pd.read_parquet(OUT)
    D, X, d = sp.data()
    m = load.matches().set_index("match_id").reindex(D.index)
    kick = pd.DatetimeIndex(m["kickoff_utc"]).tz_convert("Europe/Istanbul")
    e = lambda c: np.exp(X[c]) if c in X else pd.Series(np.nan, index=X.index)
    S = pd.DataFrame(index=D.index)
    S["date"] = kick.date.astype(str)
    S["kick"] = kick.tz_localize(None)
    S["league"] = D["league"].astype(str)
    S["per"] = D["per"]
    S["home"], S["away"] = m["home_team_id"].to_numpy(), m["away_team_id"].to_numpy()
    S["goals"] = D["fh"] + D["fa"]
    S["ht_goals"] = D["hh"] + D["ha"]
    S["y6"] = D["y"].astype(int)
    S["o6"] = D["odds6"]
    S["p6"] = D["p6"]
    S["lam"] = X[["model: lam_h1", "model: lam_a1", "model: lam_h2", "model: lam_a2"]].sum(1)
    # calibrated 6+ chance: Nesine's p6 overstates 6+; map it to the actual rate (isotonic, all seasons; only used to
    # measure correlation and expected hits, never to pick)
    iso = IsotonicRegression(out_of_bounds="clip").fit(S["p6"], S["y6"])
    S["p6_cal"] = iso.predict(S["p6"])
    legs = {"o35": ("odds: Goals over 3.5", S["goals"] >= 4), "o45": ("odds: Goals over 4.5", S["goals"] >= 5),
            "ht15": ("odds: 1st-half goals over 1.5", S["ht_goals"] >= 2),
            "o25": ("odds: Goals over 2.5", S["goals"] >= 3)}
    for k, (c, hit) in legs.items():
        S[f"odds_{k}"] = e(c)
        S[f"y_{k}"] = hit.astype(int)
    S["odds_other"], S["odds_ht_other"] = e("odds: Score OTHER"), e("odds: 1st-half score OTHER")
    S["odds_01"], S["odds_45r"] = e("odds: Total goals 0-1"), e("odds: Total goals 4-5")
    S["fav"] = np.exp(np.minimum(X["odds: Result home"], X["odds: Result away"]))
    S.to_parquet(OUT)
    return S


if __name__ == "__main__":
    S = build(refresh=True)
    print(S.shape, S["date"].nunique(), "days")
    per_day = S[S["o6"].notna()].groupby("date").size()
    print("days with >= 10 matches with 6+ odds:", int((per_day >= 10).sum()), "of", per_day.size)
