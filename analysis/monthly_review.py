"""Monthly review of the strategy book: every strategy's live record (tracker.py) against its book evidence.

For each strategy with live picks (finished matches from the day after it was added, at closing odds):
- won vs expected (the hit rate of its latest season in the book) and the chance of doing this badly (or this well)
  by luck alone (binomial);
- far behind: at least MIN_PICKS picks and a chance below P_RETIRE -> listed under 'retire' in
  analysis/live_review.yaml; build_strategy_book.py then retires it (kept in the book with date and reason, never
  deleted; the daily scan skips it). `python analysis/build_strategy_book.py --live-only` applies the list to the
  current book without a full rebuild (no caches needed);
- behind (chance below P_WARN): shown as a warning only; ahead (chance of doing this well below P_WARN): shown.
Writes analysis/output/monthly_review.md / .xlsx; analysis/live_review.yaml changes only when a strategy is newly
flagged (entries are only added, never removed).

    python analysis/monthly_review.py
"""
import datetime as dt
from pathlib import Path
import sys

import numpy as np
import pandas as pd
from scipy.stats import binom
import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import tracker  # noqa: E402

LIVE = HERE / "live_review.yaml"
MIN_PICKS = 50
P_RETIRE = 0.001          # ~0.2 strategies a month flagged by luck alone among ~230
P_WARN = 0.01
HEADER = ("# Written by analysis/monthly_review.py: strategies whose live record is far below their book evidence.\n"
          "# build_strategy_book.py retires every id under 'retire' (date and reason kept). Do not edit by hand.\n")


def review(summ):
    s = summ[summ["expected_hit_pct"].notna()].copy()
    e = s["expected_hit_pct"].astype(float) / 100
    s["expected_won"] = s["picks"] * e
    s["chance this bad by luck"] = binom.cdf(s["hits"], s["picks"], e)
    s["chance this good by luck"] = binom.sf(s["hits"] - 1, s["picks"], e)
    s["verdict"] = np.select(
        [s["picks"] < 20,
         (s["picks"] >= MIN_PICKS) & (s["chance this bad by luck"] < P_RETIRE),
         s["chance this bad by luck"] < P_WARN,
         s["chance this good by luck"] < P_WARN],
        ["too few picks yet", "far behind: retire", "behind: watch", "ahead"], "on track")
    return s.sort_values(["verdict", "chance this bad by luck"])


def update_live(s, today):
    live = (yaml.safe_load(LIVE.read_text()) if LIVE.exists() else None) or {}
    live.setdefault("retire", [])
    live.setdefault("reviews", [])
    listed = {x["id"] for x in live["retire"]}
    new = []
    for _, r in s[s["verdict"] == "far behind: retire"].iterrows():
        if r["strategy"] in listed:
            continue
        reason = (f"live record far below its book evidence: {r['hits']} of {r['picks']} won ({r['hit_pct']:.1f}%) "
                  f"vs {float(r['expected_hit_pct']):.1f}% expected (monthly review {today})")
        new.append({"id": r["strategy"], "flagged_on": today, "picks": int(r["picks"]), "won": int(r["hits"]),
                    "expected_hit_pct": float(r["expected_hit_pct"]),
                    "chance_by_luck": round(float(r["chance this bad by luck"]), 6), "reason": reason})
    if not new:                    # the file changes only when a strategy is newly flagged (then a PR is due)
        return new
    live["retire"] += new
    live["reviews"].append({"date": today, "checked": int(len(s)), "new_retirements": len(new),
                            "behind": int((s["verdict"] == "behind: watch").sum()),
                            "ahead": int((s["verdict"] == "ahead").sum())})
    LIVE.write_text(HEADER + yaml.safe_dump(live, allow_unicode=True, sort_keys=False, width=120))
    return new


def write(s, picks, summ, start, sysr, new, today):
    out = HERE / "output" / "monthly_review.md"
    out.parent.mkdir(exist_ok=True)
    L = [f"# Monthly strategy-book review — {dt.date.fromisoformat(today):%d %b %Y}", "",
         f"Every strategy replayed as stored on matches played after it was added (from {start:%d %b %Y}), at "
         "Nesine's closing odds, compared with the hit rate its book evidence promises.", ""]
    if not len(s):
        L.append("No strategy has live picks with a known expected hit rate yet.")
    else:
        L += [f"**{len(s)} strategies with picks:** {int(s['picks'].sum())} picks, {int(s['hits'].sum())} won, "
              f"{s['expected_won'].sum():.0f} expected.", ""]
        L += ["| Verdict | Strategies |", "|---|---|"]
        L += [f"| {v} | {n} |" for v, n in s["verdict"].value_counts().items()]
        for v, title in (("far behind: retire", "Far behind: retired by this review (kept in the book as retired)"),
                         ("behind: watch", "Behind: watch (not retired)"), ("ahead", "Ahead of their evidence")):
            g = s[s["verdict"] == v]
            if not len(g):
                continue
            L += ["", f"## {title}", ""]
            for _, r in g.iterrows():
                L.append(f"- {r['summary']} — {r['hits']} of {r['picks']} won ({r['hit_pct']:.1f}%), expected "
                         f"{float(r['expected_hit_pct']):.1f}% ({r['expected_won']:.1f} wins), "
                         f"{tracker.ret_txt(r['return_per_100'])}")
    L += tracker.system_lines(sysr)
    L += ["", f"Retired only with {MIN_PICKS}+ picks and less than a {P_RETIRE:.1%} chance of doing that badly by "
          "luck. Small samples swing a lot: a long-odds strategy needs several hundred picks to judge."]
    if new:
        L += ["", f"New in analysis/live_review.yaml: {', '.join(x['id'] for x in new)}. Apply with "
              "`python analysis/build_strategy_book.py --live-only` and open a PR."]
    out.write_text("\n".join(L) + "\n")
    with pd.ExcelWriter(out.with_suffix(".xlsx")) as xw:
        s.round(4).to_excel(xw, sheet_name="Review", index=False)
        picks.round({"closing_odds": 2, "return": 3}).to_excel(xw, sheet_name="Every pick", index=False)
        if sysr is not None and len(sysr):
            sysr.round(3).to_excel(xw, sheet_name="System coupons", index=False)
    return out


def main():
    today = dt.date.today().isoformat()
    picks, summ, start, sysr = tracker.run()
    s = review(summ) if len(summ) else pd.DataFrame(columns=["verdict", "picks", "hits", "expected_won"])
    new = update_live(s, today) if len(s) else []
    out = write(s, picks, summ, start, sysr, new, today)
    print(out, f"{len(s)} strategies reviewed, {len(new)} newly flagged to retire")


if __name__ == "__main__":
    main()
