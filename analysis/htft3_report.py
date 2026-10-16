"""HT/FT study 3 (the six changing results): Excel + charts from the cached steps
(htft3_signs.py, htft3_rules.py, htft3_ml.py, htft3_extra.py). Writes output/htft3.xlsx and output/htft3_*.png.
"""
from pathlib import Path
import pickle
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import htft3_data as h3  # noqa: E402
from htft_data import CACHE  # noqa: E402

OUT = Path(__file__).resolve().parent / "output"
SURF, INK, INK2, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
BLUE = "#2a78d6"
SEQ = LinearSegmentedColormap.from_list("blue", ["#f0efec", "#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf",
                                                 "#184f95"])
SEAS = {"A": "2024/25", "B": "2025/26", "C": "2026/27"}
ORDER = ["X/1", "X/2", "1/2", "2/1", "1/X", "2/X"]
NAME = {"1/X": "1/X  home ahead at HT, draw", "2/X": "2/X  away ahead at HT, draw",
        "X/1": "X/1  level at HT, home wins", "X/2": "X/2  level at HT, away wins",
        "1/2": "1/2  home ahead at HT, away wins", "2/1": "2/1  away ahead at HT, home wins"}


def ladder(d):
    rows = []
    for lab in ORDER:
        y = h3.TARGETS[lab]
        o = d[f"o_{lab}"]
        qs = np.unique(np.round(np.nanquantile(o[d["per"] == "A"], [0, .05, .1, .2, .35, .5, .75, 1]), 2))
        qs[0], qs[-1] = 0, 1000
        b = pd.cut(o, qs)
        x = d.assign(b=b)
        for iv, g in x.groupby("b", observed=True):
            r = {"result": lab, "HT/FT odds": (f"up to {iv.right:.2f}" if iv.left == 0 else
                                              (f"over {iv.left:.2f}" if iv.right >= 1000 else
                                               f"{iv.left:.2f}-{iv.right:.2f}")),
                 "matches": len(g), "hit % (all seasons)": g[y].mean() * 100,
                 "break-even % (1/odds)": (1 / g[f"o_{lab}"]).mean() * 100}
            for k, nm in SEAS.items():
                gg = g[g["per"] == k]
                r[f"hit % {nm}"] = gg[y].mean() * 100 if len(gg) else np.nan
                r[f"matches {nm}"] = len(gg)
            rows.append(r)
    return pd.DataFrame(rows)


def summary(d, S, R, M, X):
    """One row per result: normal rate and each technique's top-10% hit rate (2025/26 and 2026/27)."""
    rows = []
    for lab in ORDER:
        y = h3.TARGETS[lab]
        nB = d.loc[d["per"] == "B", y].mean() * 100
        nC = d.loc[d["per"] == "C", y].mean() * 100

        def add(tech, b, c, note=""):
            rows.append({"result": lab, "technique": tech, "hit % 2025/26": b, "hit % 2026/27": c,
                         "normal % 2025/26": nB, "normal % 2026/27": nC,
                         "x normal (average)": np.nanmean([b / nB, c / nC]), "note": note})
        s = S[(S["result"] == lab)].set_index("sign")
        own = s.loc[f"p_{lab}"]
        add("its own HT/FT odds (lowest 10%)", own["top 10% hit % 2025/26"], own["top 10% hit % 2026/27"],
            "cut-off set on 2024/25")
        q = s.loc[f"q_{lab}"]
        add("HT/FT chance from Nesine's other markets (top 10%)", q["top 10% hit % 2025/26"],
            q["top 10% hit % 2026/27"])
        cand = s[~s.index.isin([f"p_{lab}", f"o_{lab}", f"q_{lab}"])]
        best = cand.sort_values("top 10% hit % 2024/25", ascending=False).iloc[0]
        add(f"best other single sign on 2024/25: {best['what']} ({best['direction']})",
            best["top 10% hit % 2025/26"], best["top 10% hit % 2026/27"], "chosen on 2024/25 only")
        r = R[(R["result"] == lab) & (R["pool"] == "scan-ready") & R["confirmed"]]
        if len(r):
            rb = r.iloc[0]          # search order = best on 2024/25 (2025/26 only used as a pass / fail gate)
            add(f"best 2-condition rule: {rb['rule']}", rb["hit % 2025/26"], rb["hit % 2026/27"],
                f"{int(rb['matches 2025/26'])} / {int(rb['matches 2026/27'])} matches")
        else:
            add("2-condition rules", np.nan, np.nan, "none held in 2025/26")
        for score in ("boosted trees (all signs)", "logistic (25 signs)"):
            mb = M[(M["result"] == lab) & (M["score"] == score) & (M["trained on"] == "2024/25")]
            add(f"machine learning: {score}", mb.loc[mb["tested on"] == "2025/26", "top 10% hit %"].iloc[0],
                mb.loc[mb["tested on"] == "2026/27", "top 10% hit %"].iloc[0], "trained on 2024/25")
        sc = X["scores"]
        for pat, tech in (("pair index", "team habits: both teams' comeback / blown-lead record (last 20)"),):
            t = sc[(sc["result"] == lab) & sc["score"].str.startswith(pat) & sc["score"].str.contains("20")]
            if len(t):
                add(tech, t["top 10% hit % 2025/26"].iloc[0], t["top 10% hit % 2026/27"].iloc[0])
        lg = s[s.index.str.startswith("lg_y_")]
        lgb = lg.sort_values("top 10% hit % 2024/25", ascending=False).iloc[0]
        add("league history (league's recent extra results)", lgb["top 10% hit % 2025/26"],
            lgb["top 10% hit % 2026/27"], lgb["what"])
        cal = s[s.index.isin(["kick_hour_tr", "weekday", "season_day", "home_rest_days", "away_rest_days"])]
        cb = cal.sort_values("top 10% hit % 2024/25", ascending=False).iloc[0]
        add("calendar / rest days", cb["top 10% hit % 2025/26"], cb["top 10% hit % 2026/27"], cb["what"])
    return pd.DataFrame(rows)


