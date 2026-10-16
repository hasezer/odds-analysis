"""Excel rule book + chart for the deep search (rules_deep.py, rules_forward.py).

Writes analysis/output/rules_deep.xlsx (summary, forward test, one sheet per bet) and rules_deep_forward.png.
"""
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from first_look import BLUE, GRAY, INK2, ORANGE, OUT  # noqa: E402
from htft_data import CACHE  # noqa: E402

PER_SHEET = 1500


def main():
    r = pd.read_parquet(CACHE / "rules_deep.parquet")
    luck = pd.read_parquet(CACHE / "rules_deep_luck.parquet").set_index("target")
    fwd = pd.read_parquet(CACHE / "rules_forward.parquet")
    r = r[r["matches_all"] >= 250]

    def rating(t):
        k, l = luck.loc[t, "kept"], luck.loc[t, "kept_by_luck"]
        if k == 0:
            return "none"
        s = l / k
        return "very reliable" if s < .02 else "reliable" if s < .10 else "mixed" if s < .5 else "unreliable (luck)"

    f30 = fwd[fwd["top_rules"] == 30].set_index("bet")
    summ = []
    for t in luck.index:
        g = r[r["target"] == t].sort_values("hit_all", ascending=False)
        row = {"Bet": t, "Rules (250+ matches)": len(g), "Rules found (all)": int(luck.loc[t, "kept"]),
               "Expected by luck": int(luck.loc[t, "kept_by_luck"]), "Reliability": rating(t),
               "Normally %": round(g["normal_all"].iloc[0], 1) if len(g) else None,
               "Best rule": g["rule"].iloc[0] if len(g) else "",
               "Best: hit 24/25 %": round(g["hit_A"].iloc[0], 1) if len(g) else None,
               "Best: hit 25/26 %": round(g["hit_B"].iloc[0], 1) if len(g) else None,
               "Best: hit 26/27 %": round(g["hit_C"].iloc[0], 1) if len(g) else None}
        if t in f30.index:
            x = f30.loc[t]
            row.update({"FORWARD TEST 26/27: normal hit %": round(x["all_C_hit_%"], 1),
                        "with top-30 rules: hit %": round(x["C_hit_%"], 1),
                        "Nesine price says %": round(x["C_price_says_%"], 1),
                        "return %": round(x["C_return_%"], 1), "bets": int(x["C_bets"])})
        summ.append(row)
    summ = pd.DataFrame(summ)

    howto = pd.DataFrame({"How to read": [
        "Rules with ONE, TWO or THREE price conditions (AND / VE) under which a high-odds bet lands more often than "
        "normal. Each bet has its own sheet; 'Kural' is the same rule with Nesine's Turkish market names.",
        "How rules were chosen: found in 24/25+2024, confirmed in 25/26+2025, then checked in 26/27+2026. Because rules "
        "were SELECTED for doing well in the first two periods, their hit rates there are flattered. The 26/27+2026 "
        "column is the honest one.",
        "Reliability (Summary sheet): the same search was repeated with shuffled results to count how many rules pure "
        "luck would produce. 'very reliable' = luck explains under 2% of the rules; 'unreliable' = most rules could be "
        "luck (HT/FT 1/X, score 2-2, 1st-half 1-1, turnaround).",
        "Forward test (sheet 'Forward test'): rules were ranked using only 24/25 and 25/26, then applied to 26/27+2026 "
        "matches they had never seen. They clearly raise the hit rate (e.g. 0-0: 6% -> 12-13%, 6+ goals: 7% -> 13%), "
        "but Nesine's price rises with them, so flat betting still loses (though less than betting blindly).",
        "'≈ (±0.10)' = two odds within 0.10 of each other. 'odds a–b' = price inside that range.",
        "Columns: Matches = matches where the rule applied; Normally = the bet's usual hit rate; Nesine price says = the "
        "chance in Nesine's own price for that bet in those matches; Return per 100 TL = flat-stake result (all "
        "periods).",
    ]})
    fsheet = fwd.rename(columns={"bet": "Bet", "top_rules": "Top N rules used"}).round(1)
    sheets = {"How to read": howto, "Summary": summ, "Forward test": fsheet}
    for t in luck.index:
        g = r[r["target"] == t].sort_values("hit_all", ascending=False).head(PER_SHEET)
        name = t.replace("/", "-").replace("Both teams score in BOTH halves", "BTTS both halves")[:31]
        sheets[name] = pd.DataFrame({
            "Rule": g["rule"], "Kural": g["kural"], "Conditions": g["conditions"], "Matches": g["matches_all"],
            "Hit 24/25+2024 % (found)": g["hit_A"].round(1), "Hit 25/26+2025 % (confirmed)": g["hit_B"].round(1),
            "Hit 26/27+2026 % (fresh)": g["hit_C"].round(1), "Hit all %": g["hit_all"].round(1),
            "Normally %": g["normal_all"].round(1), "Lift (x)": g["lift_all"].round(2),
            "Nesine price says %": g.get("nesine_price_says", pd.Series(np.nan, index=g.index)).round(1),
            "Return per 100 TL": g.get("return_per_100", pd.Series(np.nan, index=g.index)).round(1)})
    with pd.ExcelWriter(OUT / "rules_deep.xlsx", engine="openpyxl") as xw:
        for name, df in sheets.items():
            df.to_excel(xw, sheet_name=name[:31], index=False)
            ws = xw.sheets[name[:31]]
            ws.freeze_panes = "A2"
            if name != "How to read":
                ws.auto_filter.ref = ws.dimensions
            for col in ws.columns:
                ws.column_dimensions[col[0].column_letter].width = max(
                    10, min(90, max(len(str(c.value if c.value is not None else "")) for c in col) + 2))
            if name == "How to read":
                ws.column_dimensions["A"].width = 160

    # chart: forward test, top-30 rules
    show = ["Score 0-0", "Score 2-0", "Score 0-2", "Score 3-0", "Score 2-1", "Score 3-2", "Total goals 6+",
            "HT/FT X/2", "HT/FT X/1", "HT/FT 2/2", "HT/FT 2/X", "HT/FT 1/2", "HT/FT 2/1", "1st-half score 2-1"]
    d = f30.loc[[s for s in show if s in f30.index]]
    fig, ax = plt.subplots(figsize=(12, 8))
    y = np.arange(len(d))[::-1]
    ax.barh(y + .27, d["all_C_hit_%"], height=.26, color=GRAY, label="normal hit rate")
    ax.barh(y, d["C_hit_%"], height=.26, color=BLUE, label="hit rate when the rules fire")
    ax.barh(y - .27, d["C_price_says_%"], height=.26, color=ORANGE, label="what Nesine's price says in those matches")
    ax.set_yticks(y, d.index)
    ax.set_xlabel("% of matches, 2026/27 + 2026 (matches the rules had never seen)")
    ax.grid(axis="y", visible=False)
    ax.legend(loc="lower right", frameon=False)
    ax.set_title("Forward test: the rules really raise hit rates — and Nesine's price rises with them")
    fig.tight_layout(); fig.savefig(OUT / "rules_deep_forward.png", dpi=150); plt.close(fig)
    pd.set_option("display.width", 250); pd.set_option("display.max_colwidth", 60)
    print(summ.drop(columns=["Best rule"]).to_string(index=False))


if __name__ == "__main__":
    main()
