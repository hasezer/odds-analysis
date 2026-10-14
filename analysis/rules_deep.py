"""Deep rule search for high-odds bets: HT/FT, correct scores, 1st-half scores, 6+ / 5+ goals,
both teams score in both halves. Rules with one, two or THREE price conditions.

Atoms (closing odds of the match; the target's own market is never used):
  range  odds of one selection inside one of its 10 price ranges (period-A deciles)       1,447 atoms
  equal  two odds within 0.10 of each other                                               ~1,000 atoms
Search (choices made on period A only, so B and C stay a fair test):
  1 and 2 atoms   all of them, counted with matrix products on period A
  3 atoms         beam search: the 400 best 2-atom rules of period A, each extended with every atom
Gates:
  find     A (2024/25 + 2024): matches >= 150 (3 atoms) / 200, z >= 3, lift >= 1.3
           (a 3rd atom must also lift the hit rate at least 10% above its 2-atom parent)
  confirm  B (2025/26 + 2025): matches >= 100, z >= 2, lift >= 1.25
  exam     C (2026/27 + 2026 so far): lift >= 1.1 (reported; C is small)
Writes cache/rules_deep.parquet.
"""
from pathlib import Path
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import load  # noqa: E402
import miner_data as mdat  # noqa: E402
from htft_data import CACHE  # noqa: E402
from rule_miner import nice  # noqa: E402
from rules_targets import tr_labels  # noqa: E402

NB = 10
BEAM = 400
CAND_CAP = 4000


def build_targets(match_ids):
    m = load.matches().set_index("match_id").loc[match_ids]
    h1, a1, fh, fa = (m[c].to_numpy(float) for c in ("ht_home", "ht_away", "ft_home", "ft_away"))
    h2, a2 = fh - h1, fa - a1
    ok = ~np.isnan(h1)
    res = lambda h, a: np.where(h > a, "1", np.where(h == a, "X", "2"))
    ht, ft = res(h1, a1), res(fh, fa)
    T, own = {}, {}
    for a in "1X2":
        for b in "1X2":
            T[f"HT/FT {a}/{b}"] = (ht == a) & (ft == b); own[f"HT/FT {a}/{b}"] = {"HT_FT"}
    T["HT/FT turnaround (1/2 or 2/1)"] = ((ht == "1") & (ft == "2")) | ((ht == "2") & (ft == "1"))
    own["HT/FT turnaround (1/2 or 2/1)"] = {"HT_FT"}
    for s in ["0-0", "1-0", "0-1", "1-1", "2-0", "0-2", "2-1", "1-2", "2-2", "3-0", "0-3", "3-1", "1-3", "3-2", "2-3",
              "4-0", "4-1", "3-3"]:
        x, y = map(int, s.split("-"))
        T[f"Score {s}"] = (fh == x) & (fa == y); own[f"Score {s}"] = {"CORRECT_SCORE"}
    for s in ["1-1", "2-0", "0-2", "2-1", "1-2"]:
        x, y = map(int, s.split("-"))
        T[f"1st-half score {s}"] = (h1 == x) & (a1 == y); own[f"1st-half score {s}"] = {"HT_CORRECT_SCORE"}
    T["Total goals 6+"] = (fh + fa) >= 6; own["Total goals 6+"] = {"GOAL_RANGE"}
    T["Total goals 5+"] = (fh + fa) >= 5; own["Total goals 5+"] = {"GOAL_RANGE"}
    T["Both teams score in BOTH halves"] = (h1 > 0) & (a1 > 0) & (h2 > 0) & (a2 > 0)
    own["Both teams score in BOTH halves"] = {"HT_2H_BTTS"}
    T = {k: np.where(ok, v.astype(float), np.nan) for k, v in T.items()}
    # Nesine's own price for the target (where the market exists): label in the miner matrices
    price_lab = {f"HT/FT {a}/{b}": f"HT_FT||{a}/{b}" for a in "1X2" for b in "1X2"}
    price_lab.update({f"Score {s}": f"CORRECT_SCORE||{s}" for s in
                      ["0-0", "1-0", "0-1", "1-1", "2-0", "0-2", "2-1", "1-2", "2-2", "3-0", "0-3", "3-1", "1-3", "3-2",
                       "2-3", "4-0", "4-1", "3-3"]})
    price_lab.update({f"1st-half score {s}": f"HT_CORRECT_SCORE||{s}" for s in ["1-1", "2-0", "0-2", "2-1", "1-2"]})
    price_lab["Total goals 6+"] = "GOAL_RANGE||6+"
    return T, own, price_lab


