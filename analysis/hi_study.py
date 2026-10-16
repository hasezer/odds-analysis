"""High-odds hit-rate study: Excel tables and charts for the iPad.

Reads cache/hi_*.parquet (hi_rank, hi_boost, hi_trees, hi_compare, hi_leagues) and cache/hi_data.npz.
Writes output/high_odds.xlsx and output/hi_*.png.
"""
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hi_data  # noqa: E402
import hi_rank  # noqa: E402
from htft_data import CACHE  # noqa: E402

OUT = Path(__file__).resolve().parent / "output"
BLUE, ORANGE, AQUA, GRAY = "#2a78d6", "#eb6834", "#1baf7a", "#a3a29c"
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e6e5e0", "#fcfcfb"
PER = {"A": "2024/25", "B": "2025/26", "C": "2026/27"}
NB = 6


def style(ax, grid="y"):
    ax.set_facecolor(SURF)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=INK2, length=0, labelsize=10)
    ax.grid(axis=grid, color=GRID, lw=.8)
    ax.set_axisbelow(True)


def ladder(d, Fq):
    """Hit rate by odds band of the bet itself (bands = sextiles of A + B); combined bets: goal-model bands."""
    rows = []
    per = d["per"]
    AB = np.isin(per, ["A", "B"])
    for j, (tn, ti) in enumerate(zip(d["tnames"], d["tprice"])):
        y = d["Y"][:, j]
        if ti >= 0 and (~np.isnan(d["O"][AB, ti])).mean() >= .5:
            v, kind = d["O"][:, ti], "odds"
        else:
            v, kind = 1 / np.where(Fq[:, j] > 0, Fq[:, j], np.nan), "goal-model odds (1 / chance)"
        ok = ~np.isnan(y) & ~np.isnan(v)
        e = np.unique(np.round(np.nanquantile(v[AB & ok], np.linspace(0, 1, NB + 1)), 2))
        e[0], e[-1] = 0, np.inf
        for k in range(len(e) - 1):
            lo, hi = e[k], e[k + 1]
            m = ok & (v > lo) & (v <= hi)
            band = f"≤ {hi:.2f}" if lo == 0 else f"> {lo:.2f}" if hi == np.inf else f"{lo:.2f}–{hi:.2f}"
            row = {"Bet": tn, "Band of": kind, "Odds band": band, "_k": k}
            for p, nm in PER.items():
                mp = m & (per == p)
                row[f"Matches {nm}"] = int(mp.sum())
                row[f"Hit % {nm}"] = y[mp].mean() * 100 if mp.sum() else np.nan
            row["Normal % (all)"] = np.nanmean(y) * 100
            mo = m & ~np.isnan(d["O"][:, ti]) if ti >= 0 else np.zeros_like(m)
            row["Average odds"] = np.nanmean(d["O"][mo, ti]) if mo.sum() else np.nan
            rows.append(row)
    return pd.DataFrame(rows)


def pack_filter(d, Fq):
    """Packs of the k most likely selections, played only in the matches where the pack is most likely (C)."""
    tk, names = list(d["tkeys"]), list(d["names"])
    per = d["per"]
    C = per == "C"
    groups = {"Correct score": "CORRECT_SCORE|", "1st-half score": "HT_CORRECT_SCORE|", "HT/FT": "HT_FT|"}
    rows = []
    for gname, pre in groups.items():
        ks = [k for k in tk if k.startswith(pre)]
        ti = [tk.index(k) for k in ks]
        oi = [names.index(k) for k in ks]
        P, Y, O = Fq[C][:, ti], d["Y"][C][:, ti], d["O"][C][:, oi]
        ok = ~np.isnan(Y).any(1) & ~np.isnan(P).any(1)
        order = np.argsort(-P, axis=1)
        for k in (1, 2, 3):
            pick = order[:, :k]
            pp = np.take_along_axis(P, pick, 1).sum(1)
            hit = np.take_along_axis(Y, pick, 1).max(1)
            eff = 1 / (1 / np.take_along_axis(O, pick, 1)).sum(1)
            for share in (1.0, .3, .1):
                thr = np.nanquantile(pp[ok], 1 - share)
                m = ok & (pp >= thr)
                me = m & ~np.isnan(eff)
                rows.append({"Pack": f"{gname}: {k} most likely", "Matches played": f"top {int(share * 100)}% most "
                             f"predictable" if share < 1 else "every match", "Bets 2026/27": int(m.sum()),
                             "Hit % 2026/27": hit[m].mean() * 100, "Effective odds (median)": np.nanmedian(eff[me]),
                             "Return per 100": np.nanmean(hit[me] * eff[me] - 1) * 100})
    return pd.DataFrame(rows)


