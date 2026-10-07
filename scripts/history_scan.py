"""Scan the new mackolik.com date listing (livescores JSON) day by day: competitions + matches with an iddaa code.

Listing metadata only (no odds). Resumable: one JSON line per date in --out (dates already present are skipped).
Usage: PYTHONPATH=src python scripts/history_scan.py --start 2019-08-01 --end 2026-10-06 --out scan.jsonl
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from odds_analysis import http as H

WWW = "https://www.mackolik.com"


def fetch(c: H.MackolikClient, date: str) -> dict | None:
    for _ in range(3):
        r = c.get(f"{WWW}/perform/p0/ajax/components/competition/livescores/json?sports%5B%5D=Soccer&matchDate={date}",
                  referer=f"{WWW}/canli-sonuclar", backoff=(5, 15))
        if r.ok:
            d = json.loads(r.text).get("data") or {}
            if d.get("matches"):
                return d
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--newest-first", action="store_true")
    a = ap.parse_args()
    out = Path(a.out)
    done = set()
    if out.exists():
        done = {json.loads(line)["date"] for line in out.read_text().splitlines() if line.strip()}
    d0, d1 = dt.date.fromisoformat(a.start), dt.date.fromisoformat(a.end)
    days = [d0 + dt.timedelta(days=i) for i in range((d1 - d0).days + 1)]
    if a.newest_first:
        days.reverse()
    with H.MackolikClient() as c, out.open("a", encoding="utf-8") as f:
        for day in days:
            ds = day.isoformat()
            if ds in done:
                continue
            data = fetch(c, ds)
            rec = {"date": ds, "ok": data is not None, "n_matches": 0, "competitions": {}, "matches": []}
            if data:
                comps = data.get("competitions") or {}
                rec["n_matches"] = len(data.get("matches") or {})
                for m in (data.get("matches") or {}).values():
                    comp = comps.get(m.get("competitionId")) or {}
                    rec["competitions"][m.get("competitionId")] = {
                        "name": comp.get("name"), "country": (comp.get("country") or {}).get("name"),
                        "code": comp.get("code"), "format": comp.get("competitionFormat"),
                        "slug": comp.get("competitionSlug"), "stages": list((comp.get("stage") or {}).keys())}
                    if m.get("iddaaCode"):
                        rec["matches"].append({
                            "uuid": m["id"], "code": m["iddaaCode"], "comp": m.get("competitionId"),
                            "stage": m.get("stageId"), "utc": m.get("mstUtc"), "name": m.get("matchName"),
                            "home": (m.get("homeTeam") or {}).get("name"), "away": (m.get("awayTeam") or {}).get("name"),
                            "state": m.get("state"), "substate": m.get("substate"), "score": m.get("score"),
                            "red": m.get("redCards")})
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            print(ds, rec["ok"], rec["n_matches"], len(rec["matches"]), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
