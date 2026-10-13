"""Walk-forward machine learning on every market.

For each market a gradient-boosting model predicts whether a selection wins, from
- the market's own fair price, odds and cut,
- the goal-rate model price q (built from the core markets) and the four goal rates,
- pre-match team form (goals, shots, shots on target, corners, possession, results against the market's expectation),
- context (league, rest days, stage of season, kick-off hour, weekday).

Walk-forward: from 2025-01-01 on, every 3 months the model is retrained on ALL earlier matches and predicts the next
3 months. Only these out-of-sample predictions are evaluated. Writes analysis/cache/ml_oos.parquet.
"""
from pathlib import Path
import sys
import warnings

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ml_data as md  # noqa: E402
from htft_data import CACHE  # noqa: E402

warnings.filterwarnings("ignore")
START = pd.Timestamp("2025-01-01", tz="UTC")
STEP = pd.DateOffset(months=3)


def logit(p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def features(mt: pd.DataFrame, sel: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    form = [c for c in mt.columns if c.startswith(("h_r", "a_r", "h_n_prev", "a_n_prev"))]     # includes h_rest/a_rest
    ctx = ["lam_h1", "lam_a1", "lam_h2", "lam_a2", "fit_rmse", "corners_exp", "phase", "hour_utc", "weekday"]
    d = sel.merge(mt[["match_id", "kickoff_utc", "league_id", "period"] + ctx + form], on="match_id", how="inner")
    d["lf"] = logit(d["fair"].fillna(d["implied"]))
    d["lq"] = logit(d["q"])
    d["lq_minus_lf"] = d["lq"] - d["lf"]
    d["log_odds"] = np.log(d["closing_odds"])
    d["sel_code"] = d["selection_key"].astype("category").cat.codes
    d["league_code"] = d["league_id"].astype("category").cat.codes
    d["line_f"] = d["line"].fillna(-1)
    # differences that make form features symmetric for the model
    for c in ("r6_gf", "r6_ga", "r6_sot", "r6_sota", "r6_cor", "r6_res_gf", "r15_res_gf", "r15_sot_share"):
        d[f"diff_{c}"] = d[f"h_{c}"] - d[f"a_{c}"]
    cols = (["lf", "lq", "lq_minus_lf", "log_odds", "overround", "sel_code", "line_f", "league_code"] + ctx + form
            + [c for c in d.columns if c.startswith("diff_")])
    return d, cols


def run(markets=None):
    mt, sel = md.build()
    part_dir = CACHE / "oos"
    part_dir.mkdir(exist_ok=True)
    for mk in markets or sorted(sel["market_key"].unique()):
        if (part_dir / f"{mk}.parquet").exists():
            continue
        d, cols = features(mt, sel[sel["market_key"] == mk])
        cols = [c for c in cols if d[c].notna().any()]            # e.g. no goal-model price for corners
        cat = [cols.index("sel_code"), cols.index("league_code")]
        blocks = []
        t0 = START
        while t0 < d["kickoff_utc"].max():
            t1 = t0 + STEP
            tr = d[d["kickoff_utc"] < t0]
            te = d[(d["kickoff_utc"] >= t0) & (d["kickoff_utc"] < t1)]
            t0 = t1
            if len(te) == 0 or len(tr) < 3000:
                continue
            y = tr["hit"].to_numpy()
            gb = HistGradientBoostingClassifier(max_iter=400, learning_rate=.03, max_leaf_nodes=15, min_samples_leaf=200,
                                                l2_regularization=5.0, early_stopping=True, validation_fraction=.15,
                                                n_iter_no_change=30, categorical_features=cat, random_state=0)
            gb.fit(tr[cols].to_numpy(dtype=np.float32), y)
            base = ["lf", "lq"] if tr["lq"].notna().mean() > .99 else ["lf"]
            lr = LogisticRegression(max_iter=2000).fit(tr[base].fillna(0).to_numpy(), y)
            blk = te[["match_id", "market_key", "line", "selection_key", "closing_odds", "fair", "implied", "q", "hit",
                      "kickoff_utc", "league_id", "period"]].copy()
            blk["p_gbm"] = gb.predict_proba(te[cols].to_numpy(dtype=np.float32))[:, 1]
            blk["p_lr"] = lr.predict_proba(te[base].fillna(0).to_numpy())[:, 1]
            blocks.append(blk)
        if blocks:
            r = pd.concat(blocks)
            r.to_parquet(part_dir / f"{mk}.parquet")
            print(f"{mk:28s} oos rows {len(r):>8,}", flush=True)
    res = pd.concat([pd.read_parquet(f) for f in sorted(part_dir.glob("*.parquet"))])
    res.to_parquet(CACHE / "ml_oos.parquet")
    return res


if __name__ == "__main__":
    run(sys.argv[1:] or None)
