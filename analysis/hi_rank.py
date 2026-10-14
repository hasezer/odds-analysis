"""How high can the hit rate of a high-odds bet go if you only bet the most promising matches?

For every high-odds target (hi_data.py), matches are ranked by four scores and only the top 1/2/5/10/20% are bet:
  price   Nesine's own chance for that bet (cut removed); for combined bets the goal model below
  model   the goal model: four goal rates fitted to Nesine's core prices -> chance of the bet
  ml      gradient-boosted trees (LightGBM) on ~400 pre-match features (all odds, disagreement, form, last match, context)
  rules   number of v3 rules for the bet that are true (rules picked on A + B only; C only)
Walk-forward, never testing on what was trained on: train A -> test B, train A + B -> test C.
Also "packs": per match, bet the k most likely correct scores (or HT scores / HT-FT results) together.
Writes cache/hi_rank.parquet, cache/hi_packs.parquet, cache/hi_scores_C.npz.
"""
from pathlib import Path
import sys
import time

import numpy as np
import pandas as pd
from scipy.stats import poisson
from lightgbm import LGBMClassifier

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hi_data  # noqa: E402
import ml_data as md  # noqa: E402
from htft_data import CACHE  # noqa: E402

COVER = [.01, .02, .05, .10, .20]
FOLDS = [("B", ("A",)), ("C", ("A", "B"))]


