"""All-markets signal hunt: summary tables and charts (results in analysis/ML_REPORT.md).

Prerequisites (cached in analysis/cache/):
  python analysis/ml_data.py          (~3 min)  one row per match / per selection + goal-model prices
  python analysis/ml_walkforward.py   (~40 min) walk-forward machine learning, every market
Then:  python analysis/ml_study.py    writes analysis/output/ml_*.png and analysis/output/ml_study.xlsx

Periods: A = 2024/25 + 2024 (discovery), B = 2025/26 + 2025, C = 2026/27 + 2026 (so far).
"""
from pathlib import Path
import itertools
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import htft_poisson as hp  # noqa: E402
import ml_data as md  # noqa: E402
import ml_evaluate as me  # noqa: E402
from first_look import BLUE, GRAY, INK, INK2, MARKET_NAMES, ORANGE, OUT, RED, SURFACE  # noqa: E402
from htft_data import CACHE, HTFT  # noqa: E402

SIMPLE = ["1X2", "OU", "BTTS", "HT_1X2", "2H_1X2", "TEAM_OU_HOME", "TEAM_OU_AWAY", "HT_OU", "HT_BTTS", "2H_BTTS",
          "HT_TEAM_OU_HOME", "HT_TEAM_OU_AWAY", "TEAM_WIN_EITHER_HALF_HOME", "TEAM_WIN_EITHER_HALF_AWAY"]
NAMES = {**MARKET_NAMES, "HT_2H_BTTS": "Both score 1st / 2nd half"}


def sub_of(season):
    return np.where(pd.Series(season).isin(["2024/25", "2024"]), "A",
                    np.where(pd.Series(season).isin(["2025/26", "2025"]), "B", "C"))


def z_and_roi(d, p="fair"):
    e, h = d[p].sum(), d["hit"].sum()
    return (h - e) / np.sqrt((d[p] * (1 - d[p])).sum()), (d["hit"] * d["closing_odds"] - 1).mean() * 100


# ---------------------------------------------------------------- 1. machine learning, every market
def ml_section():
    acc, bets = me.evaluate()
    acc["market_name"] = acc["market"].map(NAMES).fillna(acc["market"])
    d = acc.sort_values("gbm_vs_price_pct")
    fig, ax = plt.subplots(figsize=(11, 10))
    y = np.arange(len(d))
    ax.barh(y + .2, d["gbm_vs_price_pct"], height=.38, color=BLUE, label="Machine learning (all features)")
    ax.barh(y - .2, d["lr_vs_price_pct"], height=.38, color=ORANGE, label="Simple model (price + goal model)")
    ax.set_yticks(y, d["market_name"])
    ax.axvline(0, color=INK2, lw=1)
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("Prediction accuracy vs Nesine's own price, % (right of 0 = better than Nesine)")
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncol=2, frameon=False)
    ax.set_title("1. Machine learning barely improves on Nesine's prices\n(unseen matches, 2025 → today; the top two are a"
                 " cut-splitting artefact)", pad=34, fontsize=14)
    fig.tight_layout(); fig.savefig(OUT / "ml_1_accuracy.png", dpi=150); plt.close(fig)

    b = bets[(bets["market"] != "ALL MARKETS") & (bets["bets_B"] >= 50) & (bets["bets_C"] >= 30)]
    fig, ax = plt.subplots(figsize=(10, 8))
    ax.scatter(b["roi_B"], b["roi_C"], s=np.clip(b["bets_B"] / 40, 15, 200), color=BLUE, alpha=.6,
               edgecolor=SURFACE, linewidth=1)
    ax.axhline(0, color=INK2, lw=1); ax.axvline(0, color=INK2, lw=1)
    ax.fill_between([0, 100], 0, 100, color="#0ca30c", alpha=.06)
    ax.text(3, 3, "profitable in both", color=INK2, fontsize=10)
    ax.set_xlim(-100, 40); ax.set_ylim(-100, 40)
    ax.set_xlabel("Return of the model's 'value' bets, 2025 + 2025/26 (%)")
    ax.set_ylabel("Return, 2026 + 2026/27 so far (%)")
    ax.set_title("2. The model's 'value bets' lose money\n(each dot = one market × betting threshold; size = number of bets)",
                 fontsize=14)
    fig.tight_layout(); fig.savefig(OUT / "ml_2_value_bets.png", dpi=150); plt.close(fig)
    return acc, bets


