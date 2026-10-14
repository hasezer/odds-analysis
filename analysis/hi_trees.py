"""Readable high-odds rules from shallow decision trees: up to 3 conditions with exact cut-offs.

For every high-odds target: 60 depth-3 and 30 depth-2 trees, each on a random half of the readable features,
trained on period A (2024/25 + 2024) only. Every leaf is a candidate rule ("odds of X <= 3.40 AND ...").
  find     A: matches >= 150, hit >= 1.5 x normal
  confirm  B: matches >= 100, hit >= 1.3 x normal, z >= 2
  exam     C: reported (never used to choose)
Luck control: the same pipeline with the B results shuffled (how many leaves pass the confirm gate by chance).
"Beyond the odds" check: expected hits of the rule's B and C matches from the bet's own price (Nesine's chance,
or the goal model for combined bets), calibrated on A + B with a 2-parameter logistic fit; and the hit rate of a
plain odds filter of the same size (the k matches where the bet is cheapest).
Writes cache/hi_trees.parquet and cache/hi_trees_luck.parquet.
"""
from pathlib import Path
import sys
import time

import numpy as np
import pandas as pd
from sklearn.tree import DecisionTreeClassifier

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hi_data  # noqa: E402
import hi_rank  # noqa: E402
from htft_data import CACHE  # noqa: E402
from sklearn.linear_model import LogisticRegression  # noqa: E402

READABLE = {"odds", "fair", "disagree", "model", "form", "last", "margin"}
CTX_OK = {"context: season stage", "context: kick-off hour", "context: month"}
NICE = {"lam_h1": "expected home goals, 1st half", "lam_a1": "expected away goals, 1st half",
        "lam_h2": "expected home goals, 2nd half", "lam_a2": "expected away goals, 2nd half",
        "fit_rmse": "misfit of Nesine's core prices to one goal model", "corners_exp": "expected corners"}


def cond_text(name, thr, le):
    fam, what = name.split(": ", 1)
    op = "≤" if le else ">"
    if fam == "odds":
        return f"{what} odds {op} {np.exp(thr):.2f}"
    if fam == "fair":
        return f"Nesine's chance for {what} {op} {thr * 100:.1f}%"
    if fam == "disagree":
        return f"{what}: Nesine's chance ÷ other markets' chance {op} {thr:.3f}"
    if fam == "model":
        return f"{NICE.get(what, what)} {op} {thr:.2f}"
    if fam == "margin":
        return f"Nesine's cut on {what.rstrip('|')} {op} {thr * 100:.1f}%"
    if fam == "form":
        side = "Home team" if what.startswith("h_") else "Away team"
        return f"{side} {what[2:]} {op} {thr:.2f}"
    if fam == "last":
        return f"{what} {op} {thr:.1f}"
    return f"{what} {op} {thr:.2f}"


def leaves(tree, fnames):
    """leaf id -> list of (feature name, threshold, is_left) along its path."""
    t = tree.tree_
    out = {}

    def walk(node, path):
        if t.children_left[node] == -1:
            out[node] = path
            return
        f, th = fnames[t.feature[node]], t.threshold[node]
        walk(t.children_left[node], path + [(f, th, True)])
        walk(t.children_right[node], path + [(f, th, False)])
    walk(0, [])
    return out


