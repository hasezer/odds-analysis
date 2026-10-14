"""Rule hunt v3 results: Excel tables and charts for the iPad.

Reads cache/rules_v3*.parquet (rules_v3.py, rules_v3_teams.py) and cache/v3_atoms.npz.
Writes output/rules_v3.xlsx and output/v3_*.png.
"""
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import miner_data as mdat  # noqa: E402
import rules_v3_data as v3  # noqa: E402
from htft_data import CACHE  # noqa: E402

OUT = Path(__file__).resolve().parent / "output"
NEW = {"disagree", "form", "last", "context", "margin", "corners"}
P = "ABC"


def load():
    r = pd.read_parquet(CACHE / "rules_v3.parquet")
    r["z_price_all"] = (r["pricehits_all"] - r["price_all"]) / np.sqrt(r["var_all"].clip(lower=1e-6))
    for p in P:
        r[f"z_price_{p}"] = (r[f"pricehits_{p}"] - r[f"price_{p}"]) / np.sqrt(r[f"var_{p}"].clip(lower=1e-6))
    fams = r["families"].str.split(",")
    r["uses_new"] = fams.map(lambda f: bool(NEW & set(f)))
    return r


def diverse(g, X, k=5, jac=.5):
    """Greedy: best first, skip a rule whose matches overlap a chosen rule's by more than jac (Jaccard)."""
    chosen, masks = [], []
    for idx, row in g.iterrows():
        m = X[:, [int(a) for a in row["atoms"].split(",")]].all(1)
        if any((m & c).sum() / max((m | c).sum(), 1) > jac for c in masks):
            continue
        chosen.append(idx); masks.append(m)
        if len(chosen) == k:
            break
    return g.loc[chosen]


def table(df, price=True):
    df = df.copy()
    for p in ("all", "C"):           # hit rate needed to break even at the odds actually paid (≈ hit / (1 + return))
        df[f"breakeven_{p}"] = df[f"hit_when_priced_{p}"] / (1 + df[f"return_per_100_{p}"] / 100)
    cols = {"target": "Bet", "target_tr": "Bahis", "conditions": "Conditions", "rule": "Rule (all conditions true)",
            "kural": "Kural", "families": "Kinds of info", "matches_all": "Past matches", "hit_all": "Hit %",
            "normal_all": "Normal %", "breakeven_all": "Hit % needed to break even", "matches_C": "Matches 2026/27",
            "hit_C": "Hit % 2026/27", "normal_C": "Normal % 2026/27", "breakeven_C": "Break-even % 2026/27",
            "hit_A": "Hit % 2024/25", "hit_B": "Hit % 2025/26", "return_per_100_all": "Return per 100 staked"}
    if not price:
        cols = {k: v for k, v in cols.items() if "breakeven" not in k and "return" not in k}
    t = df[list(cols)].rename(columns=cols)
    return t.round(1)


