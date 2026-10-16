"""HT/FT deep dive 2: Excel + charts from cache/htft2_tables.pkl (htft2_study.py).
Writes output/htft2.xlsx and output/htft2_1_map.png ... htft2_5_halftime_goals.png.
"""
from pathlib import Path
import pickle
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from htft2_study import FB, GB, HS, OUT as TABLES  # noqa: E402

OUT = Path(__file__).resolve().parent / "output"
SURF, INK, INK2, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
BLUE = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
SEQ = LinearSegmentedColormap.from_list("blue", BLUE)
DIV = LinearSegmentedColormap.from_list("div", ["#e34948", "#f3b3b2", "#f0efec", "#9ec5f4", "#2a78d6"])
ORDER = ["F/F", "X/F", "X/X", "U/U", "X/U", "F/X", "U/X", "U/F", "F/U"]
NAME = {"F/F": "F/F  fav ahead at HT, fav wins", "X/F": "X/F  level at HT, fav wins", "X/X": "X/X  level, ends level",
        "U/U": "U/U  dog ahead, dog wins", "X/U": "X/U  level at HT, dog wins", "F/X": "F/X  fav ahead, ends level",
        "U/X": "U/X  dog ahead, ends level", "U/F": "U/F  dog ahead, fav wins", "F/U": "F/U  fav ahead, dog wins"}


def ink_for(rgba):
    r, g, b = rgba[:3]
    return "white" if 0.2126 * r + 0.7152 * g + 0.0722 * b < 0.5 else INK