def style(ax):
    ax.set_facecolor(SURF)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(MUTED)
    ax.tick_params(colors=INK2, labelsize=8)
    ax.grid(axis="y", color=GRID, lw=.8)
    ax.set_axisbelow(True)


def main():
    d = h3.build()
    S = pd.read_parquet(CACHE / "htft3_signs.parquet")
    R = pd.read_parquet(CACHE / "htft3_rules.parquet")
    L = pd.read_parquet(CACHE / "htft3_rules_luck.parquet")
    M = pd.read_parquet(CACHE / "htft3_ml.parquet")
    I = pd.read_parquet(CACHE / "htft3_ml_importance.parquet")
    X = pickle.load(open(CACHE / "htft3_extra.pkl", "rb"))
    lad = ladder(d)
    summ = summary(d, S, R, M, X)

    # 1) odds ladders
    fig, axes = plt.subplots(2, 3, figsize=(15, 8.5))
    fig.patch.set_facecolor(SURF)
    for ax, lab in zip(axes.flat, ORDER):
        style(ax)
        g = lad[lad["result"] == lab]
        ax.bar(range(len(g)), g["hit % (all seasons)"], color=BLUE, width=.72)
        normal = d[h3.TARGETS[lab]].mean() * 100
        ax.axhline(normal, color=INK2, lw=1)
        ax.text(len(g) - .5, normal, f" normal {normal:.1f}%", color=INK2, fontsize=8, va="bottom", ha="right")
        for i, v in enumerate(g["hit % (all seasons)"]):
            ax.text(i, v, f"{v:.1f}%", ha="center", va="bottom", fontsize=8, color=INK)
        ax.set_xticks(range(len(g)), [s.replace("up to ", "≤ ").replace("over ", "> ") for s in g["HT/FT odds"]],
                      rotation=30, ha="right")
        ax.set_title(NAME[lab], color=INK, fontsize=11, loc="left")
        ax.set_ylim(0, max(g["hit % (all seasons)"].max() * 1.25, normal * 1.6))
    fig.supxlabel("Nesine's HT/FT odds for that result (lowest odds on the left)", color=INK2)
    fig.suptitle("The result's own odds are the best sign: how often each result happened, by its HT/FT odds "
                 "(2024–2026)", color=INK, fontsize=13, x=.01, ha="left")
    fig.tight_layout(rect=(0, 0, 1, .96))
    fig.savefig(OUT / "htft3_1_ladders.png", dpi=150, facecolor=SURF)
    plt.close(fig)

    # 2) what works: x normal by technique and result
    tech_order = ["its own HT/FT odds (lowest 10%)", "HT/FT chance from Nesine's other markets (top 10%)",
                  "best other single sign", "best 2-condition rule", "machine learning: boosted trees (all signs)",
                  "machine learning: logistic (25 signs)", "team habits", "league history", "calendar / rest days"]
    short = {"its own HT/FT odds (lowest 10%)": "its own HT/FT odds (lowest 10%)",
             "HT/FT chance from Nesine's other markets (top 10%)": "price rebuilt from the other markets",
             "best other single sign": "best other single sign",
             "best 2-condition rule": "best 2-condition rule (top 300)",
             "machine learning: boosted trees (all signs)": "machine learning: boosted trees",
             "machine learning: logistic (25 signs)": "machine learning: logistic",
             "team habits": "team comeback / blown-lead habits",
             "league history": "league history", "calendar / rest days": "calendar, kick-off time, rest days"}
    Mx = np.full((len(tech_order), len(ORDER)), np.nan)
    for j, lab in enumerate(ORDER):
        g = summ[summ["result"] == lab]
        for i, t in enumerate(tech_order):
            row = g[g["technique"].str.startswith(t)]
            if len(row):
                Mx[i, j] = row["x normal (average)"].iloc[0]
    fig, ax = plt.subplots(figsize=(12, 6.2))
    fig.patch.set_facecolor(SURF)
    norm = plt.Normalize(0.8, 2.2)
    ax.imshow(Mx, cmap=SEQ, norm=norm, aspect="auto")
    for i in range(Mx.shape[0]):
        for j in range(Mx.shape[1]):
            v = Mx[i, j]
            if np.isfinite(v):
                rgba = SEQ(norm(v))
                lum = 0.2126 * rgba[0] + 0.7152 * rgba[1] + 0.0722 * rgba[2]
                ax.text(j, i, f"{v:.2f}x", ha="center", va="center", fontsize=10,
                        color="white" if lum < 0.5 else INK)
            else:
                ax.text(j, i, "none held", ha="center", va="center", fontsize=8, color=MUTED)
    ax.set_xticks(range(len(ORDER)), [NAME[o].split("  ")[0] for o in ORDER], color=INK2, fontsize=11)
    ax.set_yticks(range(len(tech_order)), [short[t] for t in tech_order], color=INK2)
    ax.tick_params(length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_xticks(np.arange(-.5, len(ORDER)), minor=True)
    ax.set_yticks(np.arange(-.5, len(tech_order)), minor=True)
    ax.grid(which="minor", color=SURF, lw=2)
    ax.tick_params(which="minor", length=0)
    ax.set_title("How much each technique raises the hit rate (x normal), measured on 2025/26 and 2026/27 only\n"
                 "1.00x = no better than picking at random; everything chosen on 2024/25", color=INK, fontsize=12,
                 loc="left")
    fig.tight_layout()
    fig.savefig(OUT / "htft3_2_what_works.png", dpi=150, facecolor=SURF)
    plt.close(fig)

    # Excel
    top_signs = []
    for lab in ORDER + ["X/1 or X/2", "1/X or 2/X", "1/2 or 2/1"]:
        g = S[S["result"] == lab].copy()
        g = g[g["top 10% matches 2025/26"] >= 200]
        g["x normal 2025/26"] = g["top 10% hit % 2025/26"] / g["normal % 2025/26"]
        g["x normal 2026/27"] = g["top 10% hit % 2026/27"] / g["normal % 2026/27"]
        top_signs.append(g.sort_values("top 10% hit % 2024/25", ascending=False).head(30))
    TS = pd.concat(top_signs, ignore_index=True)
    best_rules = (R[R["confirmed"]].sort_values(["result", "pool", "hit % 2025/26"], ascending=[True, True, False])
                  .groupby(["result", "pool"]).head(25).drop(columns=["criteria"]))
    luck = L.groupby(["result", "pool"])["confirmed"].agg(["mean", "max"]).rename(
        columns={"mean": "luck runs: average confirmed", "max": "luck runs: most"}).reset_index()
    real = R.groupby(["result", "pool"])["confirmed"].sum().rename("real data: confirmed").reset_index()
    luck = real.merge(luck, on=["result", "pool"])
    readme = [
        f"The six 'changing' HT/FT results in {len(d):,} matches (Nesine closing odds, our data): 2024/25 "
        f"{int((d['per'] == 'A').sum()):,}, 2025/26 {int((d['per'] == 'B').sum()):,}, 2026/27 so far "
        f"{int((d['per'] == 'C').sum()):,}. 1/X = home ahead at half-time, draw at full time; X/2 = level at "
        "half-time, away wins; 1/2 = home ahead at half-time, away wins; and so on.",
        "Hit rate only (not money). Everything is found on 2024/25 and checked on 2025/26 and 2026/27.",
        "Odds ladders: how often each result happened at each level of its own HT/FT odds.",
        "Best techniques: each technique's hit rate on its top 10% of matches, vs normal.",
        "Single signs: ~390 pre-match signs per result (every market, correct scores, the other-markets model, "
        "Nesine's after-half-time chances, team habits, league history, calendar), top 30 by 2024/25.",
        "Rules: best confirmed 1-2 condition rules per result, with the same number of matches picked by the "
        "result's own odds for comparison. Luck control: the same search on shuffled results.",
        "Machine learning: boosted trees and logistic regression vs the own price, top 1-20% hit rates.",
        "Extra: two-part scores (half-time state x full-time result), score paths, team habits, two-driver maps."]
    sheets = [("Read me", pd.DataFrame({"Read me": readme})), ("Odds ladders", lad),
              ("Best techniques", summ), ("Single signs (top 30)", TS.drop(columns=["sign"])),
              ("Rules (best confirmed)", best_rules), ("Rules luck control", luck), ("Machine learning", M),
              ("ML what it used", I), ("Two-part & team habits", X["scores"]), ("Two-driver maps", X["maps"]),
              ("Best map cells", X["best_cells"])]
    with pd.ExcelWriter(OUT / "htft3.xlsx") as xw:
        for name, df in sheets:
            df.round(3).to_excel(xw, sheet_name=name[:31], index=False)
            ws = xw.sheets[name[:31]]
            ws.set_column(0, 0, 18)
            ws.set_column(1, 1, 60)
            ws.set_column(2, 40, 14)
    return summ, lad


if __name__ == "__main__":
    s, l = main()
    pd.set_option("display.width", 250)
    pd.set_option("display.max_colwidth", 90)
    print(s.round(2).to_string(index=False))