def atoms(z):
    O, per, names = z["O"], z["per"], z["names"]
    S = len(names)
    mk = np.array([n.split("|")[0] for n in names])
    en, trl = [nice(n) for n in names], tr_labels(names)
    A = per == "A"
    spec, lab, mkt = [], [], []
    for i in range(S):
        col = O[A, i]
        if np.isnan(col).mean() > .5:
            continue
        e = np.unique(np.round(np.nanquantile(col, np.linspace(0, 1, NB + 1)), 2))
        e[0], e[-1] = 0, 1e9
        for k in range(len(e) - 1):
            lo, hi = e[k], e[k + 1]
            txt = f"≤ {hi:.2f}" if lo == 0 else f"> {lo:.2f}" if hi == 1e9 else f"{lo:.2f}–{hi:.2f}"
            spec.append(("r", i, lo, hi)); mkt.append({mk[i]}); lab.append((f"{en[i]} odds {txt}", f"{trl[i]} {txt}"))
    for i in range(S):
        for j in range(i + 1, S):
            if mk[i] == mk[j]:
                continue
            a, b = O[A, i], O[A, j]
            ok = ~np.isnan(a) & ~np.isnan(b)
            if ok.sum() >= 1000 and (np.abs(a[ok] - b[ok]) <= .10).sum() >= 200:
                spec.append(("e", i, j, 0)); mkt.append({mk[i], mk[j]})
                lab.append((f"{en[i]} ≈ {en[j]} (±0.10)", f"{trl[i]} ≈ {trl[j]} (±0,10)"))
    return spec, lab, mkt


def masks(spec, O):
    cols = []
    for s in spec:
        if s[0] == "r":
            _, i, lo, hi = s
            cols.append((O[:, i] > lo) & (O[:, i] <= hi))
        else:
            _, i, j, _ = s
            cols.append(np.abs(O[:, i] - O[:, j]) <= .10)
    return np.stack(cols, 1).astype(np.float32)


def zscore(h, n, base):
    rate = h / np.maximum(n, 1)
    return rate, (rate - base) / np.sqrt(base * (1 - base) / np.maximum(n, 1))