def goal_model_probs(d):
    """Chance of every target under the goal model (four Poisson goal rates fitted to Nesine's core prices)."""
    fn = list(d["fnames"])
    lam = np.stack([d["X"][:, fn.index(f"model: {c}")] for c in ("lam_h1", "lam_a1", "lam_h2", "lam_a2")], 1)
    names = list(d["names"])
    keys = {}
    for n in names:
        mk, _, sk = n.split("|")
        keys.setdefault(mk, []).append(sk)
    G = md
    extra = {
        "HT/FT comeback (1/2 or 2/1)": ((G.HT == "1") & (G.FT == "2")) | ((G.HT == "2") & (G.FT == "1")),
        "Draw with 4+ goals (2-2, 3-3 ...)": (G.FT == "X") & (G.T >= 4),
        "Total goals 6+ (any)": G.T >= 6,
        "Both teams score in both halves": (G.H1 > 0) & (G.A1 > 0) & (G.H2 > 0) & (G.A2 > 0),
        "Winner by 3+ goals": np.abs(G.HH - G.AA) >= 3,
        "Half-time draw, full-time not (X/1 or X/2)": (G.HT == "X") & (G.FT != "X"),
        "Home team scores 3+": G.HH >= 3,
        "Away team scores 3+": G.AA >= 3,
        "5+ goals and both score": (G.T >= 5) & (G.HH > 0) & (G.AA > 0),
        "2nd half has 3+ goals": G.T2 >= 3,
    }
    masks = []
    for k in d["tkeys"]:
        if k in extra:
            masks.append(extra[k])
        else:
            mk, line, sk = k.split("|")
            masks.append(md.predicate(mk, float(line) if line else None, sk, keys[mk]))
    M = np.stack(masks, 1).astype(np.float32)
    out = np.full((len(lam), M.shape[1]), np.nan, np.float32)
    okl = ~np.isnan(lam).any(1)
    ix_all = np.where(okl)[0]
    g = np.arange(md.G)
    for ix in np.array_split(ix_all, max(1, len(ix_all) // 1500)):
        pm = [poisson.pmf(g[None, :], lam[ix, j][:, None]).astype(np.float32) for j in range(4)]
        joint = (pm[0][:, :, None, None, None] * pm[1][:, None, :, None, None] * pm[2][:, None, None, :, None]
                 * pm[3][:, None, None, None, :]).reshape(len(ix), -1)
        out[ix] = joint @ M
    return out


def top_hits(score, y, odds, cover):
    """Hit rate among the top `cover` share of matches by score (matches without a score go last)."""
    ok = ~np.isnan(y)
    s, yy, oo = np.where(np.isnan(score[ok]), -np.inf, score[ok]), y[ok], odds[ok]
    order = np.argsort(-s, kind="stable")
    res = []
    for c in cover:
        k = max(1, int(round(c * len(yy))))
        pick = order[:k]
        o = oo[pick]
        res.append((c, k, yy[pick].sum(), np.nanmean(o) if (~np.isnan(o)).any() else np.nan,
                    np.nanmean(np.where(np.isnan(o), np.nan, yy[pick] * o - 1)) if (~np.isnan(o)).any() else np.nan))
    return res


def rule_counts(d, Cmask):
    """C matches: number of v3 hit-track rules (picked on A + B) that are true, per target (by target key)."""
    f = CACHE / "rules_v3_ab.parquet"
    if not f.exists():
        return {}
    import rules_v3_data as v3
    r = pd.read_parquet(f, columns=["target_key", "atoms", "ab_hit"])
    r = r[r["ab_hit"]]
    a = v3.build()
    XC = a["X"][Cmask]
    out = {}
    for tk, g in r.groupby("target_key"):
        if tk not in set(d["tkeys"]):
            continue
        cnt = np.zeros(XC.shape[0], np.float32)
        for at in g["atoms"]:
            cnt += XC[:, [int(x) for x in at.split(",")]].all(1)
        out[tk] = cnt
    return out


def packs(d, S, per_mask, label):
    """Per match, bet the k most likely selections of one market together (one stake split to win the same)."""
    names = list(d["names"])
    rows = []
    groups = {"Correct score": [k for k in d["tkeys"] if k.startswith("CORRECT_SCORE|")],
              "1st-half score": [k for k in d["tkeys"] if k.startswith("HT_CORRECT_SCORE|")],
              "HT/FT (high-odds results only)": [k for k in d["tkeys"] if k.startswith("HT_FT|")]}
    tk = list(d["tkeys"])
    Y, O = d["Y"][per_mask], d["O"][per_mask]
    for gname, ks in groups.items():
        ti = [tk.index(k) for k in ks]
        oi = [names.index(k) for k in ks]
        for meth, sc in S.items():
            s = sc[:, ti]
            if np.isnan(s).all():
                continue
            y, o = Y[:, ti], O[:, oi]
            ok = ~np.isnan(y).any(1) & ~np.isnan(s).all(1)
            order = np.argsort(-np.nan_to_num(s, nan=-1), axis=1)
            for k in (1, 2, 3, 4):
                pick = order[:, :k]
                hit = np.take_along_axis(y, pick, 1).max(1)
                oo = np.take_along_axis(o, pick, 1)
                eff = 1 / (1 / oo).sum(1)                      # one stake split so every pick pays the same
                okp = ok & ~np.isnan(eff)
                rows.append({"period": label, "pack": gname, "method": meth, "k": k, "matches": int(ok.sum()),
                             "hit": np.nanmean(hit[ok]) * 100, "priced": int(okp.sum()),
                             "hit_priced": np.nanmean(hit[okp]) * 100 if okp.sum() else np.nan,
                             "effective_odds": np.nanmedian(eff[okp]) if okp.sum() else np.nan,
                             "return_per_100": np.nanmean(hit[okp] * eff[okp] - 1) * 100 if okp.sum() else np.nan})
    return rows


def run():
    d = hi_data.build()
    X, Y, per = d["X"], d["Y"], d["per"]
    names, tkeys, tprice = list(d["names"]), list(d["tkeys"]), d["tprice"]
    Fq = goal_model_probs(d)
    rows, scores_C = [], {}
    S_by_fold = {}
    for test, train in FOLDS:
        tr, te = np.isin(per, train), per == test
        fcols = np.where(((~np.isnan(X[tr])).sum(0) >= 200) & (d["ffam"] != "fair"))[0]   # fair = odds, rescaled
        S = {"price": np.full((te.sum(), Y.shape[1]), np.nan, np.float32),
             "model": Fq[te], "ml": np.full((te.sum(), Y.shape[1]), np.nan, np.float32)}
        rc = rule_counts(d, te) if test == "C" else {}
        if rc:
            S["rules"] = np.full((te.sum(), Y.shape[1]), np.nan, np.float32)
        for j, (tn, tk, ti) in enumerate(zip(d["tnames"], tkeys, tprice)):
            t0 = time.time()
            y = Y[:, j]
            if ti >= 0:
                own = d["F"][:, ti]
                S["price"][:, j] = np.where(np.isnan(own[te]), Fq[te, j], own[te])
                odds = d["O"][te, ti]
            else:
                S["price"][:, j] = Fq[te, j]
                odds = np.full(te.sum(), np.nan, np.float32)
            okt = tr & ~np.isnan(y)
            clf = LGBMClassifier(n_estimators=250, learning_rate=.03, num_leaves=15, min_child_samples=100,
                                 subsample=.8, subsample_freq=1, colsample_bytree=.5, reg_lambda=1.0, max_bin=63,
                                 n_jobs=4, verbose=-1, random_state=0)
            clf.fit(X[okt][:, fcols], y[okt].astype(int))
            S["ml"][:, j] = clf.predict_proba(X[te][:, fcols])[:, 1]
            if tk in rc:
                S["rules"][:, j] = rc[tk] + 1e-3 * Fq[te, j]      # ties broken by the goal model
            yt = y[te]
            base = np.nanmean(yt)
            for meth, sc in S.items():
                if meth == "rules" and tk not in rc:
                    continue
                for c, k, h, ao, ret in top_hits(sc[:, j], yt, odds, COVER):
                    rows.append({"target": tn, "target_key": tk, "test": test, "method": meth, "cover": c,
                                 "bets": k, "hits": h, "hit": h / k * 100, "normal": base * 100,
                                 "avg_odds": ao, "return_per_100": ret * 100 if ret == ret else np.nan})
            print(f"{test} {tn[:42]:42s} normal {base * 100:5.1f}%  top5%: " + "  ".join(
                f"{m} {r['hit']:.1f}" for m in S for r in rows[-len(COVER) * len(S):]
                if r["method"] == m and r["cover"] == .05 and r["target_key"] == tk) +
                f"  ({time.time() - t0:.0f}s)", flush=True)
        S_by_fold[test] = S
    r = pd.DataFrame(rows)
    r.to_parquet(CACHE / "hi_rank.parquet")
    pk = []
    for test, _ in FOLDS:
        pk += packs(d, S_by_fold[test], per == test, test)
    pd.DataFrame(pk).to_parquet(CACHE / "hi_packs.parquet")
    np.savez_compressed(CACHE / "hi_scores_C.npz", **{k: v for k, v in S_by_fold["C"].items()})
    return r


if __name__ == "__main__":
    run()
