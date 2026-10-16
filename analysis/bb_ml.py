"""BTTS in both halves, step 2: combined scores (machine learning) against the simple chances.

Scores that rank matches by how likely BTTS in both halves is, trained only on earlier seasons:
  model q_bb        chance from the goal markets (four goal rates, independent halves): no training
  own price p_bb    Nesine's own both-halves chance (2025/26 on; scored only where it exists)
  logistic          logistic regression on the 25 strongest single signs of 2024/25
  boosted trees     LightGBM on all ~440 pre-match signs
  blends            average rank of q_bb and the boosted trees; of q_bb and the own price
Tests: trained on 2024/25 -> 2025/26 and 2026/27; trained on 2024/25 + 2025/26 -> 2026/27; and, for scores that
need the own price, trained on 2025/26 -> 2026/27. Measured inside each test season: hit rate of the top 1 / 2 / 5
/ 10 / 20% of matches, AUC. Writes cache/bb_ml.parquet, cache/bb_ml_importance.parquet and the out-of-sample scores
(cache/bb_ml_scores.parquet) for the fair race in bb_report.py.
"""
from pathlib import Path
import sys

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bb_data  # noqa: E402
from bb_signs import SEAS, features, pretty  # noqa: E402
from six_plus import auc  # noqa: E402

TOPS = (0.01, 0.02, 0.05, 0.10, 0.20)
PARAMS = dict(objective="binary", learning_rate=0.02, num_leaves=15, min_child_samples=150, subsample=0.8,
              subsample_freq=1, colsample_bytree=0.5, reg_lambda=10.0, n_estimators=400, verbose=-1, n_jobs=4)


def tops(score, y):
    ok = ~np.isnan(score)
    s, t = score[ok], y[ok]
    order = np.argsort(-s, kind="stable")
    out = {"matches": int(ok.sum()), "normal %": t.mean() * 100}
    for k in TOPS:
        n = max(int(round(len(s) * k)), 1)
        out[f"top {int(k * 100)}% hit %"] = t[order[:n]].mean() * 100
    out["AUC"] = auc(s, t)
    return out


def rank(v):
    return pd.Series(v).rank(pct=True).to_numpy()


def logistic(X, y, tr, cols):
    med = X.loc[tr, cols].median()
    Z = X[cols].fillna(med)
    mu, sd = Z[tr].mean(), Z[tr].std().replace(0, 1)
    Z = ((Z - mu) / sd).clip(-5, 5)
    lr = LogisticRegression(C=0.05, max_iter=3000).fit(Z[tr], y[tr])
    return lr.predict_proba(Z)[:, 1]


def run():
    d = bb_data.build()
    cols = features(d)
    S = pd.read_parquet(bb_data.CACHE / "bb_signs.parquet")
    S = S[S["target"] == "BTTS both halves"]
    X = d[cols].astype(float)
    y = d["y_bb"].to_numpy(float)
    per = d["per"].to_numpy()
    q = d["q_bb"].to_numpy(float)
    own = d["p_bb"].to_numpy(float)
    a_signs = S[S["found on"] == "2024/25"].copy()
    a_signs["strength"] = (a_signs["AUC 2024/25"] - 0.5).abs()
    lr_cols = a_signs.sort_values("strength", ascending=False)["sign"].head(25).tolist()
    rows, imps, keep = [], [], {}
    for train, tests in ((["A"], ["B", "C"]), (["A", "B"], ["C"]), (["B"], ["C"])):
        tr = np.isin(per, train)
        tag = " + ".join(SEAS[t] for t in train)
        mdl = lgb.LGBMClassifier(**PARAMS).fit(X[tr], y[tr])
        gb = mdl.predict_proba(X)[:, 1]
        lg = logistic(X, y, tr, lr_cols)
        extra = {}
        if train == ["B"]:                              # the own price exists from 2025/26: let a model use it
            b_cols = lr_cols + ["p_bb", "s_half_markets", "f_2H_BTTS__YES"]
            ok_b = tr & ~np.isnan(own)
            extra["logistic + own price (25 signs + own + half markets)"] = logistic(X, y, ok_b, b_cols)
        for te in tests:
            m = per == te
            scores = {"model q_bb": q, "own price": own, "logistic (25 signs)": lg, "boosted trees (all signs)": gb,
                      **extra}
            bl = np.full(len(d), np.nan)
            bl[m] = (rank(q[m]) + rank(gb[m])) / 2
            scores["blend: model + boosted trees"] = bl
            bo = np.full(len(d), np.nan)
            mo = m & ~np.isnan(own)
            bo[mo] = (rank(q[mo]) + rank(own[mo])) / 2
            scores["blend: model + own price"] = bo
            for nm, sc in scores.items():
                for arena, mm in (("all matches", m), ("matches with the own price", m & ~np.isnan(own))):
                    if nm in ("own price", "blend: model + own price") and arena == "all matches":
                        continue
                    if not np.isfinite(sc[mm]).any():
                        continue
                    r = {"trained on": tag, "tested on": SEAS[te], "arena": arena, "score": nm}
                    r.update(tops(sc[mm], y[mm]))
                    rows.append(r)
            keep[(tag, te)] = {"logistic (25 signs)": lg[m], "boosted trees (all signs)": gb[m], **{
                k: v[m] for k, v in extra.items()}, "match_id": d.loc[m, "match_id"].to_numpy()}
        imp = pd.DataFrame({"sign": cols, "gain": mdl.booster_.feature_importance("gain")})
        imp["share %"] = imp["gain"] / imp["gain"].sum() * 100
        imp["what"] = imp["sign"].map(pretty)
        imps.append(imp.sort_values("gain", ascending=False).head(25).assign(**{"trained on": tag}))
        print(tag, flush=True)
    R = pd.DataFrame(rows)
    I = pd.concat(imps, ignore_index=True)
    sc = []
    for (tag, te), v in keep.items():
        x = pd.DataFrame(v)
        x["trained on"], x["tested on"] = tag, SEAS[te]
        sc.append(x)
    R.to_parquet(bb_data.CACHE / "bb_ml.parquet")
    I.to_parquet(bb_data.CACHE / "bb_ml_importance.parquet")
    pd.concat(sc, ignore_index=True).to_parquet(bb_data.CACHE / "bb_ml_scores.parquet")
    return R, I


if __name__ == "__main__":
    R, I = run()
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 200)
    print(R.round(2).to_string(index=False))
    print(I[I["trained on"] == "2024/25"][["what", "share %"]].head(15).round(1).to_string(index=False))
