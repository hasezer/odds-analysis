"""BTTS in both halves, step 3: exhaustive 1- and 2-condition rules, with a luck control.

Two searches:
- 'found on 2024/25': the 40 strongest signs of 2024/25 (bb_signs.py), cut-offs at their 2024/25 top 5 / 10 / 20 /
  30 / 40 / 50%; ranked on 2024/25 by the lower 90% bound of the hit rate (Wilson); confirmed on 2025/26 (hit rate
  >= 1.3 x normal on >= nmin/2 matches); examined on 2026/27.
- 'found on 2025/26': the same, but the signs may include Nesine's own both-halves price and the 2nd-half BTTS
  market (they start in 2025/26); ranked on 2025/26, examined on 2026/27 (no confirm season, so a stricter gate:
  2026/27 >= 1.3 x normal).
Pools: 'scan-ready' (Nesine odds or chances of a listed bet, so the daily scan can check them) and 'all signs'.
Luck control: the whole pipeline (sign choice included) on results shuffled within each season, 10 times.
Each rule is compared with taking the same number of matches with the highest chance from the goal markets (q_bb)
and, where it exists, with Nesine's own both-halves price.
Writes cache/bb_rules.parquet and cache/bb_rules_luck.parquet.
"""
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bb_data  # noqa: E402
from bb_signs import SEAS, pretty  # noqa: E402
from htft3_rules import SCAN_READY, criteria as criteria3, wilson_low  # noqa: E402

SHARES = (0.05, 0.10, 0.20, 0.30, 0.40, 0.50)
K = 40
NMIN = 300


def conditions(d, signs, F):
    cols, desc = [], []
    for r in signs.itertuples():
        x = d[r.sign].to_numpy(float)
        hi = r.direction == "high"
        for sh in SHARES:
            q = np.nanquantile(x[F], 1 - sh if hi else sh)
            m = (x >= q) if hi else (x <= q)
            cols.append(m & ~np.isnan(x))
            desc.append((r.sign, ">=" if hi else "<=", q, sh))
    return np.column_stack(cols).astype(np.float32), desc


def search(d, y, signs, find, keep=300):
    per = d["per"].to_numpy()
    F = per == find
    M, desc = conditions(d, signs, F)
    sign_id = np.array([s for s, _, _, _ in desc])
    stats = {}
    for k in "ABC":
        msk = per == k
        Mk, yk = M[msk], y[msk].astype(np.float32)
        stats[k] = (Mk.T @ Mk, (Mk * yk[:, None]).T @ Mk)
    iu = np.triu_indices(M.shape[1])
    valid = (sign_id[iu[0]] != sign_id[iu[1]]) | (iu[0] == iu[1])
    i, j = iu[0][valid], iu[1][valid]
    nF, hF = stats[find][0][i, j], stats[find][1][i, j]
    ok = nF >= NMIN
    i, j, nF, hF = i[ok], j[ok], nF[ok], hF[ok]
    top = np.argsort(-wilson_low(hF, nF))[:keep]
    rows = []
    for a, b in zip(i[top], j[top]):
        r = {"rule": desc[a] if a == b else (desc[a], desc[b]), "conditions": 1 if a == b else 2}
        for k in "ABC":
            n, h = stats[k][0][a, b], stats[k][1][a, b]
            r[f"matches {SEAS[k]}"], r[f"hits {SEAS[k]}"] = int(n), int(h)
            r[f"hit % {SEAS[k]}"] = h / n * 100 if n else np.nan
        r["_mask"] = (M[:, a] * M[:, b]).astype(bool)
        rows.append(r)
    return pd.DataFrame(rows)


def criteria(rule):
    """Rule -> daily-scan criteria; Nesine's own both-halves price maps to HT_2H_BTTS||YES/YES."""
    parts = [rule] if isinstance(rule[0], str) else list(rule)
    if not any(s in ("p_bb", "o_bb") for s, _, _, _ in parts):
        return criteria3(rule)
    import json
    out = []
    for part in parts:
        s, op, q, _ = part
        if s == "o_bb":
            out.append({"bet": "HT_2H_BTTS||YES/YES", "op": op, "odds": round(float(q), 2)})
        elif s == "p_bb":
            out.append({"bet": "HT_2H_BTTS||YES/YES", "op": op, "chance_pct": round(float(q) * 100, 2)})
        else:
            c = criteria3(part)
            if c is None:
                return None
            out += json.loads(c)
    return json.dumps(out)


def text(rule):
    parts = [rule] if isinstance(rule[0], str) else list(rule)
    out = []
    for s, op, q, sh in parts:
        if s.startswith(("odds_", "o_")):
            v = f"{q:.2f}"
        elif s.startswith(("f_", "cs_", "hcs_", "p_", "q_")) or s in ("s_both2_model", "s_both2_market",
                                                                      "s_both2_market_min", "s_half_markets",
                                                                      "s_1h_market_x_2h_model", "s_cs_both2"):
            v = f"{q * 100:.1f}%"
        else:
            v = f"{q:.3g}"
        out.append(f"{pretty(s)} {'≥' if op == '>=' else '≤'} {v}")
    return "  AND  ".join(out)


