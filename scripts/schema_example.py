"""Build every SCHEMA.md table for a few real finished matches (into a scratch folder) and print example rows.

Uses the same code the backfill will use: date listing -> matches/teams, key events -> events, statistics page ->
stats, arsiv odds popup (checked by uuid) -> odds (closing_history) + settlements, then analysis_flat and the
quality checks. Read-only on Mackolik, <= 1 request/second.

Usage: PYTHONPATH=src python scripts/schema_example.py --date 2025-10-18 --league ENG-1 --limit 2 --out /tmp/x
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from odds_analysis import flat, ingest, quality, store  # noqa: E402
from odds_analysis import http as H  # noqa: E402
from odds_analysis.schema import season_label  # noqa: E402

WWW = "https://www.mackolik.com"


def season_for(lg: dict, d: date) -> str:
    if lg["calendar_year"]:
        return str(d.year)
    return season_label(d.year if d.month >= 7 else d.year - 1, False)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--league", required=True)
    ap.add_argument("--limit", type=int, default=2)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    leagues = yaml.safe_load((ROOT / "config" / "leagues.yaml").read_text(encoding="utf-8"))["leagues"]
    pipe = yaml.safe_load((ROOT / "config" / "pipeline.yaml").read_text(encoding="utf-8"))
    rules = yaml.safe_load((ROOT / "config" / "card_rules.yaml").read_text(encoding="utf-8"))
    lg = next(x for x in leagues if x["league_id"] == a.league)
    d = date.fromisoformat(a.date)
    season = season_for(lg, d)
    root = a.out
    store.upsert("leagues", ingest.league_rows(leagues), root=root)
    sett = pipe.get("settlement", {})
    unsettleable = {f for u in sett.get("unsettleable", []) if u["league_id"] == a.league and u["season"] == season
                    for f in u["families"]}

    with H.MackolikClient() as c:
        r = c.get(f"{WWW}/perform/p0/ajax/components/competition/livescores/json?sports%5B%5D=Soccer&matchDate={a.date}",
                  referer=f"{WWW}/canli-sonuclar")
        data = json.loads(r.text)["data"]
        comp = data["competitions"][lg["mackolik"]["competition_id"]]
        picked = [m for m in data["matches"].values()
                  if m["competitionId"] == lg["mackolik"]["competition_id"] and m.get("iddaaCode")][: a.limit]
        for m in picked:
            stage = ((comp.get("stage") or {}).get(str(m.get("stageId"))) or {}).get("name")
            match = ingest.match_row(m, league_id=a.league, season=season, stage=stage)
            ke = c.get(f"{WWW}/ajax/football/key-events?ajaxViewName=events&matchId={m['id']}")
            events = ingest.event_rows(m["id"], (json.loads(ke.text).get("data") or {}).get("keyEvents") or [])
            ingest.apply_extra_time(match, events)
            page = c.get(f"{WWW}/mac/x/istatistik/{m['id']}", follow_redirects=True)
            stats = ingest.stats_rows(m["id"], page.text, events) if page.ok else []
            match["stadium"] = ingest.stadium(page.text) if page.ok else None
            pop = c.get(H.odds_popup_path(m["iddaaCode"]), backoff=(5, 15, 45))
            if not pop.ok:
                print(f"skip {m['id']}: popup {pop.error}", file=sys.stderr)
                continue
            odds, outs = ingest.odds_rows(match, pop.text)
            ctx = ingest.engine_ctx(match, events, stats, rules)
            sets = ingest.settlement_rows(match, outs, ctx, store.now_utc(), unsettleable_families=unsettleable,
                                          unverified_keys=set(sett.get("unverified_markets", [])))
            part = {"season": season, "league_id": a.league}
            store.upsert("teams", ingest.team_rows([match]), root=root)
            store.upsert("matches", [match], root=root)
            store.upsert("markets", ingest.market_rows(outs, season), root=root)
            for name, rows in (("odds", odds), ("settlements", sets), ("events", events), ("stats", stats)):
                store.upsert(name, [{**x, **part} for x in rows], root=root)
            print(f"{match['_home_tr']} - {match['_away_tr']}: {len(odds)} odds, {len(events)} events", file=sys.stderr)
    flat.rebuild(season, a.league, root)
    print(json.dumps(quality.run_checks([(season, a.league)], "backfill", store.now_utc().isoformat(), root)), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
