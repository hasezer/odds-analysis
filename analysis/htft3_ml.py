"""HT/FT study 3, step 3: machine learning and combined scores for the six changing results (+ three pairs).

Per result, scores that rank matches by how likely the result is, all trained only on earlier seasons:
  own price        Nesine's HT/FT chance for the result (the baseline every technique must be compared with)
  other markets    the HT/FT chance implied by the other markets (htft_poisson.py)
  logistic         logistic regression on the 25 strongest single signs of 2024/25
  boosted trees    LightGBM on all ~400 pre-match signals
  blend            average rank of the own price and the boosted-trees score
Tests: trained on 2024/25 -> 2025/26 and 2026/27; trained on 2024/25 + 2025/26 -> 2026/27.
Measured inside each test season: hit rate of the top 1 / 2 / 5 / 10 / 20% of matches by each score, AUC.
Writes cache/htft3_ml.parquet and cache/htft3_ml_importance.parquet.
"""
from pathlib import Path
import sys

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

sys.path.insert(0, str(Path(__file__).resolve().parent))
import htft3_data as h3  # noqa: E402
from htft3_signs import PAIRS, SEAS, features, pretty  # noqa: E402
from htft_data import CACHE  # noqa: E402
from six_plus import auc  # noqa: E402

TOPS = (0.01, 0.02, 0.05, 0.10, 0.20)
PARAMS = dict(objective="binary", learning_rate=0.02, num_leaves=15, min_child_samples=150, subsample=0.8,
              subsample_freq=1, colsample_bytree=0.5, reg_lambda=10.0, n_estimators=400, verbose=-1, n_jobs=2)


def tops(score, y):
    ok = ~np.isnan(score)
    s, t = score[ok], y[ok]
    order = np.argsort(-s)
    out = {}
    for k in TOPS:
        n = max(int(round(len(s) * k)), 1)
        out[f"top {int(k * 100)}% hit %"] = t[order[:n]].mean() * 100
    out["AUC"] = auc(s, t)
    return out


def rank(v):
    return pd.Series(v).rank(pct=True).to_numpy()


def run():
    d = h3.build()
    for name, ys in PAIRS.items():
        d["y_" + name] = d[ys].max(axis=1)
        a, b = (y[2:] for y in ys)
        d["p_" + name] = d[f"p_{a[0]}/{a[1]}"] + d[f"p_{b[0]}/{b[1]}"]
        d["q_" + name] = d[f"q_{a[0]}/{a[1]}"] + d[f"q_{b[0]}/{b[1]}"]
    cols = features(d)
    S = pd.read_parquet(CACHE / "htft3_signs.parquet")
    X = d[cols].astype(float)
    per = d["per"].to_numpy()
    targets = [(lab, y) for lab, y in h3.TARGETS.items()] + [(name, "y_" + name) for name in PAIRS]
    rows, imps = [], []
    for lab, ycol in targets:
        y = d[ycol].to_numpy(float)
        own = d[f"p_{lab}"].to_numpy(float)
        other = d[f"q_{lab}"].to_numpy(float)
        sig = S[(S["result"] == lab)].copy()
        sig["strength"] = (sig["AUC 2024/25"] - 0.5).abs()
        lr_cols = sig.sort_values("strength", ascending=False)["sign"].head(25).tolist()
        for train, tests in ((["A"], ["B", "C"]), (["A", "B"], ["C"])):
            tr = np.isin(per, train)
            mdl = lgb.LGBMClassifier(**PARAMS).fit(X[tr], y[tr])
            med = X[tr][lr_cols].median()
            mu, sd = X[tr][lr_cols].fillna(med).mean(), X[tr][lr_cols].fillna(med).std().replace(0, 1)
            Z = ((X[lr_cols].fillna(med) - mu) / sd).clip(-5, 5)
            lr = LogisticRegression(C=0.05, max_iter=2000).fit(Z[tr], y[tr])
            gb = mdl.predict_proba(X)[:, 1]
            lg = lr.predict_proba(Z)[:, 1]
            for te in tests:
                m = per == te
                scores = {"own price": own, "other markets": other, "logistic (25 signs)": lg,
                          "boosted trees (all signs)": gb}
                bl = np.full(len(d), np.nan)
                bl[m] = (rank(own[m]) + rank(gb[m])) / 2
                scores["blend: own price + boosted trees"] = bl
                for nm, sc in scores.items():
                    r = {"result": lab, "trained on": " + ".join(SEAS[t] for t in train), "tested on": SEAS[te],
                         "score": nm, "normal %": y[m].mean() * 100}
                    r.update(tops(sc[m], y[m]))
                    rows.append(r)
            if train == ["A", "B"]:
                imp = pd.DataFrame({"sign": cols, "gain": mdl.booster_.feature_importance("gain")})
                imp["share %"] = imp["gain"] / imp["gain"].sum() * 100
                imp["what"] = imp["sign"].map(pretty)
                imps.append(imp.sort_values("gain", ascending=False).head(20).assign(result=lab))
        print(lab, flush=True)
    R = pd.DataFrame(rows)
    I = pd.concat(imps, ignore_index=True)
    R.to_parquet(CACHE / "htft3_ml.parquet")
    I.to_parquet(CACHE / "htft3_ml_importance.parquet")
    return R, I


if __name__ == "__main__":
    R, I = run()
    pd.set_option("display.width", 250)
    print(R.round(2).to_string())