# ---------------------------------------------------------------- 2. price caps and floors
def caps(mt, sel):
    s = sel.merge(mt[["match_id", "season"]], on="match_id")
    s["sub"] = sub_of(s["season"])
    rows = []
    for mk, g in s.groupby("market_key"):
        mx = g["closing_odds"].max()
        at = g["closing_odds"] >= .97 * mx
        if at.sum() < 200:
            continue
        row = {"market": NAMES.get(mk, mk), "cap_odds": mx, "share_of_bets_at_cap_pct": at.mean() * 100}
        for sub in "ABC":
            d = g[at & (g["sub"] == sub)]
            row[f"bets_{sub}"] = len(d)
            row[f"roi_at_cap_{sub}"] = (d["hit"] * d["closing_odds"] - 1).mean() * 100 if len(d) else np.nan
        rows.append(row)
    cap = pd.DataFrame(rows).round(1)

    # exact-price scan: does a specific odds value land more or less often than priced, in both periods?
    x = s[s["fair"].notna()].assign(grp=lambda d: d["market_key"] + " " + d["line"].map(
        lambda v: "" if pd.isna(v) else f"{v:g}") + " " + d["selection_key"])
    x["per"] = np.where(x["sub"] == "A", "A", "BC")
    rows = []
    for (grp, od), g in x.groupby(["grp", "closing_odds"]):
        a, bc = g[g["per"] == "A"], g[g["per"] == "BC"]
        if len(a) < 200 or len(bc) < 200:
            continue
        za, ra = z_and_roi(a); zb, rb = z_and_roi(bc)
        rows.append({"selection": grp, "odds": od, "bets_A": len(a), "z_A": za, "roi_A": ra, "bets_BC": len(bc),
                     "z_BC": zb, "roi_BC": rb})
    exact = pd.DataFrame(rows).round(2)

    c = cap.sort_values("roi_at_cap_A")
    fig, ax = plt.subplots(figsize=(11, 6))
    yy = np.arange(len(c))
    for i, sub in enumerate("ABC"):
        ax.barh(yy + (1 - i) * .27, c[f"roi_at_cap_{sub}"], height=.25, color=[BLUE, ORANGE, GRAY][i],
                label={"A": "2024/25 + 2024", "B": "2025/26 + 2025", "C": "2026/27 + 2026"}[sub])
    ax.set_yticks(yy, [f"{m}  (cap {o:g}, {s_:.0f}% of bets)" for m, o, s_ in
                       zip(c["market"], c["cap_odds"], c["share_of_bets_at_cap_pct"])])
    ax.axvline(0, color=INK2, lw=1); ax.set_xlim(-100, 0)
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("Return per bet at the capped price (%)")
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncol=3, frameon=False)
    ax.set_title("3. Capped prices are the worst bets on Nesine", pad=34)
    fig.tight_layout(); fig.savefig(OUT / "ml_3_caps.png", dpi=150); plt.close(fig)
    return cap, exact


