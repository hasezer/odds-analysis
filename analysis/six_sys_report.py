"""The owner's 10-game system coupon (system 3-4-5): Excel + charts from the cached system studies
(six_sys_data.py, six_sys_corr.py, six_sys_backtest.py, six_sys_legs.py, six_sys_study.py).
Writes output/six_system.xlsx and output/six_system_1_bet_value.png ... _4_hits.png.
"""
from math import comb
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from htft_data import CACHE  # noqa: E402
from rule_miner import nice  # noqa: E402
from rules_targets import tr_labels  # noqa: E402
import six_sys_study as ss  # noqa: E402

OUT = Path(__file__).resolve().parent / "output"
BLUE, ORANGE, GRAY, INK, INK2, GRID, SURF = "#2a78d6", "#eb6834", "#a3a29c", "#0b0b0b", "#52514e", "#e6e5e0", "#fcfcfb"
GREEN = "#2f9e5b"
MY6 = ("10 lowest 6+ odds", "6+ goals")
PT = ("Portugal only (all its games in the window, 3-10)", "draw & over 2.5")
PT10 = ("Portugal first, then 8 best 'draw & over 2.5' leagues, lowest odds", "draw & over 2.5")
SAME_XO = ("10 lowest 6+ odds", "draw & over 2.5")
NAMES = {MY6: "Your style: 10 lowest 6+ odds, 6+ on each",
         SAME_XO: "Same 10 games, 'draw & over 2.5' on each",
         PT: "Goals coupon: every Portugal game, 'draw & over 2.5'",
         PT10: "Goals coupon to 10: Portugal + best leagues"}
BETS = [("GOAL_RANGE||6+", "6+ goals"), ("OU|4.5|OVER", "over 4.5"), ("OU|3.5|OVER", "over 3.5"),
        ("HT_OU|1.5|OVER", "1st-half over 1.5"), ("GOAL_RANGE||4-5", "4-5 goals"), ("OU|2.5|OVER", "over 2.5"),
        ("BTTS||YES", "both teams score"), ("HT_2H_BTTS||YES/YES", "both score in both halves"),
        ("HT_CORRECT_SCORE||1-1", "half-time 1-1"), ("1X2_AND_OU|2.5|X&OVER", "draw & over 2.5")]


def style(ax):
    ax.set_facecolor(SURF)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRAY)
    ax.tick_params(colors=INK2)
    ax.grid(color=GRID, lw=.8)
    ax.set_axisbelow(True)


def payout_table():
    rows = []
    for o in (1.5, 2, 3, 4, 5, 6, 8, 10, 12, 14, 17, 20):
        r = {"odds of each game": o}
        for h in range(3, 8):
            r[f"{h} hits"] = sum(comb(h, k) * o ** k for k in (3, 4, 5)) / 582
        need = next((h for h in range(3, 11) if sum(comb(h, k) * o ** k for k in (3, 4, 5)) >= 582), None)
        r["hits needed to get the 582 units back"] = need
        rows.append(r)
    return pd.DataFrame(rows)


def bet_values():
    lg = pd.read_parquet(CACHE / "six_sys_legs.parquet")
    trn = dict(zip([k for k, _ in BETS], tr_labels([k for k, _ in BETS])))
    rows = []
    for key, short in BETS:
        for games in ("all matches", "10 lowest 6+ odds per weekend/midweek"):
            x = lg[(lg["bet"] == key) & (lg["games"] == games)].set_index("season")
            if not len(x):
                continue
            r = {"bet": short, "Nesine name": trn.get(key, nice(key)), "games": games,
                 "bets": int(x.loc["all", "legs"]), "avg odds": x.loc["all", "avg odds"],
                 "hit rate %": x.loc["all", "hit %"], "returns per 1 unit (all)": x.loc["all", "value per leg"]}
            for s in ("2024/25", "2025/26", "2026/27"):
                r[f"returns per 1 unit {s}"] = x.loc[s, "value per leg"] if s in x.index else np.nan
            rows.append(r)
    # draw & over 2.5 in Portugal and in the 8 best leagues of earlier seasons (out of sample)
    S = pd.read_parquet(CACHE / "six_sys.parquet")
    S = S[S["odds_xo"].notna()]
    S["v"] = S["y_xo"] * S["odds_xo"]
    top = ss.top_xo_leagues(S)
    later = S["per"].isin(["B", "C"])                   # out of sample: leagues chosen on the earlier season(s)
    for name, mask in (("draw & over 2.5 — Portugal", S["league"] == "POR-1"),
                       ("draw & over 2.5 — best 7 other leagues*",
                        later & S.apply(lambda r: r["league"] in top[r["per"]] and r["league"] != "POR-1", axis=1)),
                       ("draw & over 2.5 — the other 18 leagues*",
                        later & S.apply(lambda r: r["league"] not in top[r["per"]], axis=1))):
        x = S[mask]
        r = {"bet": name, "Nesine name": "MS ve 2,5 Alt/Üst: X ve Üst", "games": "all matches", "bets": len(x),
             "avg odds": x["odds_xo"].mean(), "hit rate %": x["y_xo"].mean() * 100,
             "returns per 1 unit (all)": x["v"].mean()}
        for p, s in ss.SEASON.items():
            r[f"returns per 1 unit {s}"] = x.loc[x["per"] == p, "v"].mean()
        rows.append(r)
    return pd.DataFrame(rows), top


