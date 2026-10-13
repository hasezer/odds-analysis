"""Targeted rule book: HT/FT (all 9), both teams score, both teams score in BOTH halves (+ in 1st / 2nd half).

Targets come straight from the scores, so every period can be used.
Conditions on the match's closing prices (162 common selection types; the target's own market is never used):
  range  odds of one selection inside a price range (10 ranges per selection, cut at period-A deciles)
         e.g. "Toplam Gol Aralığı 2-3 odds 1.80-1.95"
  pair   two odds equal within 0.10, or one unusually cheaper than another (as in rule_miner.py)
  combo  two price ranges at the same time (every pair of ranges of two different selections)
Gates (each period A = 2024/25 + 2024, B = 2025/26 + 2025, C = 2026/27 + 2026):
  strong    matches >= 200 / 200 / 60, z >= 3 / 3 / 1.5 and lift >= 1.25 in every period
  moderate  (only for targets with < 100 strong rules) same matches, z >= 2.5 / 2.5 / 1.0, lift >= 1.15
Writes cache/rules_targets.parquet; rules_targets_study() writes output/rules_htft_btts.xlsx.
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

NB = 10


def tr_labels(names):
    f = load._read("analysis_flat", seasons=["2025-26", "2024-25"])
    x = f[["market_key", "line", "selection_key", "market_name_tr", "selection_name_tr"]].drop_duplicates(
        ["market_key", "line", "selection_key"])
    d = {}
    for r in x.itertuples(index=False):
        line = "" if pd.isna(r.line) else f"{r.line:g}"
        lab = f"{r.market_key}|{line}|{r.selection_key}"
        ln = line.replace(".", ",")
        name = r.market_name_tr if (not ln or ln in r.market_name_tr) else f"{r.market_name_tr} {ln}"
        d[lab] = f"{name}: {r.selection_name_tr}"
    return [d.get(n, n) for n in names]


def targets(match_ids):
    m = load.matches().set_index("match_id").loc[match_ids]
    h1, a1, fh, fa = m["ht_home"], m["ht_away"], m["ft_home"], m["ft_away"]
    h2, a2 = fh - h1, fa - a1
    res = lambda h, a: np.where(h > a, "1", np.where(h == a, "X", "2"))
    ht, ft = res(h1, a1), res(fh, fa)
    ok = h1.notna().to_numpy()
    T = {}
    for a in "1X2":
        for b in "1X2":
            T[f"HT/FT {a}/{b}"] = ((ht == a) & (ft == b)).astype(float)
    T["Both teams score: yes (KG Var)"] = ((fh > 0) & (fa > 0)).astype(float).to_numpy()
    T["Both teams score in BOTH halves"] = ((h1 > 0) & (a1 > 0) & (h2 > 0) & (a2 > 0)).astype(float).to_numpy()
    T["Both teams score in 1st half"] = ((h1 > 0) & (a1 > 0)).astype(float).to_numpy()
    T["Both teams score in 2nd half"] = ((h2 > 0) & (a2 > 0)).astype(float).to_numpy()
    for k in T:
        T[k] = np.where(ok, T[k], np.nan)
    own = {k: ("HT_FT" if k.startswith("HT/FT") else "BTTS" if k.startswith("Both teams score: yes")
               else "HT_2H_BTTS") for k in T}
    own["Both teams score in 1st half"] = "HT_BTTS"
    own["Both teams score in 2nd half"] = "2H_BTTS"
    return T, own


def run(lift_min=1.25, zmins=(3, 3, 1.5), only=None, tier="strong"):
    z = mdat.build()
    O, per, names = z["O"], z["per"], z["names"]
    S = len(names)
    mk = np.array([n.split("|")[0] for n in names])
    en = [nice(n) for n in names]
    trl = tr_labels(names)
    T, own = targets(z["match_ids"])

    # ---- range conditions
    rng, rlab, rsel = [], [], []
    A = per == "A"
    for i in range(S):
        col = O[A, i]
        if np.isnan(col).mean() > .5:
            continue
        edges = np.unique(np.round(np.nanquantile(col, np.linspace(0, 1, NB + 1)), 2))
        edges[0], edges[-1] = 0, 1e9
        for k in range(len(edges) - 1):
            lo, hi = edges[k], edges[k + 1]
            rng.append((i, lo, hi)); rsel.append(i)
            txt = (f"≤ {hi:.2f}" if lo == 0 else f"> {lo:.2f}" if hi == 1e9 else f"{lo:.2f}–{hi:.2f}")
            rlab.append((f"{en[i]} odds {txt}", f"{trl[i]} oranı {txt}"))
    rsel = np.array(rsel)

    # ---- pair conditions (same as rule_miner.py)
    pairs, plab, pa, pb = [], [], [], []
    for i in range(S):
        for j in range(i + 1, S):
            if mk[i] == mk[j]:
                continue
            a, b = O[A, i], O[A, j]
            ok = ~np.isnan(a) & ~np.isnan(b)
            if ok.sum() < 1000:
                continue
            if (np.abs(a[ok] - b[ok]) <= .10).sum() >= 200:
                pairs.append(("eq", i, j)); pa.append(i); pb.append(j)
                plab.append((f"{en[i]} ≈ {en[j]} (within 0.10)", f"{trl[i]} ≈ {trl[j]} (±0,10)"))
            share = (a[ok] < b[ok]).mean()
            if .005 < share < .35 or .005 < 1 - share < .35:
                x, y = (i, j) if share < .35 else (j, i)
                pairs.append(("lt", x, y)); pa.append(x); pb.append(y)
                plab.append((f"{en[x]} cheaper than {en[y]}", f"{trl[x]} oranı < {trl[y]} oranı"))
    pa, pb = np.array(pa), np.array(pb)
    print(f"{len(rng)} price ranges, {len(pairs)} pair conditions, {len(rng) ** 2 // 2:,} range combos", flush=True)

    rows = []
    stats = {}
    for p in "ABC":
        ix = per == p
        o = O[ix]
        R = np.stack([(o[:, i] > lo) & (o[:, i] <= hi) for i, lo, hi in rng], 1).astype(np.float32)
        P = np.stack([(np.abs(o[:, i] - o[:, j]) <= .10) if k == "eq" else (o[:, i] < o[:, j])
                      for k, i, j in pairs], 1).astype(np.float32)
        stats[p] = dict(R=R, P=P, NR=R.sum(0), NP=P.sum(0), N2=R.T @ R)
    for tname, tv in T.items():
        if only is not None and tname not in only:
            continue
        t0 = time.time()
        own_mk = own[tname]
        bad_r = mk[rsel] == own_mk
        bad_p = (mk[pa] == own_mk) | (mk[pb] == own_mk)
        res = {}
        for p in "ABC":
            ix = per == p
            y = tv[ix]
            okk = ~np.isnan(y)
            y0 = np.nan_to_num(y).astype(np.float32)
            s = stats[p]
            base = y0[okk].mean()
            Ry = s["R"] * y0[:, None]
            res[p] = dict(base=base, hR=Ry.sum(0), hP=(s["P"] * y0[:, None]).sum(0), h2=Ry.T @ s["R"])

        def gate(n, h, p, zmin):
            b = res[p]["base"]
            rate = h / np.maximum(n, 1)
            zz = (rate - b) / np.sqrt(b * (1 - b) / np.maximum(n, 1))
            return rate, zz

        def keep(nA, hA, nB, hB, nC, hC):
            out = np.ones_like(nA, bool)
            for n, h, p, nmin, zmin in ((nA, hA, "A", 200, zmins[0]), (nB, hB, "B", 200, zmins[1]),
                                        (nC, hC, "C", 60, zmins[2])):
                rate, zz = gate(n, h, p, zmin)
                out &= (n >= nmin) & (zz >= zmin) & (rate >= lift_min * res[p]["base"])
            return out

        def add(kind, en_txt, tr_txt, ns, hs):
            row = {"target": tname, "tier": tier, "kind": kind, "rule": en_txt, "rule_tr": tr_txt}
            for p, n, h in zip("ABC", ns, hs):
                row.update({f"matches_{p}": int(n), f"hit_{p}": h / n * 100, f"normal_{p}": res[p]["base"] * 100})
            rows.append(row)

        g = lambda key, p: stats[p][key]
        kR = keep(g("NR", "A"), res["A"]["hR"], g("NR", "B"), res["B"]["hR"], g("NR", "C"), res["C"]["hR"]) & ~bad_r
        for k in np.where(kR)[0]:
            add("price range", *rlab[k], [g("NR", p)[k] for p in "ABC"], [res[p]["hR"][k] for p in "ABC"])
        kP = keep(g("NP", "A"), res["A"]["hP"], g("NP", "B"), res["B"]["hP"], g("NP", "C"), res["C"]["hP"]) & ~bad_p
        for k in np.where(kP)[0]:
            add("pair", *plab[k], [g("NP", p)[k] for p in "ABC"], [res[p]["hP"][k] for p in "ABC"])
        kC = keep(g("N2", "A"), res["A"]["h2"], g("N2", "B"), res["B"]["h2"], g("N2", "C"), res["C"]["h2"])
        kC = np.triu(kC, 1) & (rsel[:, None] != rsel[None, :]) & ~bad_r[:, None] & ~bad_r[None, :]
        for a_, b_ in zip(*np.where(kC)):
            add("two price ranges", f"{rlab[a_][0]} AND {rlab[b_][0]}", f"{rlab[a_][1]} VE {rlab[b_][1]}",
                [g("N2", p)[a_, b_] for p in "ABC"], [res[p]["h2"][a_, b_] for p in "ABC"])
        print(f"{tname:35s} kept so far {len(rows):>8,}  ({time.time() - t0:.0f}s)", flush=True)
    r = pd.DataFrame(rows)
    if r.empty:
        return r
    r["matches_all"] = r[["matches_A", "matches_B", "matches_C"]].sum(axis=1)
    for k in ("hit", "normal"):
        r[f"{k}_all"] = sum(r[f"{k}_{p}"] * r[f"matches_{p}"] for p in "ABC") / r["matches_all"]
    r["lift_all"] = r["hit_all"] / r["normal_all"]
    r["min_hit"] = r[["hit_A", "hit_B", "hit_C"]].min(axis=1)
    return r


def run_all():
    strong = run()
    counts = strong["target"].value_counts()
    T, _ = targets(mdat.build()["match_ids"])
    weak = [t for t in T if counts.get(t, 0) < 100]
    moderate = run(lift_min=1.15, zmins=(2.5, 2.5, 1.0), only=weak, tier="moderate")
    moderate = moderate.merge(strong[["target", "rule"]], on=["target", "rule"], how="left", indicator=True)
    moderate = moderate[moderate["_merge"] == "left_only"].drop(columns="_merge")
    r = pd.concat([strong, moderate], ignore_index=True)
    r.to_parquet(CACHE / "rules_targets.parquet")
    return r


if __name__ == "__main__":
    r = run_all()
    print(r.groupby(["target", "tier"]).size().unstack(fill_value=0).to_string())


def example_table():
    """The user's example: Total goals 2-3 price range vs under 2.5 (and 2-3 goals)."""
    z = mdat.build()
    names = list(z["names"])
    m = load.matches().set_index("match_id").loc[z["match_ids"]]
    tot = (m["ft_home"] + m["ft_away"]).to_numpy()
    gr = z["O"][:, names.index("GOAL_RANGE||2-3")]
    rows = []
    for lo, hi in [(0, 1.75), (1.75, 1.80), (1.80, 1.90), (1.90, 2.00), (2.00, 2.20), (2.20, 99)]:
        row = {"Toplam Gol Aralığı 2-3 odds": f"{lo:.2f}–{hi:.2f}" if hi < 99 else f"> {lo:.2f}"}
        for p, lab in zip("ABC", ("24/25+2024", "25/26+2025", "26/27+2026")):
            k = (gr > lo) & (gr <= hi) & (z["per"] == p)
            row[f"Matches {lab}"] = int(k.sum())
            row[f"Under 2.5 % {lab}"] = round(float(np.mean(tot[k] < 2.5) * 100), 1) if k.sum() else None
        k = (gr > lo) & (gr <= hi)
        row["Under 2.5 % all"] = round(float(np.mean(tot[k] < 2.5) * 100), 1)
        row["2-3 goals % all"] = round(float(np.mean((tot[k] >= 2) & (tot[k] <= 3)) * 100), 1)
        rows.append(row)
    rows.append({"Toplam Gol Aralığı 2-3 odds": "ALL MATCHES", "Under 2.5 % all": round(float(np.mean(tot < 2.5) * 100), 1),
                 "2-3 goals % all": round(float(np.mean((tot >= 2) & (tot <= 3)) * 100), 1)})
    return pd.DataFrame(rows)


