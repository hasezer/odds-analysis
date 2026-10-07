"""Nesine coverage per league-season (HISTORY_REPORT.md).

For every league and season:
  1. season fixture page on www.mackolik.com: all matches incl. playoff stages (count, dates, stages);
  2. the date listing (livescores JSON) of the season's busiest matchday: how many of the league's matches carry an
     iddaa code (= Nesine offered the match);
  3. up to --per-season of those coded matches: arsiv odds popup (markets, winner marks, MBS; must be the same match
     by uuid), key events (goals/cards) and the statistics page (corners, cards).
The new-site odds JSON is NOT used for coverage: it is empty for some matches whose popup is complete.
Read-only, <= 1 request/second, resumable (one JSON line per league-season).

Usage: PYTHONPATH=src python scripts/history_coverage.py --out coverage.jsonl [--per-season 3]
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import html
import json
import random
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from history_leagues import ROOT, WWW, season_labels, season_matches

from odds_analysis import http as H
from odds_analysis.parsers import parse_odds_popup

TR_OFFSET = dt.timedelta(hours=3)
ODDS_START = "2019-09-01"  # iddaa codes start 2019-08-01 but are thin during August 2019


def tr_date(utc: str) -> str:
    return (dt.datetime.fromisoformat(utc) + TR_OFFSET).date().isoformat()


def pick_day(played: list[dict]) -> str:
    """Busiest matchday in the middle of the season and inside the odds history.

    The final round is avoided (Nesine offers fewer markets when all matches kick off together), as are the first
    weeks of history (August 2019).
    """
    all_days = sorted({tr_date(m["utc"]) for m in played})
    lo, hi = len(all_days) // 10, len(all_days) - max(1, len(all_days) // 10)
    middle = set(all_days[lo:hi]) or set(all_days)
    days = collections.Counter(tr_date(m["utc"]) for m in played)
    for pool in ({d for d in middle if d >= ODDS_START}, {d for d in all_days if d >= ODDS_START}, set(all_days)):
        if pool:
            return max(sorted(pool), key=lambda d: days[d])
    raise ValueError("no played matches")


def listing(c: H.MackolikClient, date: str) -> dict | None:
    r = c.get(f"{WWW}/perform/p0/ajax/components/competition/livescores/json?sports%5B%5D=Soccer&matchDate={date}",
              referer=f"{WWW}/canli-sonuclar", backoff=(5, 15))
    if not r.ok:
        return None
    return json.loads(r.text).get("data") or {}


def check(c: H.MackolikClient, uuid: str, code: int) -> dict:
    res: dict = {"uuid": uuid, "code": code}
    r = c.get(H.odds_popup_path(code), backoff=(5, 15))
    if r.ok:
        p = parse_odds_popup(r.text)
        pu = (json.loads(r.text.lstrip("﻿"))["data"]["matches"] or [{}])[0].get("uuid")
        res["popup_same_match"] = pu == uuid
        if pu == uuid:
            res["markets"] = len({o["market_id"] for o in p["outcomes"]})
            res["selections"] = len(p["outcomes"])
            res["decided_markets"] = len({o["market_id"] for o in p["outcomes"] if o["highlight"]})
            res["mbs"] = sorted({o["mbs"] for o in p["outcomes"] if o["mbs"] is not None})
            res["market_names"] = sorted({o["market_name"] for o in p["outcomes"]})
    else:
        res["popup_error"] = r.error
    r = c.get(f"{WWW}/ajax/football/key-events?ajaxViewName=events&matchId={uuid}", backoff=(5, 15))
    ev = (json.loads(r.text).get("data") or {}).get("keyEvents") if r.ok else None
    if ev is not None:
        res["events"] = len(ev)
        res["goal_events"] = sum(e.get("type") == "goal" for e in ev)
        res["card_events"] = sum(e.get("type") == "card" for e in ev)
    else:
        res["events_error"] = r.error
    r = c.get(f"{WWW}/mac/x/istatistik/{uuid}", backoff=(5, 15), follow_redirects=True)  # 301 -> real slug
    if r.ok:
        t = html.unescape(re.sub(r"<[^>]+>", " ", r.text))
        mc = re.search(r"Korner\s+(\d+)\s+(\d+)", t)
        my = re.search(r"Sarı Kart\s+(\d+)\s+(\d+)", t)
        res["corners"] = [int(mc[1]), int(mc[2])] if mc else None
        res["yellow_cards"] = [int(my[1]), int(my[2])] if my else None
    else:
        res["stats_error"] = r.error
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--per-season", type=int, default=3)
    a = ap.parse_args()
    leagues = yaml.safe_load((ROOT / "config" / "leagues.yaml").read_text(encoding="utf-8"))["leagues"]
    out = Path(a.out)
    done = set()
    if out.exists():
        done = {(j["league"], j["season"]) for j in map(json.loads, out.read_text().splitlines())}
    rng = random.Random(11)
    with H.MackolikClient() as c, out.open("a", encoding="utf-8") as f:
        for lg in leagues:
            mk = lg["mackolik"]
            for label in season_labels(lg):
                if (lg["key"], label) in done:
                    continue
                comp = next((x for x in lg.get("extra") or [] if x["season"] == label), mk)
                page_label = label
                ms = season_matches(c, comp["slug"], comp["competition_id"], label)
                fallback = f"{label}-{int(label) + 1}" if "-" not in label else None
                if not ms and lg["calendar_year"] and fallback and fallback not in season_labels(lg):
                    # e.g. Argentina's 2019/20 Superliga is filed as "2019-2020"
                    page_label = fallback
                    ms = season_matches(c, comp["slug"], comp["competition_id"], page_label)
                rec = {"league": lg["key"], "season": label, "competition": comp.get("name", lg["name"]), "page_label": page_label, "matches": len(ms),
                       "played": sum(m["status"] == "Played" for m in ms),
                       "stages": dict(collections.Counter(m["stage"] for m in ms)),
                       "dates": sorted(m["utc"][:10] for m in ms), "listing": None, "samples": []}
                played = [m for m in ms if m["status"] == "Played"]
                if played:
                    day = pick_day(played)
                    data = listing(c, day)
                    if data is not None:
                        lm = [m for m in (data.get("matches") or {}).values()
                              if m.get("competitionId") == comp["competition_id"]]
                        coded = [m for m in lm if m.get("iddaaCode")]
                        rec["listing"] = {"date": day, "league_matches": len(lm), "with_code": len(coded)}
                        for m in rng.sample(coded, min(a.per_season, len(coded))):
                            rec["samples"].append(check(c, m["id"], int(m["iddaaCode"])))
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                f.flush()
                print(lg["key"], label, len(ms), rec["listing"], [s.get("markets") for s in rec["samples"]], flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