def best_per_bet():
    r = pd.read_parquet(CACHE / "hi_rank.parquet")
    b = CACHE / "hi_boost.parquet"
    if b.exists():
        r = pd.concat([r, pd.read_parquet(b)])
    rows = []
    for tn, g in r.groupby("target", sort=False):
        row = {"Bet": tn, "Normal % 2026/27": g[g["test"] == "C"]["normal"].iloc[0]}
        for cov in (.02, .05, .10, .20):
            x = g[(g["cover"] == cov) & (g["method"] == "price")]
            for t in ("B", "C"):
                xx = x[x["test"] == t]
                row[f"Cheapest {int(cov * 100)}%: hit % {PER[t]}"] = xx["hit"].iloc[0] if len(xx) else np.nan
            xc = x[x["test"] == "C"]
            row[f"Cheapest {int(cov * 100)}%: avg odds"] = xc["avg_odds"].iloc[0] if len(xc) else np.nan
        x = g[(g["cover"] == .10) & (g["test"] == "C")].set_index("method")["hit"]
        for m, nm in (("model", "goal model"), ("ml", "machine learning"), ("rules", "rule count"),
                      ("price+fix", "price + corrections")):
            row[f"Top 10% by {nm}: hit % 2026/27"] = x.get(m, np.nan)
        rows.append(row)
    return pd.DataFrame(rows), r


def charts(lad, methods, pf, lgs):
    # 1) odds ladder for six popular high-odds bets
    pick = ["HT/FT 2/1", "HT/FT 1/2", "Score 2-1", "Score 1-1", "Both score 1st/2nd half yes/yes",
            "Total goals 6+"]
    pick = [p for p in pick if p in set(lad["Bet"])]
    fig, axes = plt.subplots(2, 3, figsize=(13, 7.5), facecolor=SURF)
    for ax, b in zip(axes.ravel(), pick):
        style(ax)
        g = lad[lad["Bet"] == b].sort_values("_k")
        x = np.arange(len(g))
        ab = (g["Hit % 2024/25"] * g["Matches 2024/25"] + g["Hit % 2025/26"] * g["Matches 2025/26"]) / \
             (g["Matches 2024/25"] + g["Matches 2025/26"])
        kind = g["Band of"].iloc[0]
        ax.bar(x - .2, ab, .38, color=BLUE, label="2024/25 + 2025/26")
        if kind != "odds":
            ax.set_xlabel("goal-model odds (from the main markets)", fontsize=8.5, color=INK2)
        ax.bar(x + .2, g["Hit % 2026/27"], .38, color=ORANGE, label="2026/27 (exam)")
        ax.axhline(g["Normal % (all)"].iloc[0], color=INK2, lw=1, ls=(0, (3, 3)))
        ax.set_xticks(x, g["Odds band"], rotation=30, ha="right", fontsize=8.5)
        ax.set_title(b, loc="left", fontsize=11.5, color=INK, fontweight="bold")
    for ax in axes.ravel()[len(pick):]:
        ax.axis("off")
    h, l = axes.ravel()[0].get_legend_handles_labels()
    fig.legend(h + [plt.Line2D([], [], color=INK2, ls=(0, (3, 3)))], l + ["normal hit rate"], frameon=False,
               loc="upper left", bbox_to_anchor=(.01, .95), ncol=3, fontsize=10.5, labelcolor=INK)
    fig.suptitle("Odds ladder: the cheaper the bet's own odds, the more often it hits (x axis: the bet's odds band)",
                 x=.01, ha="left", fontsize=14, color=INK, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, .91))
    fig.savefig(OUT / "hi_odds_ladder.png", dpi=150)

    # 2) ways to pick matches: average lift vs share of matches bet (2026/27)
    m = methods[methods["test"] == "C"].groupby(["method", "cover"]).apply(
        lambda x: (x["hit"] / x["normal"]).mean()).unstack("method")
    fig, ax = plt.subplots(figsize=(10, 5.2), facecolor=SURF)
    style(ax, "both")
    lab = {"price": ("Nesine's own odds for the bet", BLUE), "price+fix": ("odds + corrections (ML)", AQUA),
           "rules": ("number of rules agreeing", ORANGE), "ml": ("machine learning, all features", GRAY)}
    for k, (nm, col) in lab.items():
        if k in m:
            ax.plot(m.index * 100, m[k], marker="o", ms=7, lw=2, color=col, label=nm, mec=SURF, mew=1.5)
    ax.set_xscale("log")
    ax.set_xticks([1, 2, 5, 10, 20], ["top 1%", "2%", "5%", "10%", "20%"])
    ax.set_ylabel("hit rate ÷ normal hit rate", color=INK2)
    ax.legend(frameon=False, fontsize=10.5, labelcolor=INK)
    ax.set_title("Which matches to bet? The bet's own odds pick best (66 high-odds bets, 2026/27)", loc="left",
                 fontsize=13.5, color=INK, fontweight="bold")
    fig.tight_layout()
    fig.savefig(OUT / "hi_methods.png", dpi=150)

    # 3) packs
    fig, ax = plt.subplots(figsize=(10, 5.5), facecolor=SURF)
    style(ax, "both")
    for share, col in (("every match", GRAY), ("top 30% most predictable", BLUE), ("top 10% most predictable", ORANGE)):
        g = pf[pf["Matches played"] == share]
        ax.scatter(g["Effective odds (median)"], g["Hit % 2026/27"], s=70, color=col, label=share, edgecolor=SURF,
                   lw=1.5, zorder=3)
        for i, r in enumerate(g.itertuples()):
            if share == "top 10% most predictable":
                ax.annotate(r.Pack.replace(" most likely", ""), (r[5], r[4]), xytext=(8, 5 if i % 2 else -12),
                            textcoords="offset points", fontsize=8.5, color=INK2)
    ax.set_xlabel("effective odds of the pack (median)", color=INK2)
    ax.set_ylabel("hit % 2026/27", color=INK2)
    ax.legend(frameon=False, fontsize=10.5, labelcolor=INK, title="matches played", title_fontsize=10)
    ax.set_title("Packs: back the 1–3 most likely scores / HT-FT results together", loc="left", fontsize=13.5,
                 color=INK, fontweight="bold")
    fig.tight_layout()
    fig.savefig(OUT / "hi_packs.png", dpi=150)