def run(n3=60, n2=30):
    d = hi_data.build()
    X, Y, per = d["X"], d["Y"], d["per"]
    keep = np.array([f in READABLE or n in CTX_OK for f, n in zip(d["ffam"], d["fnames"])])
    Xr, fn = X[:, keep], list(np.array(d["fnames"])[keep])
    A, B, C = (per == p for p in "ABC")
    rng = np.random.default_rng(0)
    rows, luck = [], []
    Fq = hi_rank.goal_model_probs(d)
    for j, (tn, tk, ti) in enumerate(zip(d["tnames"], d["tkeys"], d["tprice"])):
        t0 = time.time()
        y = Y[:, j]
        okA, okB, okC = (m & ~np.isnan(y) for m in (A, B, C))
        ps = np.where(np.isnan(d["F"][:, ti]), Fq[:, j], d["F"][:, ti]) if ti >= 0 else Fq[:, j].copy()
        ps = np.where(np.isnan(ps), np.nanmean(y), ps)
        lg = np.log(np.clip(ps, 1e-4, 1 - 1e-4) / (1 - np.clip(ps, 1e-4, 1 - 1e-4)))[:, None]
        cal = LogisticRegression(C=1e6).fit(lg[okA | okB], y[okA | okB].astype(int))
        pcal = cal.predict_proba(lg)[:, 1]                               # the odds' chance, calibrated
        yC_by_price = y[okC][np.argsort(-ps[okC], kind="stable")]       # C matches, cheapest bet first
        cumC = np.concatenate([[0], np.cumsum(yC_by_price)])
        bA, bB, bC = (np.nanmean(y[m]) for m in (okA, okB, okC))
        yB_sh = y[okB].copy(); rng.shuffle(yB_sh)
        seen, cand, kept, kept_luck = set(), 0, 0, 0
        for depth, ntree in ((3, n3), (2, n2)):
            for s in range(ntree):
                cols = np.sort(rng.choice(Xr.shape[1], Xr.shape[1] // 2, replace=False))
                clf = DecisionTreeClassifier(max_depth=depth, min_samples_leaf=150, class_weight="balanced",
                                             random_state=s)
                clf.fit(Xr[okA][:, cols], y[okA].astype(int))
                fsub = [fn[c] for c in cols]
                L = leaves(clf, fsub)
                la, lb, lc = (clf.apply(Xr[m][:, cols]) for m in (okA, okB, okC))
                for leaf, path in L.items():
                    key = tuple(sorted((f, round(float(th), 3), le) for f, th, le in path))
                    if key in seen:
                        continue
                    seen.add(key)
                    ma = la == leaf
                    nA, hA = ma.sum(), y[okA][ma].sum()
                    if nA < 150 or hA / nA < 1.5 * bA:
                        continue
                    cand += 1
                    mb, mc = lb == leaf, lc == leaf
                    nB, hB = mb.sum(), y[okB][mb].sum()
                    zB = (hB / max(nB, 1) - bB) / np.sqrt(bB * (1 - bB) / max(nB, 1))
                    hBs = yB_sh[mb].sum()
                    zBs = (hBs / max(nB, 1) - bB) / np.sqrt(bB * (1 - bB) / max(nB, 1))
                    if nB >= 100 and hBs / nB >= 1.3 * bB and zBs >= 2:
                        kept_luck += 1
                    if not (nB >= 100 and hB / nB >= 1.3 * bB and zB >= 2):
                        continue
                    kept += 1
                    nC, hC = mc.sum(), y[okC][mc].sum()
                    expB, expC = pcal[okB][mb].sum(), pcal[okC][mc].sum()
                    rows.append({"target": tn, "target_key": tk, "conditions": len(path),
                                 "rule": "  AND  ".join(cond_text(f, th, le) for f, th, le in path),
                                 "families": ",".join(sorted({f.split(":")[0] for f, _, _ in path})),
                                 "matches_A": int(nA), "hit_A": hA / nA * 100, "normal_A": bA * 100,
                                 "matches_B": int(nB), "hit_B": hB / nB * 100, "normal_B": bB * 100, "z_B": zB,
                                 "matches_C": int(nC), "hit_C": hC / max(nC, 1) * 100, "normal_C": bC * 100,
                                 "hits_C": int(hC),
                                 "odds_say_B": expB / max(nB, 1) * 100, "odds_say_C": expC / max(nC, 1) * 100,
                                 "z_beyond_odds_C": (hC - expC) / np.sqrt(max(expC * (1 - expC / max(nC, 1)), 1e-9)),
                                 "odds_filter_same_size_C": cumC[min(nC, len(cumC) - 1)] / max(nC, 1) * 100})
        luck.append({"target": tn, "target_key": tk, "candidates": cand, "kept": kept, "kept_by_luck": kept_luck})
        print(f"{tn[:42]:42s} normal {bA * 100:5.1f}%  candidates {cand:4d}  kept {kept:4d}  luck {kept_luck:4d}  "
              f"({time.time() - t0:.0f}s)", flush=True)
    r = pd.DataFrame(rows)
    r.to_parquet(CACHE / "hi_trees.parquet")
    pd.DataFrame(luck).to_parquet(CACHE / "hi_trees_luck.parquet")
    return r


if __name__ == "__main__":
    run()
