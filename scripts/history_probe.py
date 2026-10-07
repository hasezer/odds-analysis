"""History investigation: what the new mackolik.com backend serves for past matches (see HISTORY_REPORT.md).

Usage: PYTHONPATH=src python scripts/history_probe.py years|sample|compare  [--out DIR]
Read-only, <= 1 request/second, plain public website endpoints (no geo workaround).
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from odds_analysis import http as H  # noqa: E402
from odds_analysis.parsers import parse_odds_popup  # noqa: E402

WWW = "https://www.mackolik.com"
BIG = {("İspanya", "LaLiga"), ("İngiltere", "Premier League"), ("İngiltere", "Premier Lig"), ("İtalya", "Serie A"),
       ("Almanya", "Bundesliga"), ("Fransa", "Ligue 1"), ("Türkiye", "Süper Lig"), ("Türkiye", "Trendyol Süper Lig")}


def livescores(c: H.MackolikClient, date: str) -> dict:
    r = c.get(f"{WWW}/perform/p0/ajax/components/competition/livescores/json?sports%5B%5D=Soccer&matchDate={date}",
              referer=f"{WWW}/canli-sonuclar")
    if not r.ok:
        return {"error": r.error}
    return json.loads(r.text).get("data") or {}


def outcomes(c: H.MackolikClient, uuid: str) -> dict | None:
    r = c.get(f"{WWW}/ajax/iddaa/outcomes/soccer/all/{uuid}", referer=f"{WWW}/mac/x/iddaa/{uuid}")
    if not r.ok:
        return None
    d = json.loads(r.text)
    return d.get("data") if d.get("status") == "success" else None


def market_names(c: H.MackolikClient, uuid: str) -> list[str]:
    r = c.get(f"{WWW}/ajax/iddaa/markets/soccer/all/{uuid}?template=all", referer=f"{WWW}/mac/x/iddaa/{uuid}")
    if not r.ok:
        return []
    h = json.loads(r.text).get("data", {}).get("html", "")
    return [re.sub(r"\s+", " ", x).strip() for x in re.findall(r'__header-text">(.*?)<', h, re.S)]


def popup(c: H.MackolikClient, code: int) -> dict:
    r = c.get(H.odds_popup_path(code))
    if not r.ok:
        return {"error": r.error}
    p = parse_odds_popup(r.text)
    return {"uuid": (json.loads(r.text.lstrip("﻿"))["data"]["matches"] or [{}])[0].get("uuid"),
            "start": p["match"] and p["match"]["start_time"], "markets": len({o["market_id"] for o in p["outcomes"]}),
            "highlighted": sum(o["highlight"] for o in p["outcomes"]),
            "decided_markets": len({o["market_id"] for o in p["outcomes"] if o["highlight"]}),
            "mbs": sorted({o["mbs"] for o in p["outcomes"] if o["mbs"] is not None})}


def match_rows(data: dict) -> list[dict]:
    comps = data.get("competitions") or {}
    rows = []
    for m in (data.get("matches") or {}).values():
        comp = comps.get(m.get("competitionId"), {})
        rows.append({"uuid": m["id"], "name": m["matchName"], "code": m.get("iddaaCode"),
                     "comp": comp.get("name"), "country": (comp.get("country") or {}).get("name"),
                     "comp_code": comp.get("code"), "state": m.get("state"), "substate": m.get("substate"),
                     "score": m.get("score"), "utc": m.get("mstUtc")})
    return rows


def summarize_outcomes(o: dict | None) -> dict:
    if not o:
        return {"markets": 0}
    mk = o.get("markets") or {}
    vals = [x.get("outcome") for m in mk.values() for x in (m.get("outcomes") or {}).values()]
    return {"markets": len(mk), "selections": len(vals), "priced": sum(v not in (None, "-", "") for v in vals),
            "mbs_present": sum(bool(m.get("mbc")) for m in mk.values()),
            "states": sorted({str(x.get("state")) for m in mk.values() for x in (m.get("outcomes") or {}).values()})}


def years(c, out: Path) -> list[dict]:
    res = []
    for date in ["2014-10-18", "2015-10-17", "2016-10-15", "2017-10-14", "2018-10-20", "2019-10-19", "2020-10-17",
                 "2021-10-16", "2022-10-15", "2023-10-21", "2024-10-19", "2025-10-18"]:
        data = livescores(c, date)
        rows = match_rows(data) if "error" not in data else []
        iddaa = [r for r in rows if r["code"]]
        big = next((r for r in iddaa if (r["country"], r["comp"]) in BIG), iddaa[0] if iddaa else None)
        s = summarize_outcomes(outcomes(c, big["uuid"])) if big else {}
        pp = popup(c, big["code"]) if big else {}
        res.append({"date": date, "matches": len(rows), "iddaa_matches": len(iddaa), "example": big and big["name"],
                    "example_comp": big and big["comp"], "new_site": s, "arsiv_popup": pp,
                    "popup_same_match": bool(big and pp.get("uuid") == big["uuid"])})
        print(json.dumps(res[-1], ensure_ascii=False))
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["years", "sample"])
    ap.add_argument("--out", default="history_output")
    ap.add_argument("--dates", nargs="*")
    ap.add_argument("--per-group", type=int, default=4)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    with H.MackolikClient() as c:
        if a.what == "years":
            res = years(c, out)
        else:
            res = sample(c, a.dates, a.per_group)
    (out / f"{a.what}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


def sample(c, dates: list[str], per_group: int) -> list[dict]:
    rng = random.Random(1)
    res = []
    for date in dates:
        rows = [r for r in match_rows(livescores(c, date)) if r["code"]]
        big = [r for r in rows if (r["country"], r["comp"]) in BIG]
        small = [r for r in rows if (r["country"], r["comp"]) not in BIG]
        for group, pool in (("big", big), ("small", small)):
            for r in rng.sample(pool, min(per_group, len(pool))):
                s = summarize_outcomes(outcomes(c, r["uuid"]))
                names = market_names(c, r["uuid"]) if s["markets"] else []
                pp = popup(c, r["code"])
                row = {"date": date, "group": group, "match": r["name"], "comp": f"{r['country']} / {r['comp']}",
                       "code": r["code"], "new_site": s, "market_names": names,
                       "arsiv_popup": pp, "popup_same_match": pp.get("uuid") == r["uuid"]}
                res.append(row)
                print(json.dumps({k: v for k, v in row.items() if k != "market_names"}, ensure_ascii=False))
    return res


if __name__ == "__main__":
    sys.exit(main())