def study():
    from first_look import OUT
    r = pd.read_parquet(CACHE / "rules_targets.parquet")
    order = [f"HT/FT {a}/{b}" for a in "1X2" for b in "1X2"] + [
        "Both teams score: yes (KG Var)", "Both teams score in BOTH halves", "Both teams score in 1st half",
        "Both teams score in 2nd half"]
    short = {t: t.replace("Both teams score", "BTTS").replace(": yes (KG Var)", " yes").replace("/", "-")
             for t in order}
    howto = pd.DataFrame({"How to read": [
        "One sheet per bet. Each row is a rule: WHEN the closing odds look like the rule, the bet lands more often than "
        "its normal rate. 'Kural' is the same rule with Nesine's Turkish market names.",
        "Every rule held in ALL three periods separately: 24/25+2024, 25/26+2025 and 26/27+2026 so far.",
        "Tier 'strong': at least 1.25x the normal rate in every period with strong statistical evidence. Tier "
        "'moderate': at least 1.15x (used only for bets where few strong rules exist: BTTS yes, HT/FT 1/2, 2/1, 2/X).",
        "Rule types: 'price range' = one odds inside a range; 'two price ranges' = two odds ranges at the same time "
        "(AND / VE); 'pair' = two odds equal within 0.10 or one cheaper than the other.",
        "The bet's own market is never used in its rules (no 'BTTS yes odds low -> BTTS yes').",
        "HT/FT 1/X (1/0) has no rule: nothing in the price list lifts it consistently.",
        "These are hit-rate rules. Nesine's price for the bet usually already reflects them, so flat betting still "
        "loses money on average.",
        "Sheet 'Your example' answers: Total goals 2-3 odds 1.80-2.00 -> under 2.5? (It is LESS likely, not more.)",
    ]})
    summary = []
    sheets = {"How to read": howto}
    for t in order:
        d = r[r["target"] == t].sort_values(["tier", "hit_all"], ascending=[False, False])
        d = d.sort_values("hit_all", ascending=False)
        if len(d):
            summary.append({"Bet": t, "Normally %": round(d["normal_all"].iloc[0], 1), "Rules found": len(d),
                            "Strong": int((d["tier"] == "strong").sum()), "Best hit all %": round(d["hit_all"].max(), 1),
                            "Best rule": d["rule"].iloc[0]})
        else:
            summary.append({"Bet": t, "Rules found": 0, "Best rule": "none held in all three periods"})
        sheets[short[t][:31]] = pd.DataFrame({
            "Rule": d["rule"], "Kural": d["rule_tr"], "Tier": d["tier"], "Type": d["kind"],
            "Matches": d["matches_all"].astype(int), "Hit 24/25+2024 %": d["hit_A"].round(1),
            "Hit 25/26+2025 %": d["hit_B"].round(1), "Hit 26/27+2026 %": d["hit_C"].round(1),
            "Hit all %": d["hit_all"].round(1), "Normally %": d["normal_all"].round(1),
            "Lift (x)": d["lift_all"].round(2)}).head(3000)
    sheets = {"How to read": howto, "Summary": pd.DataFrame(summary), "Your example": example_table(),
              **{k: v for k, v in sheets.items() if k != "How to read"}}
    with pd.ExcelWriter(OUT / "rules_htft_btts.xlsx", engine="openpyxl") as xw:
        for name, df in sheets.items():
            df.to_excel(xw, sheet_name=name[:31], index=False)
            ws = xw.sheets[name[:31]]
            ws.freeze_panes = "A2"
            if name not in ("How to read",):
                ws.auto_filter.ref = ws.dimensions
            for col in ws.columns:
                ws.column_dimensions[col[0].column_letter].width = max(
                    10, min(80, max(len(str(c.value if c.value is not None else "")) for c in col) + 2))
            if name == "How to read":
                ws.column_dimensions["A"].width = 150
    return sheets