def strategies():
    s = pd.read_parquet(CACHE / "six_sys_study_summary.parquet")
    keep = ["windows", "strategy", "leg", "season", "coupons", "avg legs", "avg odds per leg", "hit rate per leg %",
            "value per leg", "avg hits", "coupons with 3+ hits %", "coupons with 4+ hits %", "coupons with 5+ hits %",
            "singles: return per 100", "doubles: return per 100", "system 3: return per 100",
            "system 3-4-5: return per 100", "system 3-4-5: 90% range low", "system 3-4-5: 90% range high",
            "system 3-4-5: theory from leg value", "system 3-4-5: best coupon (x stake)",
            "system 3-4-5: profitable coupons %"]
    s = s[keep].rename(columns={"value per leg": "returns per 1 unit per game",
                                "system 3-4-5: theory from leg value": "system 3-4-5: long-run return from leg value"})
    return s


def money_chart(C):
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    x = C[(C["windows"] == "weekend / midweek") & (C["window kind"] == "weekend")]
    for ax, sizes, title in ((axes[0], (3, 4, 5), "System 3-4-5 (your format)"), (axes[1], (1,), "Singles")):
        style(ax)
        for key, col in ((MY6, ORANGE), (SAME_XO, GRAY), (PT, BLUE)):
            g = x[(x["strategy"] == key[0]) & (x["leg"] == key[1])].sort_values("first day")
            st = sum(g[f"stake {k}"] for k in sizes)
            ret = sum(g[f"return {k}"] for k in sizes)
            cum = ((ret / st) - 1).cumsum()
            ax.plot(pd.to_datetime(g["first day"]), cum, color=col, lw=2.2, label=NAMES[key])
        ax.axhline(0, color=INK2, lw=1)
        ax.set_yscale("symlog", linthresh=10)
        ax.xaxis.set_major_locator(matplotlib.dates.MonthLocator(bymonth=(1, 7)))
        ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%b %Y"))
        ax.set_title(title, color=INK, fontsize=12, loc="left")
        ax.set_ylabel("profit, in coupon stakes (1 = one coupon)", color=INK2)
    h, lab = axes[0].get_legend_handles_labels()
    fig.legend(h, lab, frameon=False, fontsize=9, loc="lower center", ncol=3)
    fig.suptitle("One coupon every weekend since 2024: what each way would have made (log scale)", color=INK,
                 fontsize=13, x=.02, ha="left")
    fig.tight_layout(rect=(0, .07, 1, 1))
    fig.savefig(OUT / "six_system_3_money.png", dpi=150, facecolor="white")
    plt.close(fig)


