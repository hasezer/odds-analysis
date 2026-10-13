"""Rule book for the iPad: price rules that make an outcome land much more often than usual.

Needs cache/rule_book.parquet from rule_miner.py. Writes analysis/output/rules_book.xlsx and rules_examples.png.
"""
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from first_look import BLUE, GRAY, INK2, OUT  # noqa: E402
from htft_data import CACHE  # noqa: E402

POPULAR = ["1X2||1", "1X2||X", "1X2||2", "OU|2.5|OVER", "OU|2.5|UNDER", "OU|3.5|OVER", "OU|1.5|UNDER", "BTTS||YES",
           "BTTS||NO", "GOAL_RANGE||6+", "GOAL_RANGE||0-1", "HT_OU|1.5|OVER", "HT_OU|0.5|UNDER", "HT_FT||1/1",
           "HT_FT||X/X", "HT_FT||2/2", "HT_FT||2/1", "HT_FT||1/2", "HT_FT||X/1", "HT_FT||X/2", "HT_FT||1/X",
           "HT_FT||2/X", "CORRECT_SCORE||0-0", "CORRECT_SCORE||1-1", "CORNERS_OU|9.5|OVER", "CORNERS_OU|9.5|UNDER",
           "HT_1X2||X", "BOTH_HALVES_OVER|1.5|YES"]


def table(d):
    t = pd.DataFrame({
        "When this happens (closing odds)": d["rule"],
        "Bet": d["then"],
        "Matches": d["matches_all"].astype(int),
        "Hit 24/25+2024 %": d["hit_A"].round(1),
        "Hit 25/26+2025 %": d["hit_B"].round(1),
        "Hit 26/27+2026 %": d["hit_C"].round(1),
        "Hit all %": d["hit_all"].round(1),
        "Normally %": d["normal_all"].round(1),
        "Lift (x normal)": d["lift_all"].round(2),
        "Nesine's price says %": d["priced_all"].round(1),
        "Return per 100 TL": d["roi_all"].round(1),
    })
    return t.reset_index(drop=True)


def diverse(d, by, n, key="then"):
    """Best n rows by `by`, at most one per outcome and per condition."""
    out, seen_o, seen_c = [], set(), set()
    for _, r in d.sort_values(by, ascending=False).iterrows():
        if r[key] in seen_o or r["rule"] in seen_c:
            continue
        out.append(r); seen_o.add(r[key]); seen_c.add(r["rule"])
        if len(out) == n:
            break
    return pd.DataFrame(out)


def main():
    r = pd.read_parquet(CACHE / "rule_book.parquet")
    r = r[r["matches_all"] >= 500]
    r["min_hit"] = r[["hit_A", "hit_B", "hit_C"]].min(axis=1)
    r["min_lift"] = r[["lift_A", "lift_B", "lift_C"]].min(axis=1)

    high = diverse(r[(r["min_hit"] >= 70) & (r["normal_all"] <= 60)], "hit_all", 25)
    boost = diverse(r[(r["normal_all"] <= 15) & (r["min_lift"] >= 2) & (r["hit_all"] >= 3)], "lift_all", 25)
    equal = diverse(r[r["kind"] == "equal"], "lift_all", 25)
    per_bet = []
    for o in POPULAR:
        d = r[r["outcome"] == o]
        if len(d):
            per_bet.append(diverse(d, "hit_all", 5, key="rule").assign(_o=o))
    per_bet = pd.concat(per_bet)
    allr = r.sort_values("lift_all", ascending=False).head(20000)

    howto = pd.DataFrame({"How to read this rule book": [
        "Each row is a rule: WHEN the closing odds look like the first column, the BET in the second column hits more "
        "often than usual.",
        "Hit % is shown for three periods separately. A rule is only included if it beat the normal rate clearly in ALL "
        "three: 2024/25 + 2024, 2025/26 + 2025 and 2026/27 + 2026 so far.",
        "'Normally %' = how often that bet hits across all matches. 'Lift' = Hit all % / Normally %.",
        "'Nesine's price says %' = the chance Nesine's own price gives the bet in those same matches (cut removed). "
        "It is usually close to the hit rate: the price already knows. 'Return per 100 TL' shows what flat stakes "
        "would have made; almost all are negative.",
        "'≈ (within 0.10)' means the two odds differ by at most 0.10. 'cheaper than' means the first odds are lower.",
        f"{len(r):,} rules with 500+ matches passed. Sheets: best by hit rate, long-shot boosters, equal-odds rules, "
        "best rules for popular bets, and the 20,000 strongest rules (use the filter arrows).",
    ]})
    sheets = {"How to read": howto, "Highest hit rates": table(high), "Long-shot boosters": table(boost),
              "Equal-odds rules": table(equal), "Popular bets": table(per_bet),
              "All rules (top 20000)": table(allr)}
    with pd.ExcelWriter(OUT / "rules_book.xlsx", engine="openpyxl") as xw:
        for name, df in sheets.items():
            df.to_excel(xw, sheet_name=name[:31], index=False)
            ws = xw.sheets[name[:31]]
            ws.freeze_panes = "A2"
            if name != "How to read":
                ws.auto_filter.ref = ws.dimensions
            for col in ws.columns:
                ws.column_dimensions[col[0].column_letter].width = max(
                    10, min(70, max(len(str(c.value if c.value is not None else "")) for c in col) + 2))
            if name == "How to read":
                ws.column_dimensions["A"].width = 150

    # chart: a few example rules, hit rate vs normal rate
    ex = pd.concat([high.head(4), boost.head(3), equal.head(3)])
    fig, ax = plt.subplots(figsize=(12, 8))
    y = np.arange(len(ex))[::-1]
    ax.barh(y + .2, ex["hit_all"], height=.38, color=BLUE, label="hit rate when the rule is met")
    ax.barh(y - .2, ex["normal_all"], height=.38, color=GRAY, label="normal hit rate")
    for yy, h, n in zip(y, ex["hit_all"], ex["normal_all"]):
        ax.text(h + .8, yy + .2, f"{h:.0f}%  (×{h / n:.1f})", va="center", fontsize=9, color=INK2)
    labels = [f"{t}\n→ {b}" for t, b in zip(ex["rule"], ex["then"])]
    ax.set_yticks(y, [l if len(l) < 95 else l[:92] + "…" for l in labels], fontsize=8)
    ax.set_xlabel("% of matches")
    ax.grid(axis="y", visible=False)
    ax.legend(loc="lower right", frameon=False)
    ax.set_title("Examples from the rule book (hold in all three periods)")
    fig.tight_layout(); fig.savefig(OUT / "rules_examples.png", dpi=150); plt.close(fig)

    pd.set_option("display.width", 250); pd.set_option("display.max_colwidth", 80)
    for n in ("Highest hit rates", "Long-shot boosters", "Equal-odds rules"):
        print(f"\n== {n}\n", sheets[n].head(10).to_string(index=False))
    print("\n== Popular bets\n", sheets["Popular bets"].to_string(index=False))


if __name__ == "__main__":
    main()
