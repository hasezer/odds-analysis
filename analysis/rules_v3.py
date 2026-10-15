"""Rule hunt v3: every bet type Nesine prices (~160, corners included) x the v3 condition library
(price ranges, equal prices + six new families, see rules_v3_data.py), rules with 1, 2 or 3 conditions.

Two tracks, each with its own search, gates and luck control:
  hit    the bet hits clearly more often than normal                    (odds ratio vs the normal rate)
  price  the bet hits more often than Nesine's own price says it should (hits minus fair chance, z-score)
Search choices are made on period A only (2024/25 + 2024); B (2025/26 + 2025) confirms; C (2026/27 + 2026) is
the exam. Luck control: the same gates with the B and C results shuffled across matches.
  hit    A: matches >= 200 (150 for 3 conditions), z >= 3, odds ratio >= 1.4 (3rd condition: >= 1.1 vs its parent)
         B: matches >= 100, z >= 2, odds ratio >= 1.3          C: matches >= 20, odds ratio >= 1.15
  price  A: priced matches >= 200 (150), z >= 3.5                 (3rd condition must raise z)
         B: priced matches >= 100, z >= 2                       C: priced matches >= 20, hits > price
Writes cache/rules_v3.parquet and cache/rules_v3_luck.parquet.
"""
from pathlib import Path
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import miner_data as mdat  # noqa: E402
import rules_deep as rd  # noqa: E402
import rules_v3_data as v3  # noqa: E402
from htft_data import CACHE  # noqa: E402
from rule_miner import nice  # noqa: E402
from rules_targets import tr_labels  # noqa: E402

BEAM = 300
CAP = 3000          # candidates kept per track and number of conditions
KEEP_AB = False     # also keep rules that passed A and B but not C (for the rule-stacking test, rules_v3_vote.py)
P = "ABC"


def odds_ratio(r, b):
    r, b = np.clip(r, 1e-6, 1 - 1e-6), np.clip(b, 1e-6, 1 - 1e-6)
    return (r / (1 - r)) / (b / (1 - b))


def targets(z):
    O, F, Hm, names = z["O"], z["F"], z["Hm"], list(z["names"])
    trn = tr_labels(names)
    out = []
    for i, n in enumerate(names):
        out.append({"key": n, "name": nice(n), "name_tr": trn[i], "y": Hm[:, i], "f": F[:, i], "o": O[:, i],
                    "own": {n.split("|")[0]}})
    T, own, price_lab = rd.build_targets(z["match_ids"])
    nan = np.full(len(z["match_ids"]), np.nan, np.float32)
    for k in ("HT/FT turnaround (1/2 or 2/1)", "Total goals 5+"):
        out.append({"key": k, "name": k, "name_tr": k, "y": T[k], "f": nan, "o": nan, "own": own[k]})
    return out