# ---------------------------------------------------------------- 3. hand-made signals (form, shots, corners, popularity)
def signals(mt, sel):
    m = mt.set_index("match_id").copy()
    m["sub"] = sub_of(m["season"])
    A = m["sub"] == "A"

    def pick(mk, line, sk):
        s = sel[(sel["market_key"] == mk) & (sel["selection_key"] == sk) & sel["fair"].notna()]
        if line is not None:
            s = s[s["line"] == line]
        return s.drop_duplicates("match_id").set_index("match_id")

    def resid(y, x):
        ok = A & y.notna() & x.notna()
        b = np.polyfit(x[ok], y[ok], 1)
        return y - np.polyval(b, x)

    lam = m["lam_h1"] + m["lam_a1"] + m["lam_h2"] + m["lam_a2"]
    sot = m["h_r6_sot"] + m["a_r6_sot"] + m["h_r6_sota"] + m["a_r6_sota"]
    cs = sel[(sel["market_key"] == "CORNERS_OU") & (sel["selection_key"] == "OVER") & sel["fair"].notna()].copy()
    cs = cs.assign(gap=(cs["fair"] - .5).abs()).sort_values("gap").drop_duplicates("match_id").set_index("match_id")
    tests = [
        ("Shots-on-target form above the market's goal expectation", "Over 2.5 goals", pick("OU", 2.5, "OVER"),
         resid(sot, lam)),
        ("Shots-on-target form above the market's goal expectation", "Both teams score: yes",
         pick("BTTS", None, "YES"), resid(sot, lam)),
        ("Teams scored more than the market expected (last 15)", "Over 2.5 goals", pick("OU", 2.5, "OVER"),
         m["h_r15_res_gf"] + m["a_r15_res_gf"] + m["h_r15_res_ga"] + m["a_r15_res_ga"]),
        ("Home side's goal surplus vs market (last 15)", "Home team over 1.5", pick("TEAM_OU_HOME", 1.5, "OVER"),
         m["h_r15_res_gf"]),
        ("Corner form above the corner line", "Corners over (main line)", cs,
         resid(m["h_r6_cor"] + m["h_r6_cora"] + m["a_r6_cor"] + m["a_r6_cora"], m["corners_exp"])),
        ("More rest than the opponent (home minus away days)", "Home win", pick("1X2", None, "1"),
         (m["h_rest"] - m["a_rest"]).clip(-7, 7)),
        ("Points form difference (last 6)", "Home win", pick("1X2", None, "1"), m["h_r6_pts"] - m["a_r6_pts"]),
        ("Shots-on-target share difference (last 15)", "Home win", pick("1X2", None, "1"),
         m["h_r15_sot_share"] - m["a_r15_sot_share"]),
        ("Shots-on-target share difference (last 15)", "Away win", pick("1X2", None, "2"),
         m["h_r15_sot_share"] - m["a_r15_sot_share"]),
    ]
    rows = []
    for name, bet, s, sig in tests:
        d = s.join(sig.rename("sig"), how="inner").join(m[["sub"]]).dropna(subset=["sig"])
        cuts = np.quantile(d.loc[d["sub"] == "A", "sig"], [.2, .4, .6, .8])
        d["fifth"] = np.digitize(d["sig"], cuts) + 1
        for (q, sub), g in d.groupby(["fifth", "sub"]):
            z, roi = z_and_roi(g)
            rows.append({"signal": name, "bet": bet, "fifth (1 = lowest, 5 = highest)": q, "period": sub,
                         "bets": len(g), "excess_pts": (g["hit"].mean() - g["fair"].mean()) * 100, "z": z,
                         "roi_pct": roi})
    sig = pd.DataFrame(rows).round(2)

    # popular clubs
    tur = ["TUR-BESIKTAS", "TUR-FENERBAHCE", "TUR-GALATASARAY", "TUR-TRABZONSPOR"]
    big = ["ENG-ARSENAL", "ENG-CHELSEA", "ENG-LIVERPOOL", "ENG-MAN_CITY", "ENG-TOTTENHAM", "ESP-BARCELONA",
           "ESP-REAL_MADRID", "FRA-PSG", "GER-BAYERN_MUNIH", "GER-B_DORTMUND", "ITA-INTER", "ITA-JUVENTUS", "ITA-MILAN",
           "ITA-NAPOLI", "KSA-AL_HILAL", "KSA-AL_ITTIHAD", "KSA-AL_NASSR", "NED-AJAX", "NED-FEYENOORD", "NED-PSV",
           "POR-BENFICA", "POR-PORTO", "POR-SPORTING_CP", "SCO-CELTIC", "SCO-RANGERS", "USA-INTER_MIAMI"]
    x = sel[(sel["market_key"] == "1X2") & sel["fair"].notna()].merge(
        m[["home_team_id", "away_team_id", "sub"]], left_on="match_id", right_index=True)
    x["backed"] = np.where(x["selection_key"] == "1", x["home_team_id"],
                           np.where(x["selection_key"] == "2", x["away_team_id"], None))
    x["against"] = np.where(x["selection_key"] == "1", x["away_team_id"],
                            np.where(x["selection_key"] == "2", x["home_team_id"], None))
    rows = []
    for grp, lst in (("Turkish big 4", tur), ("European big clubs", big)):
        for role, col in (("back them", "backed"), ("back their opponent", "against")):
            for sub, g in x[x[col].isin(lst)].groupby("sub"):
                z, roi = z_and_roi(g)
                rows.append({"clubs": grp, "bet": role, "period": sub, "bets": len(g),
                             "excess_pts": (g["hit"].mean() - g["fair"].mean()) * 100, "z": z, "roi_pct": roi})
    pop = pd.DataFrame(rows).round(2)
    return sig, pop


