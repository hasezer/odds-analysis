"""Charts for rule hunt v3 (PNG, light theme, readable on an iPad). Writes output/v3_*.png."""
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import miner_data as mdat  # noqa: E402
from htft_data import CACHE  # noqa: E402

OUT = Path(__file__).resolve().parent / "output"
BLUE, ORANGE, GRAY = "#2a78d6", "#eb6834", "#a3a29c"
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e6e5e0", "#fcfcfb"
PERIODS = [("A", "2024/25"), ("B", "2025/26"), ("C", "2026/27 so far")]


def style(ax):
    ax.set_facecolor(SURF)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=INK2, length=0, labelsize=11)
    ax.grid(axis="y", color=GRID, lw=.8)
    ax.set_axisbelow(True)


def portugal():
    z = mdat.build()
    names = list(z["names"])
    i = names.index("1X2_AND_OU|2.5|X&OVER")
    o, y, per, lg = z["O"][:, i], z["Hm"][:, i], z["per"], z["league"].astype(str)
    ok = ~np.isnan(o) & ~np.isnan(y)
    fig, axes = plt.subplots(1, 2, figsize=(11, 5.2), sharey=True, facecolor=SURF)
    for ax, (title, m_l) in zip(axes, (("Portugal Primeira Liga", lg == "POR-1"), ("All other 25 leagues", lg != "POR-1"))):
        style(ax)
        x = np.arange(3)
        hit, be, n = [], [], []
        for p, _ in PERIODS:
            m = ok & m_l & (per == p)
            hit.append(y[m].mean() * 100); be.append((1 / o[m]).mean() * 100); n.append(m.sum())
        w = .36
        b1 = ax.bar(x - w / 2 - .01, hit, w, color=BLUE, label="Actually hit")
        b2 = ax.bar(x + w / 2 + .01, be, w, color=ORANGE, label="Needed to break even")
        for bars in (b1, b2):
            for b in bars:
                ax.text(b.get_x() + b.get_width() / 2, b.get_height() + .25, f"{b.get_height():.1f}%",
                        ha="center", va="bottom", fontsize=10.5, color=INK)
        ax.set_xticks(x, [f"{lab}\n{k} matches" for (_, lab), k in zip(PERIODS, n)])
        ax.set_title(title, loc="left", fontsize=13, color=INK, fontweight="bold")
    axes[0].set_ylabel("% of matches", color=INK2, fontsize=11)
    h, l = axes[0].get_legend_handles_labels()
    fig.legend(h, l, frameon=False, fontsize=11, loc="upper left", bbox_to_anchor=(.055, .93), ncol=2, labelcolor=INK)
    fig.suptitle("Draw with 3+ goals (2-2, 3-3 …): Portugal pays, other leagues don't", x=.06, ha="left",
                 fontsize=15, color=INK, fontweight="bold")
    fig.text(.06, .005, "Blue above orange = the bet made money in that season. Odds: Nesine closing prices.",
             fontsize=10, color=INK2)
    fig.tight_layout(rect=(0, .03, 1, .88))
    fig.savefig(OUT / "v3_portugal_draws.png", dpi=160)


def ceiling():
    b = pd.read_excel(OUT / "rules_v3.xlsx", sheet_name="Best rules per bet")
    keep = ["Goals over 2.5", "Goals under 2.5", "Both teams score yes", "Both teams score no", "Result home",
            "Result draw", "Result away", "HT/FT 1/1", "HT/FT 2/1", "HT/FT X/X", "Score 1-1", "Score 2-1",
            "Corners over 9.5", "Corners under 9.5", "Goals over 3.5", "1st-half result draw"]
    rows = []
    for k in keep:
        g = b[b["Bet"] == k]
        if not len(g):
            continue
        g = g.sort_values("Hit %", ascending=False).iloc[0]          # best over all seasons, then its 2026/27
        rows.append((k, g["Normal %"], g["Hit % 2026/27"], g["Break-even % 2026/27"]))
    d = pd.DataFrame(rows, columns=["bet", "normal", "rule", "be"]).iloc[::-1]
    fig, ax = plt.subplots(figsize=(10, .48 * len(d) + 1.6), facecolor=SURF)
    style(ax)
    ax.grid(axis="x", color=GRID, lw=.8); ax.grid(axis="y", visible=False)
    yy = np.arange(len(d))
    ax.hlines(yy, d["normal"], d["rule"], color=GRID, lw=3, zorder=1)
    ax.scatter(d["normal"], yy, s=70, color=GRAY, zorder=3, label="Normal hit rate (all matches)",
               edgecolor=SURF, lw=2)
    ax.scatter(d["rule"], yy, s=80, color=BLUE, zorder=4, label="Best rule's hit rate, 2026/27", edgecolor=SURF, lw=2)
    ax.scatter(d["be"], yy, s=90, color=ORANGE, marker="|", lw=3, zorder=5, label="Needed to break even at its odds")
    for y_, r in zip(yy, d.itertuples()):
        ax.text(max(r.rule, r.be) + 1.5, y_, f"{r.rule:.0f}%", va="center", fontsize=10, color=INK)
    ax.set_yticks(yy, d["bet"], fontsize=11, color=INK)
    ax.set_xlabel("% of matches", color=INK2)
    h, l = ax.get_legend_handles_labels()
    fig.legend(h, l, frameon=False, fontsize=10.5, loc="upper left", bbox_to_anchor=(.01, .955), ncol=3,
               labelcolor=INK)
    fig.suptitle("Rules push hit rates up a lot — but the odds shrink just as much", x=.01, ha="left",
                 fontsize=14, color=INK, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, .93))
    fig.savefig(OUT / "v3_hit_ceiling.png", dpi=160)


def stacking():
    f = CACHE / "rules_v3_vote.parquet"
    if not f.exists():
        return
    v = pd.read_parquet(f)
    v = v[(v["track"] == "money") & (v["matches_C"] > 0)]
    order = [b[2] for b in __import__("rules_v3_vote").BUCKETS]
    g = v.groupby("bucket").apply(lambda d: pd.Series({
        "bets": d["matches_C"].sum(),
        "ret": np.average(d["return_per_100_C"].fillna(0), weights=d["matches_C"])})).reindex(order).dropna()
    fig, ax = plt.subplots(figsize=(10, 5), facecolor=SURF)
    style(ax)
    x = np.arange(len(g))
    bars = ax.bar(x, g["ret"], .55, color=[BLUE if r >= 0 else ORANGE for r in g["ret"]])
    ax.axhline(0, color=INK2, lw=1)
    for b_, (k, r) in zip(bars, g.iterrows()):
        ax.text(b_.get_x() + b_.get_width() / 2, r["ret"] + (1 if r["ret"] >= 0 else -1),
                f"{r['ret']:+.1f}\n{int(r['bets']):,} bets", ha="center", va="bottom" if r["ret"] >= 0 else "top",
                fontsize=10, color=INK)
    ax.set_xticks(x, g.index, fontsize=11)
    ax.set_ylabel("Return per 100 staked, 2026/27", color=INK2)
    ax.set_title("Rules that made money in 2024/25 AND 2025/26, bet blindly in 2026/27", loc="left", fontsize=14,
                 color=INK, fontweight="bold")
    fig.text(.01, .005, "x axis: how many of those rules pointed at the bet in that match. All bet types together.",
             fontsize=10, color=INK2)
    fig.tight_layout(rect=(0, .03, 1, 1))
    fig.savefig(OUT / "v3_stacking.png", dpi=160)


if __name__ == "__main__":
    portugal()
    ceiling()
    stacking()