def run(only=None):
    z = mdat.build()
    a = v3.build()
    per = z["per"]
    Xb = a["X"]
    K = Xb.shape[1]
    amk = [set(s.split(",")) - {""} for s in a["mkt"]]
    fam = a["fam"]
    X = {p: np.ascontiguousarray(Xb[per == p], dtype=np.float32) for p in P}
    print(f"{K} conditions, {len(per)} matches", flush=True)
    rows, luck = [], []
    rng = np.random.default_rng(0)
    for t in targets(z):
        if only and t["key"] not in only:
            continue
        t0 = time.time()
        d = {}
        for p in P:
            y, f, o = (t[c][per == p].astype(np.float64) for c in ("y", "f", "o"))
            V = ~np.isnan(y)
            W = V & ~np.isnan(f) & ~np.isnan(o)
            d[p] = dict(V=V.astype(np.float32), Y=np.where(V, y, 0).astype(np.float32), W=W.astype(np.float32),
                        R=np.where(W, y - f, 0).astype(np.float32), S=np.where(W, f * (1 - f), 0).astype(np.float32),
                        Pf=np.where(W, f, 0).astype(np.float32), Ret=np.where(W, y * o - 1, 0).astype(np.float32))
            d[p]["base"] = d[p]["Y"].sum() / max(d[p]["V"].sum(), 1)
        if d["A"]["V"].sum() < 1000 or not (.002 < d["A"]["base"] < .998):
            continue
        priced = d["A"]["W"].sum() >= 1000
        bad = np.array([len(m & t["own"]) > 0 for m in amk])
        XA, dA, bA = X["A"], d["A"], d["A"]["base"]
        prod = lambda w: (XA * w[:, None]).T @ XA
        N2, H2 = prod(dA["V"]), prod(dA["Y"])
        ok_pair = np.triu(~bad[:, None] & ~bad[None, :], 1)
        cands = {}                                       # atoms tuple -> set of tracks

        def take(keys, track):
            for k in keys:
                cands.setdefault(tuple(sorted(int(x) for x in k)), set()).add(track)

        # ---- hit track
        r2 = H2 / np.maximum(N2, 1)
        z2 = (r2 - bA) / np.sqrt(bA * (1 - bA) / np.maximum(N2, 1))
        g1 = (N2 >= 200) & (z2 >= 3) & (odds_ratio(r2, bA) >= 1.4)
        dg = np.diag(g1) & ~bad
        take([(k,) for k in np.where(dg)[0]], "hit")
        ii, jj = np.where(g1 & ok_pair)
        o_ = np.argsort(-z2[ii, jj])[:CAP]
        take(zip(ii[o_], jj[o_]), "hit")
        pi, pj = np.where((N2 >= 300) & ok_pair)
        top = np.argsort(-z2[pi, pj])[:BEAM]
        Pi, Pj = pi[top], pj[top]
        if len(Pi):
            M = XA[:, Pi] * XA[:, Pj]
            n3, h3 = (M * dA["V"][:, None]).T @ XA, (M * dA["Y"][:, None]).T @ XA
            r3 = h3 / np.maximum(n3, 1)
            z3 = (r3 - bA) / np.sqrt(bA * (1 - bA) / np.maximum(n3, 1))
            par = (H2[Pi, Pj] / np.maximum(N2[Pi, Pj], 1))[:, None]
            g3 = ((n3 >= 150) & (z3 >= 3) & (odds_ratio(r3, bA) >= 1.4) & (odds_ratio(r3, par) >= 1.1)
                  & ~bad[None, :] & (np.arange(K)[None, :] != Pi[:, None]) & (np.arange(K)[None, :] != Pj[:, None]))
            bi, kk = np.where(g3)
            o_ = np.argsort(-z3[bi, kk])[:CAP]
            take(zip(Pi[bi[o_]], Pj[bi[o_]], kk[o_]), "hit")

        # ---- price track
        if priced:
            C2, R2, S2 = prod(dA["W"]), prod(dA["R"]), prod(dA["S"])
            zr = R2 / np.sqrt(np.maximum(S2, 1e-6))
            g1 = (C2 >= 200) & (zr >= 3.5)
            take([(k,) for k in np.where(np.diag(g1) & ~bad)[0]], "price")
            ii, jj = np.where(g1 & ok_pair)
            o_ = np.argsort(-zr[ii, jj])[:CAP]
            take(zip(ii[o_], jj[o_]), "price")
            pi, pj = np.where((C2 >= 300) & ok_pair)
            top = np.argsort(-zr[pi, pj])[:BEAM]
            Pi, Pj = pi[top], pj[top]
            if len(Pi):
                M = XA[:, Pi] * XA[:, Pj]
                c3, rr3, s3 = ((M * dA[c][:, None]).T @ XA for c in ("W", "R", "S"))
                z3 = rr3 / np.sqrt(np.maximum(s3, 1e-6))
                g3 = ((c3 >= 150) & (z3 >= 3.5) & (z3 >= zr[Pi, Pj][:, None] + .5) & ~bad[None, :]
                      & (np.arange(K)[None, :] != Pi[:, None]) & (np.arange(K)[None, :] != Pj[:, None]))
                bi, kk = np.where(g3)
                o_ = np.argsort(-z3[bi, kk])[:CAP]
                take(zip(Pi[bi[o_]], Pj[bi[o_]], kk[o_]), "price")

        # ---- confirm (B), exam (C), luck control
        sh = {}
        for p in "BC":
            Vb, Wb = d[p]["V"] > 0, d[p]["W"] > 0
            s = {}
            perm = rng.permutation(np.where(Vb)[0])
            Ysh = np.zeros_like(d[p]["Y"]); Ysh[np.where(Vb)[0]] = d[p]["Y"][perm]
            s["Y"] = Ysh
            perm = rng.permutation(np.where(Wb)[0])                 # price track: move (result, price) pairs together
            for c in ("R", "S", "W"):
                v = np.zeros_like(d[p][c]); v[np.where(Wb)[0]] = d[p][c][perm]; s[c] = v
            sh[p] = s
        keys = list(cands)
        kept = {"hit": 0, "price": 0}
        kept_luck = {"hit": 0, "price": 0}
        for c0 in range(0, len(keys), 1000):
            chunk = keys[c0:c0 + 1000]
            st = {}
            for p in P:
                Xp = X[p]
                Mk = np.stack([Xp[:, list(k)].prod(1) for k in chunk], 1)
                st[p] = {c: d[p][c] @ Mk for c in ("V", "Y", "W", "R", "S", "Pf", "Ret")}
                if p in sh:
                    st[p].update({f"s{c}": sh[p][c] @ Mk for c in ("Y", "R", "S", "W")})
            ok = {}
            for tag, pre in (("real", ""), ("luck", "s")):
                b, c_ = d["B"]["base"], d["C"]["base"]
                nB, hB, nC, hC = st["B"]["V"], st["B"][pre + "Y"], st["C"]["V"], st["C"][pre + "Y"]
                rB, rC = hB / np.maximum(nB, 1), hC / np.maximum(nC, 1)
                zB = (rB - b) / np.sqrt(b * (1 - b) / np.maximum(nB, 1))
                abh = (nB >= 100) & (zB >= 2) & (odds_ratio(rB, b) >= 1.3)
                abh &= np.array(["hit" in cands[k] for k in chunk])
                okh = abh & (nC >= 20) & (odds_ratio(rC, c_) >= 1.15)
                wB, wC = st["B"][pre + "W"], st["C"][pre + "W"]
                zrB = st["B"][pre + "R"] / np.sqrt(np.maximum(st["B"][pre + "S"], 1e-6))
                abp = (wB >= 100) & (zrB >= 2)
                abp &= np.array(["price" in cands[k] for k in chunk])
                okp = abp & (wC >= 20) & (st["C"][pre + "R"] > 0)
                ok[tag] = (okh, okp, abh, abp)
            kept_luck["hit"] += int(ok["luck"][0].sum()); kept_luck["price"] += int(ok["luck"][1].sum())
            keep = (ok["real"][2] | ok["real"][3]) if KEEP_AB else (ok["real"][0] | ok["real"][1])
            for q in np.where(keep)[0]:
                k = chunk[q]
                tr_ = [n for n, f in (("hit", ok["real"][0][q]), ("price", ok["real"][1][q])) if f]
                for x in tr_:
                    kept[x] += 1
                row = {"target_key": t["key"], "target": t["name"], "target_tr": t["name_tr"], "tracks": ",".join(tr_),
                       "ab_hit": bool(ok["real"][2][q]), "ab_price": bool(ok["real"][3][q]),
                       "conditions": len(k), "atoms": ",".join(map(str, k)),
                       "families": ",".join(sorted({fam[i] for i in k})),
                       "rule": "  AND  ".join(a["en"][i] for i in k), "kural": "  VE  ".join(a["tr"][i] for i in k)}
                for p in P:
                    s = st[p]
                    row.update({f"matches_{p}": int(s["V"][q]), f"hits_{p}": int(round(s["Y"][q])),
                                f"normal_{p}": d[p]["base"] * 100, f"priced_{p}": int(s["W"][q]),
                                f"pricehits_{p}": float(s["R"][q] + s["Pf"][q]), f"price_{p}": float(s["Pf"][q]),
                                f"ret_{p}": float(s["Ret"][q]), f"var_{p}": float(s["S"][q])})
                rows.append(row)
        luck.append({"target": t["name"], "target_key": t["key"], "candidates": len(keys),
                     "kept_hit": kept["hit"], "luck_hit": kept_luck["hit"],
                     "kept_price": kept["price"], "luck_price": kept_luck["price"]})
        print(f"{t['name'][:34]:34s} base {bA * 100:5.1f}%  cand {len(keys):5d}  hit {kept['hit']:4d} "
              f"(luck {kept_luck['hit']:4d})  price {kept['price']:4d} (luck {kept_luck['price']:4d})  "
              f"{time.time() - t0:.0f}s", flush=True)
    r = pd.DataFrame(rows)
    if len(r):
        for c in ("matches", "hits", "priced", "pricehits", "price", "ret", "var"):
            r[f"{c}_all"] = r[[f"{c}_{p}" for p in P]].sum(axis=1)
        for p in list(P) + ["_all"]:
            p_ = p if p == "_all" else f"_{p}"
            r[f"hit{p_}"] = r[f"hits{p_}"] / r[f"matches{p_}"] * 100
            r[f"price_says{p_}"] = r[f"price{p_}"] / r[f"priced{p_}"] * 100
            r[f"hit_when_priced{p_}"] = r[f"pricehits{p_}"] / r[f"priced{p_}"] * 100
            r[f"return_per_100{p_}"] = r[f"ret{p_}"] / r[f"priced{p_}"] * 100
        r["normal_all"] = sum(r[f"normal_{p}"] * r[f"matches_{p}"] for p in P) / r["matches_all"]
        r["lift_all"] = r["hit_all"] / r["normal_all"]
    tag = "_ab" if KEEP_AB else "" if not only else "_test"
    r.to_parquet(CACHE / f"rules_v3{tag}.parquet")
    pd.DataFrame(luck).to_parquet(CACHE / f"rules_v3_luck{tag}.parquet")
    return r


if __name__ == "__main__":
    if "--keep-ab" in sys.argv:
        KEEP_AB = True
        sys.argv.remove("--keep-ab")
    only = set(sys.argv[1:]) or None
    r = run(only)
    print(len(r))
