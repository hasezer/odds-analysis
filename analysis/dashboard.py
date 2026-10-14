"""Daily dashboard: upcoming matches, their Nesine odds, and the picks our rule book makes on those odds.

python analysis/dashboard.py [--data-dir DIR] [--days 4] [--out analysis/output/dashboard.html]

--data-dir  where the upcoming matches and snapshot odds are (default: the repo's data/). The snapshot job
            (python -m odds_analysis snapshot) writes them; it can be pointed at a copy with ODDS_DATA_DIR.
Rules: cache/rules_deep.parquet (+ _luck, rules_forward) built by rules_deep.py / rules_forward.py.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import miner_data as mdat  # noqa: E402
import rules_deep as rd  # noqa: E402
from htft_data import CACHE  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
TR = timezone(timedelta(hours=3))
SNAPSHOT_TYPES = ["opening_snapshot", "intraday_snapshot", "closing_snapshot"]
WATCH = {"HT/FT 2/X", "Score 2-1", "Score 3-2", "Score 3-0", "Score 0-2", "1st-half score 2-1"}
CAPS = {"HT_FT": 34.0, "CORRECT_SCORE": 120.0, "1X2_AND_OU": 34.5, "1X2_AND_BTTS": 34.5,
        "HT_1X2_AND_HT_BTTS": 34.5, "HT_1X2_AND_HT_OU": 34.5, "HT_CORRECT_SCORE": 60.0}
GROUP = {"HT/FT": "HT/FT", "Score": "Correct score", "1st-half score": "1st-half score",
         "Total goals": "Goals", "Over": "Goals", "Under": "Goals", "Both teams score": "Both teams score",
         "Home win": "Result", "Draw": "Result", "Away win": "Result", "1st-half draw": "Result"}
TR_BET = {"Home win": "MS 1", "Draw": "MS X", "Away win": "MS 2", "1st-half draw": "İY X",
          "Over 2.5 goals": "2,5 Üst", "Under 2.5 goals": "2,5 Alt", "Over 3.5 goals": "3,5 Üst",
          "Both teams score: yes": "KG Var", "Both teams score: no": "KG Yok", "Total goals 6+": "Toplam gol 6+",
          "Total goals 5+": "Toplam gol 5+", "Both teams score in BOTH halves": "İki yarıda da KG",
          "HT/FT turnaround (1/2 or 2/1)": "İY/MS 1/2 veya 2/1"}


def bet_group(t):
    for k, v in GROUP.items():
        if t.startswith(k):
            return v
    return "Other"


def tr_bet(t):
    if t in TR_BET:
        return TR_BET[t]
    if t.startswith("HT/FT "):
        return "İY/MS " + t[6:].replace("X", "0")
    if t.startswith("Score "):
        return "Skor " + t[6:]
    if t.startswith("1st-half score "):
        return "İY skor " + t[15:]
    return t


def load_upcoming(data_dir: Path, days: int):
    now = pd.Timestamp.now(tz="UTC")
    end = now + pd.Timedelta(days=days)
    m = pd.concat([pd.read_parquet(f) for f in data_dir.glob("matches/season=*/league=*/*.parquet")])
    m = m[(m["status"] == "scheduled") & (m["kickoff_utc"] > now) & (m["kickoff_utc"] <= end)]
    files = [f for f in data_dir.glob("odds/season=*/league=*/date=*/*.parquet")]
    o = pd.concat([pd.read_parquet(f) for f in files]) if files else pd.DataFrame()
    o = o[o["match_id"].isin(m["match_id"]) & o["price_type"].isin(SNAPSHOT_TYPES) & o["odds"].notna()]
    o = o.sort_values("captured_at_utc").drop_duplicates(
        ["match_id", "market_type_id", "line", "handicap_home", "handicap_away", "selection_key"], keep="last")
    teams = pd.read_parquet(data_dir / "teams" / "part-0000.parquet").set_index("team_id")["name_tr"]
    mk = pd.read_parquet(data_dir / "markets" / "part-0000.parquet").drop_duplicates("market_type_id")
    mk = mk.set_index("market_type_id")["name_tr"]
    return m, o, teams, mk


def leagues():
    cfg = yaml.safe_load((ROOT / "config" / "leagues.yaml").read_text())
    items = cfg["leagues"] if isinstance(cfg, dict) and "leagues" in cfg else cfg
    out = {}
    for x in items:
        lid = x.get("league_id") or x.get("id")
        out[lid] = {"tr": x.get("name_tr", lid), "en": x.get("name", lid)}
    return out


def fair_probs(o):
    o = o.copy()
    o["imp"] = 1 / o["odds"]
    key = ["match_id", "market_type_id", "line"]
    s = o.groupby(key, dropna=False)["imp"].transform("sum")
    n = o.groupby(key, dropna=False)["imp"].transform("count")
    div = np.where(o["market_key"] == "DC", s / 2, s)
    o["fair"] = np.where(n >= 2, o["imp"] / div, np.nan)
    return o


def build(data_dir: Path, days: int):
    m, o, teams, mknames = load_upcoming(data_dir, days)
    return compute(m, o, teams, mknames, days)


def compute(m, o, teams, mknames, days, league_names=None):
    """Picks for the matches in m (columns: match_id, league_id, kickoff_utc, home_team_id, away_team_id) from their
    odds rows o (match_id, market_type_id, market_key, line, selection_key, selection_name_tr, odds,
    captured_at_utc). teams maps team id -> name, mknames market_type_id -> Turkish market name."""
    o = fair_probs(o)
    o["lab"] = [mdat.label(a, b, c) for a, b, c in zip(o["market_key"], o["line"], o["selection_key"])]
    z = mdat.build()
    names = list(z["names"])
    spec, lab, _ = rd.atoms(z)
    _, _, price_lab = rd.build_targets(z["match_ids"])

    m = m.sort_values("kickoff_utc").reset_index(drop=True)
    idx = {mid: i for i, mid in enumerate(m["match_id"])}
    O = np.full((len(m), len(names)), np.nan, np.float32)
    col = {n: j for j, n in enumerate(names)}
    for r in o.itertuples(index=False):
        if r.lab in col and r.match_id in idx:
            O[idx[r.match_id], col[r.lab]] = r.odds
    X = rd.masks(spec, O) > 0 if len(m) else np.zeros((0, len(spec)), bool)

    rules = pd.read_parquet(CACHE / "rules_deep.parquet")
    luck = pd.read_parquet(CACHE / "rules_deep_luck.parquet").set_index("target")
    share = (luck["kept_by_luck"] / luck["kept"].clip(lower=1))
    rating = share.map(lambda s: "very reliable" if s < .02 else "reliable" if s < .10 else "mixed" if s < .5
                       else "unreliable").to_dict()
    rules = rules[rules["target"].map(lambda t: rating.get(t) in ("very reliable", "reliable", "mixed"))]
    at = rules["atoms"].str.split(",").map(lambda v: [int(x) for x in v])
    A = np.full((len(rules), 3), -1)
    for i, v in enumerate(at):
        A[i, :len(v)] = v
    fires = np.ones((len(m), len(rules)), bool)
    for k in range(3):
        a = A[:, k]
        has = a >= 0
        fires[:, has] &= X[:, a[has]]
    rules = rules.reset_index(drop=True)
    rules["cons_hit"] = np.minimum(rules["hit_all"], rules["hit_C"])

    # odds by match for the page (every market, Turkish names)
    odds_by = {}
    for mid, g in o.groupby("match_id"):
        rows = []
        for r in g.sort_values(["market_type_id", "line", "selection_key"]).itertuples(index=False):
            mname = mknames.get(r.market_type_id, r.market_key)
            if pd.notna(r.line) and f"{r.line:g}".replace(".", ",") not in mname:
                mname = f"{mname} {r.line:g}".replace(".", ",")
            cap = r.market_key in CAPS and r.odds >= CAPS[r.market_key]
            rows.append([mname, r.selection_name_tr or r.selection_key, round(float(r.odds), 2),
                         None if pd.isna(r.fair) else round(float(r.fair) * 100, 1), int(cap), r.lab])
        odds_by[mid] = rows

    lg = leagues()
    lg.update(league_names or {})
    out_matches, out_picks = [], []
    for i, mr in m.iterrows():
        mid = mr["match_id"]
        ko = mr["kickoff_utc"].tz_convert(TR)
        fired = np.where(fires[i])[0]
        picks = []
        if len(fired):
            fr = rules.iloc[fired]
            for t, g in fr.groupby("target"):
                lab_t = price_lab.get(t)
                odds_now = fair_now = None
                if lab_t and lab_t in col and not np.isnan(O[i, col[lab_t]]):
                    odds_now = float(O[i, col[lab_t]])
                    fr_o = o[(o["match_id"] == mid) & (o["lab"] == lab_t)]
                    fair_now = None if fr_o.empty or pd.isna(fr_o["fair"].iloc[0]) else float(fr_o["fair"].iloc[0])
                mkt = lab_t.split("|")[0] if lab_t else None
                if odds_now is not None and mkt in CAPS and odds_now >= CAPS[mkt]:
                    continue                                   # capped price: a trap, never a pick
                if lab_t and fair_now is None:
                    continue                                   # bet has a market but no price yet
                g = g.copy()
                if fair_now is not None and "nesine_price_says" in g and g["nesine_price_says"].notna().any():
                    # context check: today's price must look like the prices the rule was learned on
                    ratio = fair_now * 100 / g["nesine_price_says"]
                    g = g[(ratio >= 1 / 1.5) & (ratio <= 1.5)]
                    if g.empty:
                        continue
                    # expected hit today = today's price x HALF of how much the rule beat the price in the past
                    # (careful hit; halved because the forward test showed past edges shrink on new matches)
                    edge = g["cons_hit"] / g["nesine_price_says"]
                    g["est"] = (fair_now * 100 * (1 + 0.5 * (edge - 1))).clip(upper=99)
                else:
                    g["est"] = g["cons_hit"]
                best = g.sort_values(["est", "matches_all"], ascending=False).iloc[0]
                est = float(best["est"])
                value = None if odds_now is None else est / 100 * odds_now - 1
                p = {"m": mid, "bet": t, "bet_tr": tr_bet(t), "group": bet_group(t),
                     "rules": int(len(g)), "rule": best["rule"], "kural": best["kural"],
                     "cond": int(best["conditions"]), "n": int(best["matches_all"]),
                     "hit_all": round(float(best["hit_all"]), 1), "hit_c": round(float(best["hit_C"]), 1),
                     "n_c": int(best["matches_C"]), "normal": round(float(best["normal_all"]), 1),
                     "hit": round(est, 1),
                     "hist_price": None if pd.isna(best.get("nesine_price_says", np.nan)) else round(float(best["nesine_price_says"]), 1),
                     "per": [round(float(best["hit_A"]), 1), round(float(best["hit_B"]), 1),
                             round(float(best["hit_C"]), 1)],
                     "odds": None if odds_now is None else round(odds_now, 2),
                     "price": None if fair_now is None else round(fair_now * 100, 1),
                     "value": None if value is None else round(value * 100, 1),
                     "rating": rating.get(t, ""), "watch": t in WATCH}
                picks.append(p)
        out_picks += picks
        out_matches.append({
            "id": mid, "league": mr["league_id"], "league_tr": lg.get(mr["league_id"], {}).get("tr", mr["league_id"]),
            "date": ko.strftime("%Y-%m-%d"), "time": ko.strftime("%H:%M"),
            "home": teams.get(mr["home_team_id"], mr["home_team_id"]),
            "away": teams.get(mr["away_team_id"], mr["away_team_id"]),
            "odds": odds_by.get(mid, []), "npicks": len(picks)})
    latest = o["captured_at_utc"].max() if len(o) else None
    meta = {"generated": datetime.now(TR).strftime("%Y-%m-%d %H:%M"),
            "odds_time": None if latest is None or pd.isna(latest) else latest.tz_convert(TR).strftime("%Y-%m-%d %H:%M"),
            "matches": len(out_matches), "with_odds": sum(1 for x in out_matches if x["odds"]),
            "picks": len(out_picks), "rules": int(len(rules)), "days": days}
    return {"meta": meta, "matches": out_matches, "picks": out_picks}


def render(data, out: Path):
    tpl = (Path(__file__).resolve().parent / "dashboard_template.html").read_text()
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    out.write_text(tpl.replace("__DATA__", blob))
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", type=Path, default=ROOT / "data")
    ap.add_argument("--days", type=int, default=4)
    ap.add_argument("--out", type=Path, default=ROOT / "analysis" / "output" / "dashboard.html")
    a = ap.parse_args()
    d = build(a.data_dir, a.days)
    print(d["meta"])
    print(render(d, a.out))
