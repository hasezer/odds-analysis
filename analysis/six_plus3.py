"""6+ goals deep dive, studies 6-7.

6 structure signals built from Nesine's own markets (each compares how a 6+ game could happen with the 6+ price):
  shootout = P(home 3+) x P(away 3+) / p6       tail = P(5+) / p6          other = P('other' score) / p6
  early = P(1st-half 2+) / P(4+)                 hidraw = P(draw & 3+ goals) / p6
  bothhalves = P(both halves 2+) / p6            balance = |log(P(home 3+) / P(away 3+))|
  ht_other = P(1st-half score 'other' = 3+ goals in 1st half) / p6            range45 = P(4-5 goals) / p6
  btts = P(both score) / P(3+ goals)
  -> separation of 6+ games among matches with the same p6 (stratified AUC), per season
7 small combined model: logistic regression of 6+ on logit(p6) + the signals that pointed the same way in 2024/25
  AND 2025/26 (chosen without 2026/27), fitted on 2024/25 + 2025/26, tested on 2026/27: hit rate of its top 2/5/10%
  vs the top by p6 alone; also returns of 6+ and over 3.5 on those picks.
Writes cache/six_plus_structure.parquet and cache/six_plus_combined.parquet.
"""
from pathlib import Path
import sys

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

sys.path.insert(0, str(Path(__file__).resolve().parent))
import six_plus as sp  # noqa: E402
from htft_data import CACHE  # noqa: E402

SEAS = sp.SEAS


def structure(D, X):
    c = lambda n: X[f"chance: {n}"] if f"chance: {n}" in X else pd.Series(np.nan, index=X.index)
    p6 = D["p6"]
    S = pd.DataFrame(index=D.index)
    S["shootout"] = c("Home goals over 2.5") * c("Away goals over 2.5") / p6
    S["tail"] = c("Goals over 4.5") / p6
    S["other"] = c("Score OTHER") / p6
    S["early"] = c("1st-half goals over 1.5") / c("Goals over 3.5")
    S["hidraw"] = c("Result & goals X & over 2.5") / p6
    S["bothhalves"] = c("Both halves over yes 1.5") / p6
    S["balance"] = np.abs(np.log(c("Home goals over 2.5") / c("Away goals over 2.5")))
    S["ht_other"] = c("1st-half score OTHER") / p6
    S["range45"] = c("Total goals 4-5") / p6
    S["btts"] = c("Both teams score yes") / c("Goals over 2.5")
    for k in ("form: h_r6_gf", "form: a_r6_gf", "form: h_rest", "disagree: Double chance 12",
              "disagree: 1st-half result & both score 1 & yes", "form: h_r6_res_gf"):
        S[k] = X[k]
    return S


def run():
    D, X, _ = sp.data()
    S = structure(D, X)
    rows = []
    for col in S.columns:
        v = S[col].to_numpy(float)
        row = {"signal": col, "coverage": 1 - np.isnan(v).mean(), "AUC all": sp.auc(v, D["y"].to_numpy())}
        for p, nm in SEAS.items():
            m = (D["per"] == p).to_numpy()
            row[f"beyond price {nm}"] = sp.strat_auc(v[m], D["y"].to_numpy()[m], D["p6"].to_numpy()[m])
        rows.append(row)
    st = pd.DataFrame(rows)
    st.to_parquet(CACHE / "six_plus_structure.parquet")
    # combined model: choose signals on A (direction) confirmed on B; never look at C
    chosen = [r.signal for r in st.itertuples()
              if r.coverage > .7 and ((getattr(r, "_4") > .51 and getattr(r, "_5") > .51) or
                                      (getattr(r, "_4") < .49 and getattr(r, "_5") < .49))]
    lp = np.log(D["p6"] / (1 - D["p6"]))
    Z = pd.concat([lp.rename("logit_p6"), S[chosen]], axis=1)
    Z = Z.fillna(Z[D["per"].isin(["A", "B"])].median())
    mu, sd = Z[D["per"].isin(["A", "B"])].mean(), Z[D["per"].isin(["A", "B"])].std()
    Zs = (Z - mu) / sd
    tr, te = D["per"].isin(["A", "B"]), D["per"] == "C"
    lr = LogisticRegression(C=0.5, max_iter=2000).fit(Zs[tr], D.loc[tr, "y"].astype(int))
    base = LogisticRegression(C=0.5, max_iter=2000).fit(Zs[tr][["logit_p6"]], D.loc[tr, "y"].astype(int))
    pc, pb = lr.predict_proba(Zs[te])[:, 1], base.predict_proba(Zs[te][["logit_p6"]])[:, 1]
    y = D.loc[te, "y"].to_numpy()
    ll = lambda p: -np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))
    res = []
    for share in (.02, .05, .10, .20):
        k = int(round(share * te.sum()))
        for nm, p in (("6+ price only", pb), ("price + structure signals", pc)):
            top = np.argsort(-p)[:k]
            res.append({"top share": share, "method": nm, "bets": k, "6+ hit %": y[top].mean() * 100})
    out = pd.DataFrame(res)
    coefs = pd.Series(lr.coef_[0], index=Zs.columns).round(3)
    return st, chosen, out, coefs, ll(pb), ll(pc)


if __name__ == "__main__":
    st, chosen, out, coefs, llb, llc = run()
    pd.set_option("display.width", 220)
    print(st.round(3).to_string())
    print("chosen (same direction in 2024/25 and 2025/26):", chosen)
    print("coefficients:", coefs.to_dict())
    print(f"2026/27 log-loss: price only {llb:.5f}  price + signals {llc:.5f}  (lower = better)")
    print(out.pivot_table(index="top share", columns="method", values="6+ hit %").round(1).to_string())