def run():
    z = mdat.build()
    O, F, per, names = z["O"], z["F"], z["per"], list(z["names"])
    spec, lab, mkt = atoms(z)
    K = len(spec)
    T, own, price_lab = build_targets(z["match_ids"])
    X = {p: masks(spec, O[per == p]) for p in "ABC"}
    print(f"{K} atoms; computing A co-occurrence…", flush=True)
    NA2 = X["A"].T @ X["A"]
    rows = []
    for tname, tv in T.items():
        t0 = time.time()
        Y = {p: np.nan_to_num(tv[per == p]).astype(np.float32) for p in "ABC"}
        V = {p: (~np.isnan(tv[per == p])).astype(np.float32) for p in "ABC"}
        base = {p: Y[p].sum() / V[p].sum() for p in "ABC"}
        bad = np.array([len(m & own[tname]) > 0 for m in mkt])
        XA, yA = X["A"], Y["A"]
        HA2 = (XA * yA[:, None]).T @ XA
        n1, h1 = np.diag(NA2), np.diag(HA2)
        r1, z1 = zscore(h1, n1, base["A"])
        r2, z2 = zscore(HA2, NA2, base["A"])
        ok2 = (NA2 >= 200) & (z2 >= 3) & (r2 >= 1.3 * base["A"]) & ~bad[:, None] & ~bad[None, :]
        ok2 = np.triu(ok2, 1)
        cands = []                                      # (atoms tuple, n_A, hits_A)
        for k in np.where((n1 >= 200) & (z1 >= 3) & (r1 >= 1.3 * base["A"]) & ~bad)[0]:
            cands.append(((k,), n1[k], h1[k]))
        ii, jj = np.where(ok2)
        order = np.argsort(-z2[ii, jj])
        for o in order[:CAND_CAP]:
            cands.append(((ii[o], jj[o]), NA2[ii[o], jj[o]], HA2[ii[o], jj[o]]))
        # beam: best 2-atom parents with room to split further
        pr, pz = np.where(np.triu((NA2 >= 300) & ~bad[:, None] & ~bad[None, :], 1)), None
        pz = z2[pr]
        top = np.argsort(-pz)[:BEAM]
        P_i, P_j = pr[0][top], pr[1][top]
        if len(P_i):
            M = XA[:, P_i] * XA[:, P_j]                                  # N_A x beam
            n3 = M.T @ XA
            h3 = (M * yA[:, None]).T @ XA
            r3, z3 = zscore(h3, n3, base["A"])
            parent_rate = (HA2[P_i, P_j] / np.maximum(NA2[P_i, P_j], 1))[:, None]
            ok3 = ((n3 >= 150) & (z3 >= 3) & (r3 >= 1.3 * base["A"]) & (r3 >= 1.1 * parent_rate) & ~bad[None, :]
                   & (np.arange(K)[None, :] != P_i[:, None]) & (np.arange(K)[None, :] != P_j[:, None]))
            bi, kk = np.where(ok3)
            order = np.argsort(-z3[bi, kk])[:CAND_CAP]
            seen = set()
            for o in order:
                key = tuple(sorted((P_i[bi[o]], P_j[bi[o]], kk[o])))
                if key in seen:
                    continue
                seen.add(key)
                cands.append((key, n3[bi[o], kk[o]], h3[bi[o], kk[o]]))
        # confirm on B, exam on C
        tsel = names.index(price_lab[tname]) if tname in price_lab and price_lab[tname] in names else None
        kept = 0
        for p in "BC":
            pass
        for atoms_, nA, hA in cands:
            stats = {}
            for p in "BC":
                m = np.prod(X[p][:, list(atoms_)], axis=1) * V[p]
                n, h = m.sum(), (m * Y[p]).sum()
                stats[p] = (n, h)
            nB, hB = stats["B"]; nC, hC = stats["C"]
            rB, zB = zscore(hB, nB, base["B"])
            rC, _ = zscore(hC, nC, base["C"])
            if not (nB >= 100 and zB >= 2 and rB >= 1.25 * base["B"] and nC >= 20 and rC >= 1.1 * base["C"]):
                continue
            row = {"target": tname, "conditions": len(atoms_),
                   "rule": "  AND  ".join(lab[a][0] for a in atoms_),
                   "kural": "  VE  ".join(lab[a][1] for a in atoms_)}
            for p, n, h in (("A", nA, hA), ("B", nB, hB), ("C", nC, hC)):
                row.update({f"matches_{p}": int(n), f"hits_{p}": int(round(h)), f"hit_{p}": h / max(n, 1) * 100,
                            f"normal_{p}": base[p] * 100})
            if tsel is not None:
                allm = np.prod(np.concatenate([X[p] for p in "ABC"])[:, list(atoms_)], axis=1) > 0
                fo = np.concatenate([F[per == p, tsel] for p in "ABC"])
                oo = np.concatenate([O[per == p, tsel] for p in "ABC"])
                yy = np.concatenate([Y[p] for p in "ABC"])
                okp = allm & ~np.isnan(oo)
                row["nesine_price_says"] = float(np.nanmean(fo[okp]) * 100) if okp.any() else np.nan
                row["return_per_100"] = float(np.mean(yy[okp] * oo[okp] - 1) * 100) if okp.any() else np.nan
            rows.append(row)
            kept += 1
        print(f"{tname:32s} base {base['A'] * 100:5.1f}%  candidates {len(cands):5d}  kept {kept:5d}  "
              f"({time.time() - t0:.0f}s)", flush=True)
    r = pd.DataFrame(rows)
    r["matches_all"] = r[["matches_A", "matches_B", "matches_C"]].sum(axis=1)
    r["hits_all"] = r[["hits_A", "hits_B", "hits_C"]].sum(axis=1)
    r["hit_all"] = r["hits_all"] / r["matches_all"] * 100
    r["normal_all"] = sum(r[f"normal_{p}"] * r[f"matches_{p}"] for p in "ABC") / r["matches_all"]
    r["lift_all"] = r["hit_all"] / r["normal_all"]
    r.to_parquet(CACHE / "rules_deep.parquet")
    return r


if __name__ == "__main__":
    r = run()
    print(r.groupby(["target", "conditions"]).size().unstack(fill_value=0).to_string())
