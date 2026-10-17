"""Closing-price check of the owner's own bets: did the odds taken beat Nesine's closing odds?

Beating the closing price on average (closing-line value, CLV) is the best single sign of a long-term winner: the
closing price holds the most information, so getting more than it again and again means getting value.
Input: analysis/my_bets.csv, one row per bet (a system coupon: one row per game); lines starting with # are ignored.
    date        kick-off date in Turkey, YYYY-MM-DD
    home, away  team names as Nesine shows them (matched to our matches by similarity, kick-off date +-1 day)
    bet         the selection as market|line|selection, the labels of data/analysis_flat, e.g. 1X2||1,
                OU|2.5|OVER, BTTS||YES, HT_2H_BTTS||YES/YES, HT_FT||X/1, CORRECT_SCORE||2-1, 1X2_AND_OU|2.5|X&OVER
    odds_taken  the decimal odds the bet was placed at
    stake       optional (default 1); note: optional free text
Per bet: the matched match, Nesine's closing odds, CLV % (odds taken / closing odds - 1), won or lost, profit.
Summary: average CLV, share of bets that beat the closing price, hit rate vs the closing price's break-even, and
the return per 100 at the odds taken vs at the closing odds. Writes output/my_bets.xlsx.

    python analysis/my_bets.py [path to csv]
"""
from difflib import SequenceMatcher
from pathlib import Path
import sys
import unicodedata

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import load  # noqa: E402

COLS = ["date", "home", "away", "bet", "odds_taken", "stake", "note"]


def norm(s):
    s = unicodedata.normalize("NFKD", str(s).lower().replace("ı", "i")).encode("ascii", "ignore").decode()
    return " ".join(s.replace(".", " ").replace("-", " ").split())


def sim(a, b):
    a, b = norm(a), norm(b)
    return 1.0 if a and (a in b or b in a) else SequenceMatcher(None, a, b).ratio()


def find_match(r, fx):
    day = pd.Timestamp(r["date"])
    c = fx[(fx["day"] >= day - pd.Timedelta(days=1)) & (fx["day"] <= day + pd.Timedelta(days=1))]
    if not len(c):
        return None, 0.0
    score = c.apply(lambda x: (sim(r["home"], x["home_team_tr"]) + sim(r["away"], x["away_team_tr"])) / 2, axis=1)
    best = score.idxmax()
    return (c.loc[best], float(score[best])) if score[best] >= 0.6 else (None, float(score[best]))


def run(path):
    bets = pd.read_csv(path, comment="#", dtype=str).reindex(columns=COLS)
    bets = bets[bets["date"].notna() & bets["bet"].notna()].reset_index(drop=True)
    if not len(bets):
        print(f"no bets in {path} yet")
        return pd.DataFrame(), pd.DataFrame()
    bets["odds_taken"] = pd.to_numeric(bets["odds_taken"], errors="coerce")
    bets["stake"] = pd.to_numeric(bets["stake"], errors="coerce").fillna(1.0)
    f = load.flat()
    fx = f.drop_duplicates("match_id")[["match_id", "league_id", "kickoff_utc", "home_team_tr", "away_team_tr",
                                        "ft_home", "ft_away", "status"]].copy()
    fx["day"] = fx["kickoff_utc"].dt.tz_convert("Europe/Istanbul").dt.tz_localize(None).dt.normalize()
    rows = []
    for _, r in bets.iterrows():
        mk, line, sk = (r["bet"].split("|") + ["", ""])[:3]
        x, score = find_match(r, fx)
        row = dict(r)
        row.update({"matched": x is not None, "match score": round(score, 2)})
        if x is not None:
            sel = f[(f["match_id"] == x["match_id"]) & (f["market_key"] == mk) & (f["selection_key"] == sk)]
            sel = sel[sel["line"].isna()] if line == "" else sel[np.isclose(sel["line"], float(line))]
            row.update({"league": x["league_id"], "match": f"{x['home_team_tr']} - {x['away_team_tr']}",
                        "kick-off (Turkey)": str(x["day"].date()),
                        "score": f"{x['ft_home']:.0f}-{x['ft_away']:.0f}" if pd.notna(x["ft_home"]) else ""})
            if len(sel):
                s = sel.iloc[0]
                row.update({"closing_odds": s["closing_odds"], "won": s["hit"]})
        rows.append(row)
    d = pd.DataFrame(rows).reindex(columns=COLS + ["matched", "match score", "league", "match", "kick-off (Turkey)",
                                                   "score", "closing_odds", "won"])
    d["CLV %"] = (d["odds_taken"] / d["closing_odds"] - 1) * 100
    d["profit"] = np.where(d["won"].notna(), d["stake"] * (d["won"] * d["odds_taken"] - 1), np.nan)
    ok = d["CLV %"].notna()
    st = d["won"].notna() & ok
    summ = pd.DataFrame([{
        "bets": len(d), "matched to a match": int(d["matched"].sum()), "with a closing price": int(ok.sum()),
        "average CLV %": d.loc[ok, "CLV %"].mean(), "beat the closing price %": (d.loc[ok, "CLV %"] > 0).mean() * 100,
        "settled": int(st.sum()), "hit %": d.loc[st, "won"].mean() * 100,
        "break-even at closing odds %": (1 / d.loc[st, "closing_odds"]).mean() * 100,
        "return per 100 at odds taken": d.loc[st, "profit"].sum() / d.loc[st, "stake"].sum() * 100,
        "return per 100 at closing odds":
            (d.loc[st, "stake"] * (d.loc[st, "won"] * d.loc[st, "closing_odds"] - 1)).sum()
            / d.loc[st, "stake"].sum() * 100}])
    out = HERE / "output" / "my_bets.xlsx"
    out.parent.mkdir(exist_ok=True)
    with pd.ExcelWriter(out) as xw:
        summ.round(2).to_excel(xw, sheet_name="Summary", index=False)
        d.round(3).to_excel(xw, sheet_name="Every bet", index=False)
    unmatched = d[~d["matched"].astype(bool)]
    if len(unmatched):
        print("not matched (check the team names / date):")
        print(unmatched[["date", "home", "away", "match score"]].to_string(index=False))
    print(summ.round(2).T.to_string())
    return d, summ


if __name__ == "__main__":
    run(Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "my_bets.csv")
