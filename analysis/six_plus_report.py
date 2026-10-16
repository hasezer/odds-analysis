"""6+ goals deep dive: Excel + chart from the cached studies (six_plus*.py).
Writes output/six_plus.xlsx and output/six_plus_ladder.png.
"""
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import six_plus as sp  # noqa: E402
import six_plus2 as sp2  # noqa: E402
from htft_data import CACHE  # noqa: E402

OUT = Path(__file__).resolve().parent / "output"
BLUE, ORANGE, GRAY, INK, INK2, GRID, SURF = "#2a78d6", "#eb6834", "#a3a29c", "#0b0b0b", "#52514e", "#e6e5e0", "#fcfcfb"


def ladder(D):
    bins = [0, 4.5, 6, 7.5, 9, 11, 13, 16, 20, 1000]
    labs = ["≤ 4.50", "4.50–6", "6–7.50", "7.50–9", "9–11", "11–13", "13–16", "16–20", "> 20"]
    x = D[D["odds6"].notna()].copy()
    x["band"] = pd.cut(x["odds6"], bins, labels=labs)
    rows = []
    for b, g in x.groupby("band", observed=True):
        row = {"6+ odds": b, "matches": len(g), "actual 6+ %": g["y"].mean() * 100,
               "Nesine's chance (cut removed) %": g["p6"].mean() * 100, "break-even %": (1 / g["odds6"]).mean() * 100,
               "return per 100": (g["y"] * g["odds6"] - 1).mean() * 100}
        for p, nm in sp.SEAS.items():
            gg = g[g["per"] == p]
            row[f"actual % {nm}"] = gg["y"].mean() * 100 if len(gg) else np.nan
            row[f"matches {nm}"] = len(gg)
        rows.append(row)
    return pd.DataFrame(rows)


def main():
    D, X, d = sp.data()
    lad = ladder(D)
    prof = pd.read_parquet(CACHE / "six_plus_profile.parquet")
    for c in ("median in 6+ games", "median in other games"):
        prof[c] = np.where(prof["family"] == "odds", np.exp(prof[c]), prof[c])
    top = prof.sort_values("AUC (all)", key=lambda s: (s - .5).abs(), ascending=False)
    k, sc, ht = sp2.kinds(D, X)
    calib = pd.read_parquet(CACHE / "six_plus_calib.parquet")
    ins = pd.read_parquet(CACHE / "six_plus_instruments.parquet")
    rules = pd.read_parquet(CACHE / "six_plus_rules.parquet")
    struct = pd.read_parquet(CACHE / "six_plus_structure.parquet")
    with pd.ExcelWriter(OUT / "six_plus.xlsx") as xw:
        pd.DataFrame({"Read me": [
            "Every finished match with 6+ goals (1,311 of 20,667) compared with all other matches. Our data only.",
            "6+ ladder: hit rate of 6+ by its own odds, vs the chance Nesine's price implies and the break-even rate.",
            "What 6+ games look like: the odds that differ most between 6+ games and other games (medians).",
            "Beyond the price: how well a signal separates 6+ games among matches with the SAME 6+ price "
            "(0.5 = adds nothing). Nothing adds more than ~0.02 consistently.",
            "Rules: 1-2 threshold rules found 2024/25, confirmed 2025/26, graded 2026/27, compared with simply taking "
            "the same number of matches with the cheapest 6+ price.",
            "Which bet: when 6+ is likely, over 3.5 / 1st-half over 1.5 lose far less than the 6+ bet itself."]}).to_excel(
            xw, sheet_name="Read me", index=False)
        lad.round(1).to_excel(xw, sheet_name="6+ ladder", index=False)
        top[["signal", "AUC (all)", "median in 6+ games", "median in other games"]].head(40).round(3).to_excel(
            xw, sheet_name="What 6+ games look like", index=False)
        prof.drop(columns=["base AUC of the 6+ price itself"]).round(3).to_excel(xw, sheet_name="Beyond the price",
                                                                                 index=False)
        struct.round(3).to_excel(xw, sheet_name="Structure signals", index=False)
        k.round(2).reset_index().to_excel(xw, sheet_name="Kinds of 6+ games", index=False)
        sc.reset_index().rename(columns={"index": "score"}).to_excel(xw, sheet_name="6+ scores", index=False)
        ht.reset_index().rename(columns={"index": "1st-half goals"}).to_excel(xw, sheet_name="1st-half goals in 6+",
                                                                             index=False)
        calib.round(1).to_excel(xw, sheet_name="Where Nesine misprices 6+", index=False)
        ins.round(1).to_excel(xw, sheet_name="Which bet to play", index=False)
        rules.head(300).round(1).to_excel(xw, sheet_name="Best 6+ rules", index=False)
        for ws in xw.sheets.values():
            ws.set_column(0, 0, 45); ws.set_column(1, 30, 14)
    fig, ax = plt.subplots(figsize=(11, 5.6), facecolor=SURF)
    ax.set_facecolor(SURF)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(GRID); ax.grid(axis="y", color=GRID); ax.set_axisbelow(True)
    ax.tick_params(colors=INK2, length=0)
    xx = np.arange(len(lad))
    ax.bar(xx - .2, lad["actual 6+ %"], .38, color=BLUE, label="6+ actually happened")
    ax.bar(xx + .2, lad["break-even %"], .38, color=ORANGE, label="needed to break even at those odds")
    ax.plot(xx, lad["Nesine's chance (cut removed) %"], color=INK, lw=1.5, marker="o", ms=5,
            label="Nesine's chance (cut removed)")
    for i, r in lad.iterrows():
        ax.text(i - .2, r["actual 6+ %"] + .5, f"{r['actual 6+ %']:.0f}%", ha="center", fontsize=9, color=INK)
    ax.set_xticks(xx, [f"{b}\n{n:,} m." for b, n in zip(lad["6+ odds"], lad["matches"])], fontsize=9)
    ax.set_xlabel("6+ goals odds (closing)", color=INK2); ax.set_ylabel("% of matches", color=INK2)
    ax.legend(frameon=False, fontsize=10, labelcolor=INK)
    ax.set_title("6+ goals: the cheaper the 6+ odds, the likelier — but it always falls short of break-even",
                 loc="left", fontsize=13, color=INK, fontweight="bold")
    fig.tight_layout()
    fig.savefig(OUT / "six_plus_ladder.png", dpi=150)
    return lad


if __name__ == "__main__":
    print(main().round(1).to_string())
