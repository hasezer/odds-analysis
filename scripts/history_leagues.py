"""Per-league history check for the 26 configured leagues (HISTORY_REPORT.md).

For every league and season: the season fixture page on www.mackolik.com (all matches incl. playoff stages),
then a small sample of played matches: odds markets (new site), iddaa code -> arsiv odds popup (winner marks),
key events (goals/cards) and the statistics page (corners, cards).
Read-only, <= 1 request/second. Output: one JSON line per league-season (resumable).

Usage: PYTHONPATH=src python scripts/history_leagues.py --out leagues.jsonl [--per-season 2]
"""

from __future__ import annotations

import argparse
import collections
import html
import json
import random
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from odds_analysis import http as H  # noqa: E402
from odds_analysis.parsers import parse_odds_popup  # noqa: E402

WWW = "https://www.mackolik.com"
ROOT = Path(__file__).resolve().parents[1]
MATCH_RE = re.compile(r'"raw":\{"match":\{"id":(\d+),"uuid":"([a-z0-9]+)".*?"round":\{[^}]*?"name":"([^"]*)"'
                      r'.*?"date_time_utc":"([^"]+)","match_time":"[^"]*","status":"([^"]+)","fts_A":(-?\d+|null),'
                      r'"fts_B":(-?\d+|null),"hts_A":(-?\d+|null),"hts_B":(-?\d+|null)')


def season_labels(league: dict) -> list[str]:
    first, last = 2019, 2026
    if league["calendar_year"]:
        labels = [str(y) for y in range(first, last + 1)]
        labels += [f"{y}-{y + 1}" for y in league.get("split_from", []) or []]
        return labels
    return [f"{y}-{y + 1}" for y in range(first, last + 1)]


def season_matches(c: H.MackolikClient, slug: str, cid: str, label: str) -> list[dict]:
    r = c.get(f"{WWW}/puan-durumu/{slug}/{label}/fikstur/{cid}", backoff=(5, 15))
    if not r.ok:  # redirects are not followed: a wrong slug/season is simply "not ok"
        return []
    s = html.unescape(r.text)
    out, seen = [], set()
    for m in MATCH_RE.finditer(s):
        if m[2] in seen:
            continue
        seen.add(m[2])
        stage = json.loads(f'"{m[3]}"') if "\\u" in m[3] else m[3]
        out.append({"id": int(m[1]), "uuid": m[2], "stage": stage, "utc": m[4], "status": m[5],
                    "ft": None if m[6] == "null" else (int(m[6]), int(m[7])),
                    "ht": None if m[8] == "null" else (int(m[8]), int(m[9]))})
    return out


def check_match(c: H.MackolikClient, uuid: str) -> dict:
    res: dict = {"uuid": uuid}
    r = c.get(f"{WWW}/ajax/iddaa/outcomes/soccer/all/{uuid}", backoff=(5,))
    d = json.loads(r.text).get("data") if r.ok else None
    mk = (d or {}).get("markets") or {}
    res["new_site_markets"] = len(mk)
    res["mbs_present"] = sum(bool(m.get("mbc")) for m in mk.values())
    code = None
    if mk:
        r = c.get(f"{WWW}/ajax/iddaa/markets/soccer/all/{uuid}?template=all", backoff=(5,))
        if r.ok:
            m = re.search(r"slipParams[^0-9]*(\d+)\.\d+\$", html.unescape(r.text).replace("\\", ""))
            code = int(m[1]) if m else None
    res["iddaa_code"] = code
    if code:
        r = c.get(H.odds_popup_path(code), backoff=(5,))
        if r.ok:
            p = parse_odds_popup(r.text)
            pu = (json.loads(r.text.lstrip("﻿"))["data"]["matches"] or [{}])[0].get("uuid")
            res["popup_same_match"] = pu == uuid
            if pu == uuid:
                res["popup_markets"] = len({o["market_id"] for o in p["outcomes"]})
                res["popup_decided_markets"] = len({o["market_id"] for o in p["outcomes"] if o["highlight"]})
                res["popup_market_names"] = sorted({o["market_name"] for o in p["outcomes"]})
    r = c.get(f"{WWW}/ajax/football/key-events?ajaxViewName=events&matchId={uuid}", backoff=(5,))
    ev = (json.loads(r.text).get("data") or {}).get("keyEvents") if r.ok else None
    if ev is not None:
        res["events"] = len(ev)
        res["goal_events"] = sum(e.get("type") == "goal" for e in ev)
        res["card_events"] = sum(e.get("type") == "card" for e in ev)
        res["sub_events"] = sum(e.get("type") == "substitute" for e in ev)
    r = c.get(f"{WWW}/mac/x/istatistik/{uuid}", backoff=(5,))
    if r.ok:
        t = html.unescape(re.sub(r"<[^>]+>", " ", r.text))
        mc = re.search(r"Korner\s+(\d+)\s+(\d+)", t)
        my = re.search(r"Sarı Kart\s+(\d+)\s+(\d+)", t)
        res["corners"] = [int(mc[1]), int(mc[2])] if mc else None
        res["yellow_cards_stat"] = [int(my[1]), int(my[2])] if my else None
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--per-season", type=int, default=2)
    a = ap.parse_args()
    leagues = yaml.safe_load((ROOT / "config" / "leagues.yaml").read_text(encoding="utf-8"))["leagues"]
    out = Path(a.out)
    done = set()
    if out.exists():
        done = {(j["league"], j["season"]) for j in map(json.loads, out.read_text().splitlines())}
    rng = random.Random(7)
    with H.MackolikClient() as c, out.open("a", encoding="utf-8") as f:
        for lg in leagues:
            for label in season_labels(lg):
                if (lg["key"], label) in done:
                    continue
                ms = season_matches(c, lg["mackolik"]["slug"], lg["mackolik"]["competition_id"], label)
                played = [m for m in ms if m["status"] == "Played"]
                rec = {"league": lg["key"], "season": label, "matches": len(ms), "played": len(played),
                       "stages": dict(collections.Counter(m["stage"] for m in ms)),
                       "first": min((m["utc"] for m in ms), default=None), "last": max((m["utc"] for m in ms), default=None),
                       "samples": [check_match(c, m["uuid"]) for m in rng.sample(played, min(a.per_season, len(played)))]}
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                f.flush()
                print(lg["key"], label, rec["matches"], rec["played"], [s.get("new_site_markets") for s in rec["samples"]], flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