# ---------------------------------------------------------------- 4. HT/FT shape scan (your 1/0 = 2/0 idea and more)
def htft_shape():
    w = hp.build()
    w["sub"] = sub_of(w["season"])
    per = np.where(w["sub"] == "A", "A", "BC")

    def zr(d, k):
        hit = d["htft"] == k
        p = d[f"p_{k}"]
        return len(d), int(hit.sum()), p.sum(), (hit.sum() - p.sum()) / np.sqrt((p * (1 - p)).sum()), \
            (hit * d[f"o_{k}"] - 1).mean() * 100

    r = np.log(w["o_1/X"] / w["o_2/X"])
    rows = []
    for lab, mask in (("1/0 and 2/0 priced equal (within 2%)", r.abs() < .02),
                      ("1/0 cheaper than 2/0 by > 10%", r < -.1), ("2/0 cheaper than 1/0 by > 10%", r > .1)):
        for k in HTFT:
            row = {"situation": lab, "outcome": k}
            for p_ in ("A", "BC"):
                n, h, e, z, roi = zr(w[mask & (per == p_)], k)
                row.update({f"matches_{p_}": n, f"hits_{p_}": h, f"expected_{p_}": round(e, 1), f"z_{p_}": z,
                            f"roi_{p_}": roi})
            rows.append(row)
    eq = pd.DataFrame(rows).round(2)

    rows = []
    for a, b in itertools.combinations(HTFT, 2):
        rr = np.log(w[f"o_{a}"] / w[f"o_{b}"])
        cuts = np.unique(np.quantile(rr[per == "A"], [.1, .3, .5, .7, .9]))
        g = np.digitize(rr, cuts)
        for gi in np.unique(g):
            for k in HTFT:
                row = {"price pair": f"{a} vs {b}", "band (0 = lowest ratio)": gi, "outcome": k}
                ok = True
                for p_ in ("A", "BC"):
                    d = w[(g == gi) & (per == p_)]
                    if len(d) < 150:
                        ok = False; break
                    n, h, e, z, roi = zr(d, k)
                    row.update({f"matches_{p_}": n, f"z_{p_}": z, f"roi_{p_}": roi})
                if ok:
                    rows.append(row)
    scan = pd.DataFrame(rows)

    fig, ax = plt.subplots(figsize=(10, 8))
    prof = (scan["roi_A"] > 0) & (scan["roi_BC"] > 0)
    ax.scatter(scan["z_A"], scan["z_BC"], s=12, color=GRAY, alpha=.5, linewidths=0, label="price situation × outcome")
    ax.scatter(scan.loc[prof, "z_A"], scan.loc[prof, "z_BC"], s=40, color=RED, label="profitable in both periods")
    for v in (-1.96, 1.96):
        ax.axvline(v, color=INK2, lw=.8, ls="--"); ax.axhline(v, color=INK2, lw=.8, ls="--")
    ax.set_xlabel("Lands more (+) / less (−) often than priced, 2024/25 + 2024  (z-score)")
    ax.set_ylabel("Same, later seasons  (z-score)")
    ax.legend(frameon=False, loc="upper left")
    ax.set_title(f"4. HT/FT price-shape scan: {len(scan):,} situations, {int(prof.sum())} profitable in both periods",
                 fontsize=14)
    fig.tight_layout(); fig.savefig(OUT / "ml_4_htft_shape.png", dpi=150); plt.close(fig)
    return eq, scan.round(2)