def main():
    r = load()
    luck = pd.read_parquet(CACHE / "rules_v3_luck.parquet")
    a = v3.build()
    X = a["X"]
    OUT.mkdir(exist_ok=True)
    sheets = {}

    # ---- luck check per bet
    lk = luck.copy()
    lk["hit_real_vs_luck"] = lk["kept_hit"] / lk["luck_hit"].clip(lower=1)
    sheets["Luck check"] = lk.rename(columns={
        "target": "Bet", "candidates": "Rules tried (after period A)", "kept_hit": "Hit test: rules kept",
        "luck_hit": "Hit test: kept with shuffled results", "kept_price": "Beat-price test: rules kept",
        "luck_price": "Beat-price test: kept with shuffled results"}).drop(columns=["target_key", "hit_real_vs_luck"])

    # ---- best hit-rate rules per bet (diverse), and safe bets
    h = r[r["tracks"].str.contains("hit") & (r["matches_all"] >= 300) & (r["matches_C"] >= 30)]
    best = []
    for tk, g in h.groupby("target_key"):
        g = g.sort_values(["hit_all", "matches_all"], ascending=False)
        best.append(diverse(g, X, k=5))
    best = pd.concat(best)
    best["gain"] = best["hit_all"] - best["normal_all"]
    best = best.sort_values(["target", "hit_all"], ascending=[True, False])
    sheets["Best rules per bet"] = table(best)

    safe = h[(h["hit_all"] >= 80) & (h["hit_C"] >= 80) & (h["hit_A"] >= 78) & (h["hit_B"] >= 78)]
    sb = []
    for tk, g in safe.groupby("target_key"):
        sb.append(diverse(g.sort_values(["hit_all", "matches_all"], ascending=False), X, k=3))
    safe = pd.concat(sb).sort_values("hit_all", ascending=False) if sb else safe
    sheets["80%+ rules"] = table(safe)

    # ---- the new information: does it beat the old price-only rules?
    cmp_ = []
    for tk, g in h.groupby("target_key"):
        old, new = g[~g["uses_new"]], g[g["uses_new"]]
        row = {"Bet": g["target"].iloc[0], "Normal %": g["normal_all"].iloc[0]}
        for nm, x in (("price-only", old), ("with new info", new)):
            x = x[x["matches_all"] >= 500].sort_values("hit_all", ascending=False)
            row[f"Best hit % ({nm}, 500+ matches)"] = x["hit_all"].iloc[0] if len(x) else np.nan
            row[f"Its hit % in 2026/27 ({nm})"] = x["hit_C"].iloc[0] if len(x) else np.nan
        cmp_.append(row)
    cmp_ = pd.DataFrame(cmp_)
    sheets["New info vs price-only"] = cmp_.round(1)
    fam_counts = h.assign(f=h["families"].str.split(",")).explode("f")["f"].value_counts()

    # ---- beat-the-price rules
    pr = r[r["tracks"].str.contains("price")].copy()
    pr = pr[pr["priced_all"] >= 200]
    pb = []
    for tk, g in pr.groupby("target_key"):
        pb.append(diverse(g.sort_values("z_price_all", ascending=False), X, k=5))
    pb = pd.concat(pb).sort_values("z_price_all", ascending=False) if pb else pr
    t = table(pb)
    t.insert(9, "Hit % when priced", pb["hit_when_priced_all"].round(1).to_numpy())
    t["Beat-price z (all)"] = pb["z_price_all"].round(2).to_numpy()
    for p, nm in zip(P, ("2024/25", "2025/26", "2026/27")):
        t[f"Return per 100, {nm}"] = pb[f"return_per_100_{p}"].round(1).to_numpy()
    sheets["Beats Nesine's price"] = t

    # ---- rules that made money in every period (any track), at least 100 priced matches in A and B, 30 in C
    mm = r[(r["priced_A"] >= 100) & (r["priced_B"] >= 100) & (r["priced_C"] >= 30)
           & (r["return_per_100_A"] > 0) & (r["return_per_100_B"] > 0) & (r["return_per_100_C"] > 0)].copy()
    mm["worst_period"] = mm[[f"return_per_100_{p}" for p in P]].min(axis=1)
    mb = []
    for tk, g in mm.groupby("target_key"):
        mb.append(diverse(g.sort_values("worst_period", ascending=False), X, k=5))
    mm = pd.concat(mb).sort_values("worst_period", ascending=False) if mb else mm
    t = table(mm)
    for p, nm in zip(P, ("2024/25", "2025/26", "2026/27")):
        t[f"Return per 100, {nm}"] = mm[f"return_per_100_{p}"].round(1).to_numpy()
    sheets["Made money every period"] = t
    money_every = mm

    # ---- teams and leagues
    tm = pd.read_parquet(CACHE / "rules_v3_teams.parquet")
    ts = pd.read_parquet(CACHE / "rules_v3_teams_summary.parquet")
    if len(tm):
        tm = tm.sort_values("z_A", ascending=False)
        tm["held_in_2026/27"] = np.where(tm["n_C"] >= 5, tm["hit_C"] > tm["price_C"], np.nan)
        sheets["Teams beating price"] = tm.round(2)
    lgs = pd.read_parquet(CACHE / "rules_v3_leagues.parquet")
    lgl = pd.read_parquet(CACHE / "rules_v3_leagues_luck.parquet")
    sheets["League x bet winners"] = lgs.round(1)
    sheets["League scan luck"] = pd.DataFrame({"Real data: combinations found": [len(lgs)],
                                               "Shuffled leagues: average found": [lgl["found"].mean()],
                                               "Shuffled leagues: most found": [lgl["found"].max()]})
    vt = pd.read_parquet(CACHE / "rules_v3_vote.parquet")
    vt = vt[vt["priced_C"] > 0]
    order = ["no rule", "1–4 rules", "5–19 rules", "20–99 rules", "100+ rules"]
    stack = []
    for (tr, b), d in vt.groupby(["track", "bucket"]):
        stack.append({"Rules picked by": {"hit": "hit-rate test (2024/25 + 2025/26)",
                                          "price": "beat-price test (2024/25 + 2025/26)",
                                          "money": "made money in 2024/25 AND 2025/26"}[tr],
                      "How many rules agreed": b, "_o": order.index(b), "Bets in 2026/27": int(d["priced_C"].sum()),
                      "Hit % 2026/27": np.average(d["hit_C"], weights=d["matches_C"]),
                      "Return per 100 staked, 2026/27": np.average(d["return_per_100_C"], weights=d["priced_C"])})
    sheets["Rule stacking 2026-27"] = pd.DataFrame(stack).sort_values(["Rules picked by", "_o"]).drop(
        columns="_o").round(1)
    sheets["Teams luck check"] = ts.groupby("group")[["pairs", "beat_both", "beat_both_by_luck"]].sum().reset_index()

    with pd.ExcelWriter(OUT / "rules_v3.xlsx") as xw:
        intro = pd.DataFrame({"Read me": [
            "Rule hunt v3: ~160 bet types x 4,298 conditions (odds + six new kinds of information).",
            "Periods: 2024/25 + 2024 = find, 2025/26 + 2025 = confirm, 2026/27 + 2026 so far = exam.",
            "Hit %: how often the bet won when the rule's conditions were all true. Normal %: all matches.",
            "Hit % needed to break even: at the odds Nesine actually paid on those matches. Above it = profit.",
            "Luck check: how many rules passed with the results shuffled (pure chance) next to the real count.",
        ]})
        intro.to_excel(xw, sheet_name="Read me", index=False)
        for name, df in sheets.items():
            df.to_excel(xw, sheet_name=name[:31], index=False)
            ws = xw.sheets[name[:31]]
            for i, c in enumerate(df.columns):
                w = min(max(len(str(c)), *(len(str(v)) for v in df[c].head(200))) + 2, 70) if len(df) else 15
                ws.set_column(i, i, w)
    return r, luck, best, safe, pb, cmp_, fam_counts, tm, ts, money_every


if __name__ == "__main__":
    res = main()
    r, luck, best, safe, pb, cmp_, fam, tm, ts, money = res
    print(luck[["kept_hit", "luck_hit", "kept_price", "luck_price"]].sum())
    print(fam)
    print(len(money), money["target"].value_counts().head(20).to_string())
