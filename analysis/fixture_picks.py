"""Picks for any Mackolik competition on one date (e.g. today's Champions League), without storing anything.

python analysis/fixture_picks.py --competition 4oogyu6o156iphvdvphwpck10 --date 2026-10-14 \
    --name "UEFA Şampiyonlar Ligi" --out analysis/output/ucl_today.html

Uses the project's own Mackolik client and odds parser (src/odds_analysis, read only) to fetch the current Nesine
odds of the competition's matches, keeps them in memory, and runs the Matchday Radar picks engine on them.
Note: the rule book was learned on the project's 26 domestic leagues; other competitions are outside that data.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from odds_analysis import http as H, ingest, www  # noqa: E402
import dashboard  # noqa: E402


def fetch(competition: str, d: date, league_id: str):
    c = H.MackolikClient()
    data = www.listing(c, d) or {}
    now = datetime.now(timezone.utc)
    matches, rows, teams = [], [], {}
    day_lists: dict = {}
    for mm in (data.get("matches") or {}).values():
        if mm.get("competitionId") != competition or not mm.get("iddaaCode"):
            continue
        m = ingest.match_row(mm, league_id=league_id, season="cup", stage=None)
        if m["status"] != "scheduled" or m["kickoff_utc"] <= now:
            continue
        teams[m["home_team_id"]], teams[m["away_team_id"]] = m["_home_tr"], m["_away_tr"]
        try:
            outcomes, source, _ = ingest.fetch_outcomes(c, m, day_lists, np=1)
        except Exception as exc:  # noqa: BLE001
            print(f"odds failed for {m['_home_tr']} - {m['_away_tr']}: {exc}")
            matches.append(m)
            continue
        r, _ = ingest.odds_rows_from(m, outcomes, price_type="opening_snapshot", captured_at=now, source=source)
        rows += r
        matches.append(m)
        print(f"{m['_home_tr']} - {m['_away_tr']}: {len(r)} prices")
    return pd.DataFrame(matches), pd.DataFrame(rows), pd.Series(teams)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--competition", required=True)
    ap.add_argument("--date", type=date.fromisoformat, default=date.today())
    ap.add_argument("--league-id", default="UCL")
    ap.add_argument("--name", default="UEFA Şampiyonlar Ligi")
    ap.add_argument("--title", default="Champions League Radar")
    ap.add_argument("--out", type=Path, default=ROOT / "analysis" / "output" / "fixture.html")
    a = ap.parse_args()
    m, o, teams = fetch(a.competition, a.date, a.league_id)
    mk = pd.read_parquet(ROOT / "data" / "markets" / "part-0000.parquet").drop_duplicates("market_type_id")
    d = dashboard.compute(m, o, teams, mk.set_index("market_type_id")["name_tr"], days=1,
                          league_names={a.league_id: {"tr": a.name, "en": a.name}})
    print(d["meta"])
    out = dashboard.render(d, a.out)
    html = out.read_text()
    out.write_text(html.replace("<title>Matchday Radar</title>", f"<title>{a.title}</title>")
                   .replace("<h1>Matchday Radar</h1>", f"<h1>{a.title}</h1>"))
    print(out)