def main():
    pay = payout_table()
    bv, top = bet_values()
    summ = strategies()
    seas = pd.read_parquet(CACHE / "six_sys_study_seasons.parquet")
    sens = pd.read_parquet(CACHE / "six_sys_study_sensitivity.parquet")
    C = pd.read_parquet(CACHE / "six_sys_study_coupons.parquet")
    corr = pd.read_parquet(CACHE / "six_sys_corr.parquet")
    mom = pd.read_parquet(CACHE / "six_sys_momentum.parquet")
    theory = ss.theory_table()
    S = pd.read_parquet(CACHE / "six_sys.parquet")
    P = S[(S["league"] == "POR-1") & S["odds_xo"].notna()].copy()
    P["v"] = P["y_xo"] * P["odds_xo"]
    P["odds band"] = pd.cut(P["odds_xo"], [0, 12, 14, 17, 21, 100], labels=["≤ 12", "12–14", "14–17", "17–21", "> 21"])
    pt_band = P.pivot_table(index="odds band", columns="per", values="v", aggfunc=["size", "mean"], observed=True)
    pt_band.columns = [f"{'bets' if a == 'size' else 'returns per 1 unit'} {ss.SEASON[b]}" for a, b in pt_band.columns]
    Sx = S[S["odds_xo"].notna()].assign(v=lambda d: d["y_xo"] * d["odds_xo"])
    lg = Sx.pivot_table(index="league", columns="per", values="v", aggfunc=["size", "mean"])
    lg.columns = [f"{'bets' if a == 'size' else 'returns per 1 unit'} {ss.SEASON[b]}" for a, b in lg.columns]
    lg["in the 8 best now (all seasons)"] = lg.index.isin(ss.xo_leagues(S, ["A", "B", "C"]))
    lg = lg.sort_values("returns per 1 unit 2025/26", ascending=False)
    main_c = C[(C["windows"] == "weekend / midweek") & (C["window kind"] == "weekend") &
               C.set_index(["strategy", "leg"]).index.isin([MY6, SAME_XO, PT, PT10])].copy()
    main_c["coupon"] = [NAMES[(a, b)] for a, b in zip(main_c["strategy"], main_c["leg"])]
    main_c["system 3-4-5 paid (x stake)"] = main_c[["return 3", "return 4", "return 5"]].sum(axis=1) / \
        main_c[["stake 3", "stake 4", "stake 5"]].sum(axis=1)
    main_c["singles paid (x stake)"] = main_c["return 1"] / main_c["stake 1"]
    main_c = main_c[["coupon", "window", "season", "legs", "hits", "avg odds", "system 3-4-5 paid (x stake)",
                     "singles paid (x stake)"]].sort_values(["coupon", "window"])

    with pd.ExcelWriter(OUT / "six_system.xlsx") as xw:
        pd.DataFrame({"Read me": [
            "Your coupon: 10 games, system 3-4-5 = every treble (120), four-fold (210) and five-fold (252): 582 combos "
            "at 1 unit. Our data only (Nesine closing odds via Mackolik), 2024/25, 2025/26 and 2026/27 so far.",
            "Payout: what 3, 4, 5 ... hits pay, as a multiple of the 582 units staked, if every game has the same odds.",
            "Bet types: what 1 unit returns over time on each bet (hit rate x odds). Below 1 = Nesine keeps the "
            "difference. A combo returns the PRODUCT of its games' returns (0.70 x 0.70 x 0.70 = 0.34 for a treble).",
            "Strategies: one coupon per weekend (Fri-Mon) and per midweek (Tue-Thu), or per day; how the 10 games "
            "are chosen x which bet each game gets. 'theory' = the long-run return implied by the measured return "
            "per game (steadier than the actual result, which depends on a few lucky coupons).",
            "Season odds: 40 coupons drawn at random from each strategy's real coupons, 20,000 times.",
            "If the edge is smaller: the Goals coupon replayed with smaller Portugal edges than measured (exact long "
            "run + 4,000 simulated seasons of 30 weekends).",
            "Linked games: are 6+ games / goals linked between matches of the same day or league? (No.)",
            "Every coupon: each weekend's coupon of the main strategies."]}).to_excel(xw, sheet_name="Read me",
                                                                                     index=False)
        pay.round(2).to_excel(xw, sheet_name="Payout of your coupon", index=False)
        bv.round(3).to_excel(xw, sheet_name="Bet types", index=False)
        summ.round(2).to_excel(xw, sheet_name="Strategies", index=False)
        seas.round(1).to_excel(xw, sheet_name="Season odds", index=False)
        sens.round(1).to_excel(xw, sheet_name="If the edge is smaller", index=False)
        pt_band.round(3).reset_index().to_excel(xw, sheet_name="Portugal by odds", index=False)
        lg.round(3).reset_index().to_excel(xw, sheet_name="Draw&over2.5 by league", index=False)
        theory.round(1).to_excel(xw, sheet_name="Theory", index=False)
        corr.round(3).to_excel(xw, sheet_name="Linked games", index=False)
        mom.round(4).to_excel(xw, sheet_name="Momentum", index=False)
        main_c.round(2).to_excel(xw, sheet_name="Every coupon", index=False)
        for ws in xw.sheets.values():
            ws.set_column(0, 0, 44)
            ws.set_column(1, 30, 16)

    # 1) what 1 unit returns per bet type
    b = bv[bv["games"] == "all matches"].copy()
    b = b.sort_values("returns per 1 unit (all)")
    fig, ax = plt.subplots(figsize=(10, 6))
    style(ax)
    cols = [BLUE if "Portugal" in s else GREEN if "best 7" in s else ORANGE if s == "6+ goals" else GRAY
            for s in b["bet"]]
    ax.barh(b["bet"], b["returns per 1 unit (all)"], color=cols)
    ax.axvline(1, color=INK, lw=1.2)
    ax.text(1.01, -.9, "break-even", color=INK, fontsize=9)
    for i, (v, o) in enumerate(zip(b["returns per 1 unit (all)"], b["avg odds"])):
        ax.text(v + .01, i, f"{v:.2f}   (odds ≈ {o:.1f})", va="center", color=INK2, fontsize=9)
    ax.set_xlim(0, max(1.8, b["returns per 1 unit (all)"].max() + .35))
    ax.set_xlabel("what 1 unit staked returns over time (hit rate x odds), all matches 2024–2026\n"
                  "* 2025/26 and 2026/27 only, leagues chosen on the earlier season(s)", color=INK2)
    ax.set_title("What 1 unit returns on each bet: 6+ is one of the worst,\n'draw & over 2.5' is fair, and in "
                 "Portugal it pays", color=INK, fontsize=12, loc="left")
    fig.tight_layout()
    fig.savefig(OUT / "six_system_1_bet_value.png", dpi=150, facecolor="white")
    plt.close(fig)

    # 2) the system multiplies the return per game
    fig, ax = plt.subplots(figsize=(9, 5.5))
    style(ax)
    v = np.linspace(.6, 1.4, 161)
    for name, col, lw in (("singles", GRAY, 1.6), ("system 3", BLUE, 1.6), ("system 3-4-5", INK, 2.6)):
        ax.plot(v, [(ss.system_value(x, ss.SYSTEMS[name]) - 1) * 100 for x in v], color=col, lw=lw, label=name)
    for x, lab, col in ((0.71, "6+ in your\ngames: 0.71", ORANGE), (0.86, "draw & over 2.5\nall leagues: 0.86", GRAY),
                        (1.3, "Portugal 'draw &\nover 2.5': 1.3+", BLUE)):
        y = (ss.system_value(x) - 1) * 100
        ax.scatter([x], [y], color=col, s=70, zorder=5)
        ax.annotate(lab, (x, y), textcoords="offset points", xytext=(8, -28 if x < 1 else 6), color=col, fontsize=9)
    ax.axhline(0, color=INK2, lw=1)
    ax.axvline(1, color=GRAY, lw=1, ls="--")
    ax.set_ylim(-100, 250)
    ax.set_xlabel("what 1 unit returns on each game of the coupon", color=INK2)
    ax.set_ylabel("long-run return per 100 staked", color=INK2)
    ax.set_title("A system multiplies each game's price: below 1 it sinks, above 1 it climbs", color=INK,
                 fontsize=12, loc="left")
    ax.legend(frameon=False, loc="upper left")
    fig.tight_layout()
    fig.savefig(OUT / "six_system_2_multiplier.png", dpi=150, facecolor="white")
    plt.close(fig)

    money_chart(C)

    # 4) chance of 3+, 4+, 5+ hits and what they pay
    x = C[(C["windows"] == "weekend / midweek") & (C["window kind"] == "weekend")]
    fig, ax = plt.subplots(figsize=(10, 5))
    style(ax)
    keys = [MY6, SAME_XO, PT]
    w = .26
    for j, (key, col) in enumerate(zip(keys, (ORANGE, GRAY, BLUE))):
        g = x[(x["strategy"] == key[0]) & (x["leg"] == key[1])]
        vals = [(g["hits"] >= h).mean() * 100 for h in (3, 4, 5)]
        o = g["avg odds"].mean()
        bars = ax.bar(np.arange(3) + (j - 1) * w, vals, w, color=col, label=f"{NAMES[key]} (odds ≈ {o:.1f})")
        for h, (bb, vv) in enumerate(zip(bars, vals)):
            n = 10 if key != PT else 9
            pays = sum(comb(h + 3, k) * o ** k for k in (3, 4, 5)) / sum(comb(n, k) for k in (3, 4, 5))
            ax.text(bb.get_x() + bb.get_width() / 2, vv + .4, f"{vv:.1f}%\npays ≈{pays:,.0f}x", ha="center",
                    fontsize=7.5, color=INK2)
    ax.set_xticks(range(3), ["3+ hits", "4+ hits", "5+ hits"])
    ax.set_ylim(0, ax.get_ylim()[1] * 1.15)
    ax.set_ylabel("% of weekend coupons", color=INK2)
    ax.set_title("How often each weekend coupon reached 3, 4, 5 hits (and roughly what that pays)", color=INK,
                 fontsize=12, loc="left")
    ax.legend(frameon=False, fontsize=8.5)
    fig.tight_layout()
    fig.savefig(OUT / "six_system_4_hits.png", dpi=150, facecolor="white")
    plt.close(fig)
    return top


if __name__ == "__main__":
    print(main())