def same_size(d, y, score, mask, k):
    """Hit rate of the same number of season-k matches with the highest score (matches without it excluded)."""
    m = (d["per"] == k).to_numpy() & ~np.isnan(score)
    n = int((mask & (d["per"] == k).to_numpy()).sum())
    if n == 0 or m.sum() < n:
        return np.nan
    idx = np.argsort(-score[m], kind="stable")[:n]
    return y[m][idx].mean() * 100


def run_one(d, y, signs_all, find, scan_ready, shuffle_seed=None):
    if shuffle_seed is not None:
        rng = np.random.default_rng(shuffle_seed)
        y = y.copy()
        for k in "ABC":
            m = (d["per"] == k).to_numpy()
            y[m] = rng.permutation(y[m])
    F = (d["per"] == find).to_numpy()
    sig = signs_all.copy()
    lifts = []
    for r in sig.itertuples():                       # strongest signs on the find season (re-picked when shuffled)
        x = d[r.sign].to_numpy(float)
        ok = F & ~np.isnan(x)
        if ok.sum() < 0.3 * F.sum():
            lifts.append(-1)
            continue
        q = np.nanquantile(x[ok], .9 if r.direction == "high" else .1)
        m = ok & ((x >= q) if r.direction == "high" else (x <= q))
        lifts.append(y[m].mean() if m.sum() else 0)
    sig = sig.assign(lift=lifts)
    sig = sig[sig["lift"] >= 0]
    if scan_ready:
        sig = sig[sig["sign"].str.startswith(SCAN_READY)]
    sig = sig.sort_values("lift", ascending=False).head(K)
    res = search(d, y, sig, find)
    normal = {k: y[(d["per"] == k).to_numpy()].mean() * 100 for k in "ABC"}
    if find == "A":
        res["confirmed"] = (res["hit % 2025/26"] >= 1.3 * normal["B"]) & (res["matches 2025/26"] >= NMIN / 2)
    else:
        res["confirmed"] = (res["hit % 2026/27"] >= 1.3 * normal["C"]) & (res["matches 2026/27"] >= NMIN / 3)
    return res, normal


def run(n_luck=10):
    d = bb_data.build()
    S = pd.read_parquet(bb_data.CACHE / "bb_signs.parquet")
    S = S[S["target"] == "BTTS both halves"]
    y = d["y_bb"].to_numpy(float)
    q = d["q_bb"].to_numpy(float)
    own = d["p_bb"].to_numpy(float)
    out, luck = [], []
    for find, sig_pool in (("A", S[S["found on"] == "2024/25"]), ("B", S)):
        for pool, sr in (("scan-ready", True), ("all signs", False)):
            res, normal = run_one(d, y, sig_pool[["sign", "direction"]], find, sr)
            for k in ("B", "C"):
                res[f"model q_bb, same size, % {SEAS[k]}"] = [same_size(d, y, q, m, k) for m in res["_mask"]]
                res[f"own price, same size, % {SEAS[k]}"] = [same_size(d, y, own, m, k) for m in res["_mask"]]
            res["criteria"] = [criteria(r) for r in res["rule"]]
            res["rule"] = [text(r) for r in res["rule"]]
            res = res.drop(columns="_mask")
            res.insert(0, "pool", pool)
            res.insert(0, "found on", SEAS[find])
            for k, nm in SEAS.items():
                res[f"normal % {nm}"] = normal[k]
            out.append(res)
            for s in range(n_luck):
                lr, _ = run_one(d, y, sig_pool[["sign", "direction"]], find, sr, shuffle_seed=2000 + s)
                luck.append({"found on": SEAS[find], "pool": pool, "run": s, "confirmed": int(lr["confirmed"].sum())})
            print(SEAS[find], pool, int(res["confirmed"].sum()), "confirmed; luck runs:",
                  [x["confirmed"] for x in luck[-n_luck:]], flush=True)
    R = pd.concat(out, ignore_index=True)
    L = pd.DataFrame(luck)
    R.to_parquet(bb_data.CACHE / "bb_rules.parquet")
    L.to_parquet(bb_data.CACHE / "bb_rules_luck.parquet")
    return R, L


if __name__ == "__main__":
    R, L = run()
    pd.set_option("display.width", 260)
    pd.set_option("display.max_colwidth", 110)
    cols = ["found on", "pool", "rule", "matches 2024/25", "hit % 2024/25", "matches 2025/26", "hit % 2025/26",
            "matches 2026/27", "hit % 2026/27", "model q_bb, same size, % 2025/26", "model q_bb, same size, % 2026/27",
            "own price, same size, % 2026/27"]
    for (f, p), g in R[R["confirmed"]].groupby(["found on", "pool"]):
        print(f, p)
        print(g[cols].head(8).round(1).to_string(index=False))