# ---------------------------------------------------------------- 5. the loss ladder: how far can selection go?
def ladder(mt, sel):
    s = sel[sel["fair"].notna()].merge(mt[["match_id", "season"]], on="match_id")
    s["sub"] = sub_of(s["season"])
    s["profit"] = np.where(s["hit"], s["closing_odds"] - 1, -1.0)
    r = np.log(s["q"] / s["fair"])
    simple = s["market_key"].isin(SIMPLE)
    short = s["closing_odds"].between(1.10, 2.0)
    rules = [
        ("Bet everything", s["closing_odds"] > 0),
        ("Only simple markets (84% payback)", simple),
        ("+ odds 1.10–2.00", simple & short),
        ("+ goal model agrees (q ≥ Nesine)", simple & short & (r >= 0)),
        ("+ over / yes / home side", simple & short & (r >= 0) & s["selection_key"].isin(["OVER", "YES", "1"])),
    ]
    rows = []
    for name, m in rules:
        row = {"rule": name}
        for sub in "ABC":
            roi, lo, hi = me.roi_ci(s[m & (s["sub"] == sub)])
            row.update({f"bets_{sub}": int((m & (s["sub"] == sub)).sum()), f"roi_{sub}": roi, f"low_{sub}": lo,
                        f"high_{sub}": hi})
        rows.append(row)
    lad = pd.DataFrame(rows).round(1)

    fig, ax = plt.subplots(figsize=(11, 6))
    x = np.arange(len(lad))
    for i, sub in enumerate("ABC"):
        ax.bar(x + (i - 1) * .27, lad[f"roi_{sub}"], width=.25, color=[BLUE, ORANGE, GRAY][i],
               label={"A": "2024/25 + 2024", "B": "2025/26 + 2025", "C": "2026/27 + 2026"}[sub])
    ax.axhline(0, color=INK2, lw=1)
    ax.set_xticks(x, [t.replace(" (", "\n(") for t in lad["rule"]], fontsize=10)
    ax.set_ylabel("Return per bet (%)")
    ax.grid(axis="x", visible=False)
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncol=3, frameon=False)
    ax.set_title("5. Smart selection halves the loss, but never reaches profit", pad=34)
    fig.tight_layout(); fig.savefig(OUT / "ml_5_ladder.png", dpi=150); plt.close(fig)
    return lad


def main():
    mt, sel = md.build()
    acc, bets = ml_section()
    cap, exact = caps(mt, sel)
    sig, pop = signals(mt, sel)
    eq, scan = htft_shape()
    lad = ladder(mt, sel)
    sheets = {"1 ML accuracy": acc, "1 ML value bets": bets, "2 Caps": cap, "2 Exact odds scan": exact,
              "3 Form & stats signals": sig, "3 Popular clubs": pop, "4 HTFT 1-0 vs 2-0": eq,
              "4 HTFT shape scan": scan, "5 Loss ladder": lad}
    with pd.ExcelWriter(OUT / "ml_study.xlsx", engine="openpyxl") as xw:
        for name, df in sheets.items():
            df.to_excel(xw, sheet_name=name[:31], index=False)
            ws = xw.sheets[name[:31]]
            ws.freeze_panes = "A2"
            for col in ws.columns:
                ws.column_dimensions[col[0].column_letter].width = max(
                    10, min(45, max(len(str(c.value if c.value is not None else "")) for c in col) + 2))
    pd.set_option("display.width", 250); pd.set_option("display.max_rows", 300)
    print(acc.sort_values("gbm_vs_price_pct", ascending=False).to_string(index=False))
    print(bets[bets["market"] == "ALL MARKETS"].to_string(index=False))
    pos = bets[(bets["roi_B"] > 0) & (bets["roi_C"] > 0) & (bets["bets_B"] >= 50) & (bets["bets_C"] >= 30)]
    print("\nmarket x rule profitable in B and C:\n", pos.to_string(index=False))
    print(cap.to_string(index=False)); print(lad.to_string(index=False)); print(pop.to_string(index=False))
    print("exact-odds cells", len(exact), "profitable in both", int(((exact.roi_A > 0) & (exact.roi_BC > 0)).sum()))
    print("htft shape cells", len(scan), "profitable in both", int(((scan.roi_A > 0) & (scan.roi_BC > 0)).sum()))


if __name__ == "__main__":
    main()
