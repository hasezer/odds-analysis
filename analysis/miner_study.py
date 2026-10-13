"""Charts and tables for the round-2/3 signal hunt (results in analysis/MINER_REPORT.md).

Needs the caches built by miner.py (and miner.py --shuffle), book_models.py (3 shards), learned_goals.py, arb_scan.py.
Writes analysis/output/miner_*.png and analysis/output/miner_study.xlsx.
"""
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from first_look import BLUE, GRAY, INK2, ORANGE, OUT, SURFACE  # noqa: E402
from htft_data import CACHE  # noqa: E402


def main():
    real = pd.read_parquet(CACHE / "miner_hits.parquet")
    shuf = pd.read_parquet(CACHE / "miner_hits_shuffled.parquet")
    book = pd.concat([pd.read_parquet(f) for f in sorted(CACHE.glob("book_models_*of3.parquet"))])
    lg = pd.read_parquet(CACHE / "learned_goals.parquet")
    arb = pd.read_parquet(CACHE / "arb_scan.parquet")
    arb["kickoff_utc"] = arb["kickoff_utc"].dt.tz_localize(None)        # Excel can't store time zones

    # 1. funnel: real vs shuffled
    fig, ax = plt.subplots(figsize=(10, 5.5))
    labels = ["passed 'find'\n(2024/25 + 2024)", "also passed 'confirm'\n(2025/26 + 2025)"]
    rv = [len(real), int(real["confirmed"].sum())]
    sv = [len(shuf), int(shuf["confirmed"].sum())]
    x = np.arange(2)
    ax.bar(x - .2, rv, .38, color=BLUE, label="real data")
    ax.bar(x + .2, sv, .38, color=GRAY, label="shuffled data (pure luck)")
    for i in range(2):
        ax.text(x[i] - .2, rv[i] + 5, f"{rv[i]}", ha="center", color=INK2)
        ax.text(x[i] + .2, sv[i] + 5, f"{sv[i]}", ha="center", color=INK2)
    ax.set_xticks(x, labels)
    ax.set_ylabel("price patterns")
    ax.grid(axis="x", visible=False)
    ax.legend(frameon=False, loc="upper right")
    ax.set_title("1. ~21 million price-pair patterns: real data does no better than luck")
    fig.tight_layout(); fig.savefig(OUT / "miner_1_funnel.png", dpi=150); plt.close(fig)

    # 2. what the 'find' winners did next season
    fig, ax = plt.subplots(figsize=(10, 7))
    ax.scatter(real["roi_A"], real["roi_B"], s=np.clip(real["bets_A"] / 5, 15, 150), color=BLUE, alpha=.6,
               edgecolor=SURFACE, linewidth=1)
    ax.axhline(0, color=INK2, lw=1)
    ax.set_xlabel("Return in 2024/25 + 2024, where the pattern was found (%)")
    ax.set_ylabel("Return the next season, 2025/26 + 2025 (%)")
    ax.text(real["roi_A"].max(), real["roi_B"].mean() + 3, f"average next season: {real['roi_B'].mean():.0f}%",
            ha="right", color=INK2)
    ax.axhline(real["roi_B"].mean(), color=ORANGE, lw=1.5, ls="--")
    ax.set_title("2. The miner's 127 'winners' lost money the next season")
    fig.tight_layout(); fig.savefig(OUT / "miner_2_next_season.png", dpi=150); plt.close(fig)

    # 3. sure-bet scan
    v = arb["best_guaranteed_return"].dropna() * 100
    fig, ax = plt.subplots(figsize=(10, 5.5))
    ax.hist(v.clip(-25, 5), bins=np.arange(-25, 5.5, .5), color=BLUE)
    ax.axvline(0, color=INK2, lw=1)
    ax.set_xlabel("Best guaranteed return from any mix of Nesine bets on one match (%)  — right of 0 = sure bet")
    ax.set_ylabel("matches")
    ax.set_title(f"3. Sure-bet scan, {len(v):,} matches: none above 0% except one data error")
    fig.tight_layout(); fig.savefig(OUT / "miner_3_surebets.png", dpi=150); plt.close(fig)

    score = pd.DataFrame([
        ("Price-pair miner (every pair of 162 prices × 11 bands × 162 bets)", "~21 million", len(real),
         int(real["confirmed"].sum()), f"luck control: {len(shuf)} / {int(shuf['confirmed'].sum())}"),
        ("Whole-price-list models (logistic, boosting, similar-matches) × 162 bets", len(book), "—",
         int(book["passed_B"].sum()), ""),
        ("Learned goal model → every goal bet", len(lg), "—", int(lg["passed_B"].sum()),
         "2 earlier 'passes' were a data error (fixed)"),
        ("Internal sure bets (all goal markets of a match combined)", len(v), "—",
         int((v > 0).sum()), "the 1 'sure bet' is the same data error"),
    ], columns=["idea", "tested", "passed find", "passed confirm", "note"])
    with pd.ExcelWriter(OUT / "miner_study.xlsx", engine="openpyxl") as xw:
        for name, df in {"Scorecard": score, "Miner finds (real)": real.round(2),
                         "Miner finds (shuffled)": shuf.round(2), "Whole-book models": book.round(2),
                         "Learned goal model": lg.round(2),
                         "Sure-bet scan (top 200)": arb.sort_values("best_guaranteed_return",
                                                                     ascending=False).head(200)}.items():
            df.to_excel(xw, sheet_name=name[:31], index=False)
            ws = xw.sheets[name[:31]]
            ws.freeze_panes = "A2"
            for col in ws.columns:
                ws.column_dimensions[col[0].column_letter].width = max(
                    10, min(60, max(len(str(c.value if c.value is not None else "")) for c in col) + 2))
    print(score.to_string(index=False))


if __name__ == "__main__":
    main()
