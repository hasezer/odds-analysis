"""HT/FT study 3, step 2: exhaustive 1- and 2-condition rules for the six changing results (+ three pairs).

Per result:
1. Candidate signs: the 40 strongest single signs on 2024/25 (+2024) ONLY (htft3_signs.py, by top-10% hit rate in
   2024/25). Two pools: 'scan-ready' (Nesine odds or chances of a listed bet, so the daily scan can check them) and
   'all' (also the other-markets model, Nesine's after-half-time chances, team habits, league, calendar).
2. Cut-offs at the 2024/25 quantiles: the sign's top 5 / 10 / 20 / 30 / 40 / 50% in its good direction.
3. Every single condition and every pair of conditions on two different signs (about 28,000 rules per result).
4. Find: at least `nmin` matches in 2024/25; ranked by the lower 90% bound of the hit rate (Wilson); top 300 kept.
   Confirm: 2025/26 hit rate >= 1.3 x normal with >= nmin/2 matches. Exam: 2026/27 shown as is.
5. Luck control: the same pipeline (sign choice included) on results shuffled within each season, 10 times.
6. Each confirmed rule is compared with simply taking the same number of matches with the lowest odds for that
   result (the 'own odds filter of the same size') in 2025/26 and 2026/27.
Writes cache/htft3_rules.parquet and cache/htft3_rules_luck.parquet.
"""
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import htft3_data as h3  # noqa: E402
from htft3_signs import PAIRS, SEAS, pretty  # noqa: E402
from htft_data import CACHE  # noqa: E402

SHARES = (0.05, 0.10, 0.20, 0.30, 0.40, 0.50)
K = 40
SCAN_READY = ("odds_", "f_", "cs_", "hcs_", "p_", "o_")


def wilson_low(h, n, z=1.2816):
    n = np.maximum(n, 1)
    ph = h / n
    return (ph + z * z / (2 * n) - z * np.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n))) / (1 + z * z / n)


def conditions(d, signs, A):
    """Boolean matrix of conditions: each sign x cut-off in its good direction (cut-offs from 2024/25)."""
    cols, desc = [], []
    for r in signs.itertuples():
        x = d[r.sign].to_numpy(float)
        hi = r.direction == "high"
        for sh in SHARES:
            q = np.nanquantile(x[A], 1 - sh if hi else sh)
            m = (x >= q) if hi else (x <= q)
            cols.append(m & ~np.isnan(x))
            desc.append((r.sign, ">=" if hi else "<=", q, sh))
    return np.column_stack(cols).astype(np.float32), desc


def search(d, y, signs, nmin, keep=300):
    per = d["per"].to_numpy()
    A, B, C = (per == "A"), (per == "B"), (per == "C")
    M, desc = conditions(d, signs, A)
    ncond = M.shape[1]
    sign_id = np.array([s for s, _, _, _ in desc])
    stats = {}
    for k, msk in (("A", A), ("B", B), ("C", C)):
        Mk = M[msk]
        yk = y[msk].astype(np.float32)
        stats[k] = (Mk.T @ Mk, (Mk * yk[:, None]).T @ Mk)          # pair counts, pair hits (diagonal = singles)
    iu = np.triu_indices(ncond)
    valid = sign_id[iu[0]] != sign_id[iu[1]]
    valid |= iu[0] == iu[1]
    i, j = iu[0][valid], iu[1][valid]
    nA, hA = stats["A"][0][i, j], stats["A"][1][i, j]
    ok = nA >= nmin
    i, j, nA, hA = i[ok], j[ok], nA[ok], hA[ok]
    lowA = wilson_low(hA, nA)
    top = np.argsort(-lowA)[:keep]
    i, j = i[top], j[top]
    rows = []
    for a, b in zip(i, j):
        r = {"rule": desc[a] if a == b else (desc[a], desc[b]), "conditions": 1 if a == b else 2}
        for k in ("A", "B", "C"):
            n, h = stats[k][0][a, b], stats[k][1][a, b]
            r[f"matches {SEAS[k]}"], r[f"hits {SEAS[k]}"] = int(n), int(h)
            r[f"hit % {SEAS[k]}"] = h / n * 100 if n else np.nan
        r["_mask"] = (M[:, a] * M[:, b]).astype(bool)
        rows.append(r)
    return pd.DataFrame(rows)


def criteria(rule):
    """Rule -> daily-scan criteria (only for scan-ready signs); None if a sign is not checkable from the odds."""
    from htft3_signs import label_of_f
    parts = [rule] if isinstance(rule[0], str) else list(rule)
    out = []
    for s, op, q, sh in parts:
        if s.startswith("odds_"):
            out.append({"bet": s[5:], "op": op, "odds": round(float(q), 2)})
        elif s.startswith("o_"):
            out.append({"bet": f"HT_FT||{s[2:]}", "op": op, "odds": round(float(q), 2)})
        elif s.startswith("p_"):
            out.append({"bet": f"HT_FT||{s[2:]}", "op": op, "chance_pct": round(float(q) * 100, 2)})
        elif s.startswith("f_") and label_of_f(s):
            out.append({"bet": label_of_f(s), "op": op, "chance_pct": round(float(q) * 100, 2)})
        elif s.startswith("hcs_"):
            out.append({"bet": f"HT_CORRECT_SCORE||{s[4:]}", "op": op, "chance_pct": round(float(q) * 100, 2)})
        elif s.startswith("cs_"):
            out.append({"bet": f"CORRECT_SCORE||{s[3:]}", "op": op, "chance_pct": round(float(q) * 100, 2)})
        else:
            return None
    return json.dumps(out)