def main():
    d = hi_data.build()
    Fq = hi_rank.goal_model_probs(d)
    sheets = {}
    lad = ladder(d, Fq)
    sheets["Odds ladder"] = lad.drop(columns="_k").round(2)
    best, methods = best_per_bet()
    sheets["Best way to pick matches"] = best.round(1)
    pk = pd.read_parquet(CACHE / "hi_packs.parquet")
    pf = pack_filter(d, Fq)
    sheets["Packs (filtered)"] = pf.round(2)
    sheets["Packs (all methods)"] = pk.round(2)
    tr = CACHE / "hi_trees.parquet"
    if tr.exists():
        t = pd.read_parquet(tr)
        t = t.sort_values(["target", "hit_B"], ascending=[True, False]).groupby("target").head(5)
        t["beats_odds_filter_C"] = t["hit_C"] > t["odds_filter_same_size_C"]
        sheets["Readable rules (trees)"] = t.round(2)
        sheets["Trees luck check"] = pd.read_parquet(CACHE / "hi_trees_luck.parquet")
    cp = CACHE / "hi_compare.parquet"
    if cp.exists():
        c = pd.read_parquet(cp)
        sheets["v3 rules beyond odds - luck"] = pd.read_parquet(CACHE / "hi_compare_luck.parquet").round(1)
        top = c[c["z_beyond_odds_C"] >= 2].sort_values("z_beyond_odds_C", ascending=False).groupby("target").head(5)
        sheets["v3 rules beating odds 26-27"] = top[["target", "rule", "conditions", "families", "matches_A", "hit_A",
                                                     "matches_B", "hit_B", "matches_C", "hit_C", "normal_C",
                                                     "odds_say_C", "odds_filter_same_size_C",
                                                     "z_beyond_odds_C"]].round(2)
    lg = pd.read_parquet(CACHE / "hi_leagues.parquet")
    lgl = pd.read_parquet(CACHE / "hi_leagues_luck.parquet")
    lg["beyond_odds_every_season"] = (lg["hit_A"] > lg["model_A"]) & (lg["hit_B"] > lg["model_B"]) & \
                                     (lg["hit_C"] > lg["model_C"])
    sheets["League tendencies"] = lg.round(2)
    sheets["League luck check"] = pd.DataFrame({"Real: league x bet pairs above normal in A and B": [len(lg)],
                                                "Shuffled leagues: average": [lgl["found"].mean()],
                                                "Shuffled leagues: most": [lgl["found"].max()],
                                                "Real pairs still above normal in 2026/27 (%)":
                                                    [lg["held_in_C"].mean() * 100]})
    with pd.ExcelWriter(OUT / "high_odds.xlsx") as xw:
        pd.DataFrame({"Read me": [
            "High-odds bets (typical odds 4+) in all 26 leagues: how to raise the hit rate. Our data only.",
            "Seasons: 2024/25 (+2024) find, 2025/26 (+2025) confirm, 2026/27 (+2026) so far = exam.",
            "Odds ladder: hit rate by the bet's own odds band. The single strongest filter.",
            "Best way to pick matches: hit rate if you bet only the cheapest 2/5/10/20% of matches, per method.",
            "Packs: back the k most likely scores / HT-FT results of a match together.",
            "Readable rules: up to 3 conditions with exact cut-offs, found on 2024/25, confirmed 2025/26.",
            "'odds say': the hit rate the odds of those same matches predict. 'odds filter same size': hit rate of "
            "the same number of matches where the bet was cheapest.",
            "League tendencies: leagues that produce a result more often than normal, every season.",
        ]}).to_excel(xw, sheet_name="Read me", index=False)
        for name, df in sheets.items():
            df.to_excel(xw, sheet_name=name[:31], index=False)
            ws = xw.sheets[name[:31]]
            for i, c in enumerate(df.columns):
                w = min(max(len(str(c)), *(len(str(v)) for v in df[c].head(200))) + 2, 70) if len(df) else 15
                ws.set_column(i, i, w)
    charts(lad, methods, pf, lg)
    return sheets


if __name__ == "__main__":
    s = main()
    print({k: len(v) for k, v in s.items()})