def heat(ax, M, texts, cmap, norm, rows, cols):
    ax.imshow(M, cmap=cmap, norm=norm, aspect="auto")
    for i in range(M.shape[0]):
        for j in range(M.shape[1]):
            if texts[i][j]:
                ax.text(j, i, texts[i][j], ha="center", va="center", fontsize=9,
                        color=ink_for(cmap(norm(M[i, j]))) if np.isfinite(M[i, j]) else MUTED)
    ax.set_xticks(range(len(cols)), cols, color=INK2)
    ax.set_yticks(range(len(rows)), rows, color=INK2)
    ax.tick_params(length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_xticks(np.arange(-.5, len(cols)), minor=True)
    ax.set_yticks(np.arange(-.5, len(rows)), minor=True)
    ax.grid(which="minor", color=SURF, lw=2)
    ax.tick_params(which="minor", length=0)


def fig(w, h):
    f, ax = plt.subplots(figsize=(w, h))
    f.patch.set_facecolor(SURF)
    return f, ax


def main():
    T = pickle.load(open(TABLES, "rb"))
    n = T["n_matches"].iloc[0]

    # 1) the map
    m = T["map_fav"].reindex(FB[1])
    M = m[ORDER].to_numpy().T
    f, ax = fig(10.5, 6.6)
    heat(ax, M, [[f"{v:.0f}%" for v in r] for r in M], SEQ, plt.Normalize(0, 60), [NAME[o] for o in ORDER],
         [f"{c}\n({int(k):,} games)" for c, k in zip(FB[1], m["matches"])])
    ax.set_xlabel("favourite's chance to win (Nesine's 1X2 odds, cut removed)", color=INK2)
    ax.set_title("Which HT/FT result to expect, by how strong the favourite is\n"
                 f"share of {int(n['matches']):,} matches 2024–2026; F = favourite, U = underdog, X = level",
                 color=INK, fontsize=12, loc="left")
    f.tight_layout()
    f.savefig(OUT / "htft2_1_map.png", dpi=150, facecolor=SURF)
    plt.close(f)

    # 2) half-time table
    ht = T["halftime"].set_index(["favourite", "half-time"])
    rows = [h for h in HS]
    M = np.array([[ht.loc[(c, r), "fav wins"] if (c, r) in ht.index else np.nan for c in FB[1]] for r in rows])
    tx = [[(f"fav wins {ht.loc[(c, r), 'fav wins']:.0f}%\ndraw {ht.loc[(c, r), 'draw']:.0f}% · "
            f"dog {ht.loc[(c, r), 'dog wins']:.0f}%\n({int(ht.loc[(c, r), 'matches'])} games)")
           if (c, r) in ht.index and ht.loc[(c, r), "matches"] >= 30 else "too few games" for c in FB[1]] for r in rows]
    f, ax = fig(12, 7.4)
    heat(ax, M, tx, SEQ, plt.Normalize(0, 100), [r.replace(" (1-1, 2-2)", "\n(1-1, 2-2)") for r in rows], FB[1])
    ax.set_xlabel("favourite's chance to win before the match (Nesine's 1X2 odds, cut removed)", color=INK2)
    ax.set_ylabel("score at half-time", color=INK2)
    ax.set_title("At half-time: how often each full-time result really happens\n"
                 "use it live: a bet is worth it only if the live odds are above 100 / chance%", color=INK,
                 fontsize=12, loc="left")
    f.tight_layout()
    f.savefig(OUT / "htft2_2_halftime.png", dpi=150, facecolor=SURF)
    plt.close(f)

    # 3) what each HT/FT outcome returns
    v = T["value_fav"].pivot_table(index="outcome", columns="favourite", values="returns per 1 unit")
    v = v.reindex(index=ORDER, columns=FB[1])
    M = v.to_numpy()
    f, ax = fig(10.5, 6.6)
    heat(ax, M, [[f"{x:.2f}" if np.isfinite(x) else "" for x in r] for r in M], DIV, TwoSlopeNorm(1.0, 0.3, 1.3),
         [NAME[o] for o in ORDER], FB[1])
    ax.set_xlabel("favourite's chance to win (Nesine's 1X2 odds, cut removed)", color=INK2)
    ax.set_title("What 1 unit returns on each HT/FT result (all seasons)\n"
                 "below 1.00 = loses; every cell loses, the underdog's results lose the most", color=INK,
                 fontsize=12, loc="left")
    f.tight_layout()
    f.savefig(OUT / "htft2_3_value.png", dpi=150, facecolor=SURF)
    plt.close(f)

    # 4) half-time related bets: what 1 unit returns
    fam = T["family"].set_index("bet")
    pick = {"HT_2H_BTTS||YES/YES": "both teams score in both halves", "HT_CORRECT_SCORE||fav 1-1": "half-time score 1-1",
            "2H_BTTS||YES": "both teams score in the 2nd half", "HT_OU|0.5|OVER": "1st half over 0.5 goals",
            "2H_1X2||X": "2nd half ends level", "2H_1X2||F": "favourite wins the 2nd half",
            "HT_1X2||F": "favourite leads at half-time", "HT_1X2||X": "level at half-time",
            "HT_1X2||U": "underdog leads at half-time", "HT_OU|1.5|OVER": "1st half over 1.5 goals",
            "HT_FT||F/F": "HT/FT F/F", "HT_FT||X/F": "HT/FT X/F", "HT_FT||X/X": "HT/FT X/X",
            "HT_FT||U/U": "HT/FT U/U", "HT_FT||X/U": "HT/FT X/U", "HT_FT||F/U": "HT/FT F/U (turnaround)",
            "HT_FT||U/F": "HT/FT U/F (turnaround)"}
    b = fam.loc[[k for k in pick if k in fam.index]].copy()
    b["label"] = [pick[k] for k in b.index]
    b = b.sort_values("returns per 1 unit")
    f, ax = fig(10, 6.8)
    ax.set_facecolor(SURF)
    cols = ["#a3a29c" if k.startswith("HT_FT") else "#2a78d6" for k in b.index]
    ax.barh(b["label"], b["returns per 1 unit"], color=cols, height=.7)
    ax.axvline(1, color=INK, lw=1.2)
    ax.text(1.005, -0.9, "break-even", color=INK, fontsize=9)
    for i, (val, o) in enumerate(zip(b["returns per 1 unit"], b["avg odds"])):
        ax.text(val + .008, i, f"{val:.2f}  (odds ≈ {o:.1f})", va="center", color=INK2, fontsize=9)
    ax.set_xlim(0.5, 1.12)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.grid(axis="x", color=GRID, lw=.8)
    ax.set_axisbelow(True)
    ax.tick_params(colors=INK2)
    ax.set_xlabel("what 1 unit returns over time (all matches, 2024–2026); grey = the HT/FT market itself", color=INK2)
    ax.set_title("Half-time ideas are cheaper to bet outside the HT/FT market", color=INK, fontsize=12, loc="left")
    f.tight_layout()
    f.savefig(OUT / "htft2_4_family.png", dpi=150, facecolor=SURF)
    plt.close(f)

    # 5) half-time goals -> 2nd-half goals (live goals aid)
    hg = T["halftime_goals"].set_index(["pre-match over 2.5 chance", "half-time goals"])
    rows = ["0", "1", "2", "3+"]
    M = np.array([[hg.loc[(c, r), "2nd half 2+ goals %"] for c in GB[1]] for r in rows])
    tx = [[f"1+ goal {hg.loc[(c, r), '2nd half 1+ goals %']:.0f}%\n2+ goals {hg.loc[(c, r), '2nd half 2+ goals %']:.0f}%"
           f"\n({int(hg.loc[(c, r), 'matches'])} games)" for c in GB[1]] for r in rows]
    f, ax = fig(10.5, 5.6)
    heat(ax, M, tx, SEQ, plt.Normalize(0, 80), [f"{r} goal{'s' if r != '1' else ''} at half-time" for r in rows],
         GB[1])
    ax.set_xlabel("before the match: Nesine's chance of over 2.5 goals", color=INK2)
    ax.set_title("At half-time: chance of goals in the 2nd half", color=INK, fontsize=12, loc="left")
    f.tight_layout()
    f.savefig(OUT / "htft2_5_halftime_goals.png", dpi=150, facecolor=SURF)
    plt.close(f)

    # Excel
    readme = [
        f"HT/FT deep dive 2: {int(n['matches']):,} matches with all 9 HT/FT prices (Nesine closing odds, our data): "
        f"2024/25 {int(n['2024/25']):,}, 2025/26 {int(n['2025/26']):,}, 2026/27 so far {int(n['2026/27']):,}.",
        "Everything is seen from the FAVOURITE's side (by Nesine's 1X2 odds): F = favourite, U = underdog (dog), "
        "X = level. F/F = favourite ahead at half-time and wins. If the favourite plays at home, F/F is Nesine's 1/1; "
        "if it plays away, F/F is 2/2.",
        "Map: share of each HT/FT result by favourite strength (and goal expectation), by season.",
        "Spot: the best group of games for each result (chosen on 2024/25 + 2025/26) vs the top 10% by its own odds.",
        "Most likely: how often Nesine's most likely HT/FT result happens.",
        "Half-time table: after each half-time score, how often the favourite wins / draws / loses, and 2nd-half goals."
        " Live use: a bet is worth it only if the live odds are above 100 / chance%.",
        "Implied vs actual: Nesine's pre-match HT/FT chances of each full-time result after each half-time result.",
        "Returns: what 1 unit returns on each HT/FT result (1.00 = break-even).",
        "Scan: cells at or above break-even in 2024/25 AND 2025/26, against a no-edge luck twin.",
        "Half-time bets: every half-time-related bet, what 1 unit returns.",
        "Leagues late: does a league keep scoring later than the odds expect? (No.)",
        "Hypotheses: Portugal 1/X (from the Portugal 2-2 effect), draws by goal expectation."]
    sheets = [("Read me", pd.DataFrame({"Read me": readme})), ("Map by favourite", T["map_fav"].reset_index()),
              ("Map by season", T["map_fav_by_season"]), ("Map favourite x goals", T["map_cells"].reset_index()),
              ("Spot each result", T["spot"]), ("Most likely result", T["top_outcome"]),
              ("Half-time table", T["halftime"]), ("Half-time goals", T["halftime_goals"]),
              ("Implied vs actual", T["transitions"]), ("Returns by favourite", T["value_fav"]),
              ("Returns F-F by odds", T["value_ff"]), ("Scan (luck control)", T["scan"]),
              ("Scan cells", T["scan_cells"]), ("Half-time bets", T["family"]),
              ("Half-time bets by fav", T["family_fav"]), ("Leagues late", T["league_late"]),
              ("Leagues late corr", pd.concat([T["league_late_corr"], T["half_share"]], axis=1)),
              ("Hypotheses", T["hypotheses"])]
    with pd.ExcelWriter(OUT / "htft2.xlsx") as xw:
        for name, df in sheets:
            df.round(3).to_excel(xw, sheet_name=name[:31], index=False)
            ws = xw.sheets[name[:31]]
            ws.set_column(0, 0, 40)
            ws.set_column(1, 40, 15)


if __name__ == "__main__":
    main()