def text(rule):
    parts = [rule] if isinstance(rule[0], str) else list(rule)
    out = []
    for s, op, q, sh in parts:
        v = f"{q:.2f}" if s.startswith(("odds_", "o_")) else (f"{q * 100:.1f}%" if s.startswith(("f_", "cs_", "hcs_",
                                                                                                 "p_", "q_", "c_"))
                                                                 else f"{q:.3g}")
        out.append(f"{pretty(s)} {'≥' if op == '>=' else '≤'} {v}")
    return "  AND  ".join(out)


def own_filter(d, y, p, mask, per):
    """Hit rate of the same number of matches with the highest own price chance, in season `per`."""
    m = (d["per"] == per).to_numpy()
    n = int((mask & m).sum())
    if n == 0:
        return np.nan
    idx = np.argsort(-p[m])[:n]
    return y[m][idx].mean() * 100


def run_target(d, ycol, pcol, signs_all, nmin, scan_ready, shuffle_seed=None):
    y = d[ycol].to_numpy(float)
    if shuffle_seed is not None:
        rng = np.random.default_rng(shuffle_seed)
        y = y.copy()
        for k in ("A", "B", "C"):
            m = (d["per"] == k).to_numpy()
            y[m] = rng.permutation(y[m])
    sig = signs_all.copy()
    if shuffle_seed is not None:                      # re-pick the signs on the shuffled 2024/25 results
        A = (d["per"] == "A").to_numpy()
        lifts = []
        for r in sig.itertuples():
            x = d[r.sign].to_numpy(float)
            q = np.nanquantile(x[A], .9 if r.direction == "high" else .1)
            m = A & ((x >= q) if r.direction == "high" else (x <= q))
            lifts.append(y[m].mean() if m.sum() else 0)
        sig = sig.assign(**{"top 10% hit % 2024/25": np.array(lifts) * 100})
    if scan_ready:
        sig = sig[sig["sign"].str.startswith(SCAN_READY)]
    sig = sig.sort_values("top 10% hit % 2024/25", ascending=False).head(K)
    res = search(d.assign(**{ycol: y}), y, sig, nmin)
    nB = {k: (d["per"] == k).sum() for k in "ABC"}
    normal = {k: y[(d["per"] == k).to_numpy()].mean() * 100 for k in "ABC"}
    res["confirmed"] = (res["hit % 2025/26"] >= 1.3 * normal["B"]) & (res["matches 2025/26"] >= nmin / 2)
    return res, normal


def run(n_luck=10):
    d = h3.build()
    for name, ys in PAIRS.items():
        d["y_" + name] = d[ys].max(axis=1)
        a, b = (y[2:] for y in ys)
        d["p_" + name] = d[f"p_{a[0]}/{a[1]}"] + d[f"p_{b[0]}/{b[1]}"]
    S = pd.read_parquet(CACHE / "htft3_signs.parquet")
    targets = [(lab, y, f"p_{lab}") for lab, y in h3.TARGETS.items()] + \
              [(name, "y_" + name, "p_" + name) for name in PAIRS]
    out, luck = [], []
    for lab, ycol, pcol in targets:
        sig = S[S["result"] == lab][["sign", "direction", "top 10% hit % 2024/25"]]
        rate = d[ycol].mean()
        nmin = 150 if rate > 0.08 else 300
        for pool, sr in (("scan-ready", True), ("all signs", False)):
            res, normal = run_target(d, ycol, pcol, sig, nmin, sr)
            y = d[ycol].to_numpy(float)
            p = d[pcol].to_numpy(float)
            res["own odds filter, same size, % 2025/26"] = [own_filter(d, y, p, m, "B") for m in res["_mask"]]
            res["own odds filter, same size, % 2026/27"] = [own_filter(d, y, p, m, "C") for m in res["_mask"]]
            res["criteria"] = [criteria(r) for r in res["rule"]]
            res["rule"] = [text(r) for r in res["rule"]]
            res = res.drop(columns="_mask")
            res.insert(0, "pool", pool)
            res.insert(0, "result", lab)
            for k, nm in SEAS.items():
                res[f"normal % {nm}"] = normal[k]
            out.append(res)
            for s in range(n_luck):
                lr, _ = run_target(d, ycol, pcol, sig, nmin, sr, shuffle_seed=1000 + s)
                luck.append({"result": lab, "pool": pool, "run": s, "confirmed": int(lr["confirmed"].sum())})
            print(lab, pool, int(res["confirmed"].sum()), "confirmed; luck runs:",
                  [x["confirmed"] for x in luck[-n_luck:]], flush=True)
    R = pd.concat(out, ignore_index=True)
    L = pd.DataFrame(luck)
    R.to_parquet(CACHE / "htft3_rules.parquet")
    L.to_parquet(CACHE / "htft3_rules_luck.parquet")
    return R, L


if __name__ == "__main__":
    run()
