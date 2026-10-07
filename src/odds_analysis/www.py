"""www.mackolik.com requests (the new backend): date listing, key events, statistics page, season fixtures."""

from __future__ import annotations

import json
import re
from datetime import date

from . import http as H

WWW = "https://www.mackolik.com"


def listing(c: H.MackolikClient, d: date) -> dict | None:
    """All football matches of a Turkish calendar date: {'competitions': {...}, 'matches': {...}} or None."""
    r = c.get(f"{WWW}/perform/p0/ajax/components/competition/livescores/json?sports%5B%5D=Soccer&matchDate={d.isoformat()}",
              referer=f"{WWW}/canli-sonuclar")
    if not r.ok:
        return None
    data = json.loads(r.text).get("data") or {}
    return data if data.get("matches") is not None else None


def key_events(c: H.MackolikClient, uuid: str) -> list[dict] | None:
    r = c.get(f"{WWW}/ajax/football/key-events?ajaxViewName=events&matchId={uuid}")
    if not r.ok:
        return None
    return (json.loads(r.text).get("data") or {}).get("keyEvents") or []


def stats_page(c: H.MackolikClient, uuid: str) -> str | None:
    r = c.get(f"{WWW}/mac/x/istatistik/{uuid}", follow_redirects=True)  # 301 -> the match's real slug
    return r.text if r.ok else None


RAW_KEY = '"raw":{"match":{'  # each fixture of a season page carries its source row as a JSON object


def season_fixtures(c: H.MackolikClient, slug: str, competition_id: str, label: str) -> list[dict]:
    """Every match of one league season (regular season and the league's own playoff stages):
    [{'match_id', 'stage', 'kickoff_utc', 'status'}]; [] if the page does not exist."""
    import html

    r = c.get(f"{WWW}/puan-durumu/{slug}/{label}/fikstur/{competition_id}")
    if not r.ok:  # redirects are not followed: a wrong slug/season is simply "not ok"
        return []
    s = html.unescape(r.text)
    dec = json.JSONDecoder()
    out, seen = [], set()
    pos = s.find(RAW_KEY)
    while pos != -1:  # raw_decode is linear; a regex over the ~4 MB page backtracks for minutes
        m = dec.raw_decode(s, pos + len('"raw":'))[0]["match"]
        pos = s.find(RAW_KEY, pos + 1)
        if m["uuid"] in seen:
            continue
        seen.add(m["uuid"])
        out.append({"match_id": m["uuid"], "stage": (m.get("round") or {}).get("name") or None,
                    "kickoff_utc": m["date_time_utc"].replace(" ", "T") + "Z", "status": m["status"]})
    return out


def market_outcomes(c: H.MackolikClient, uuid: str) -> list[dict] | None:
    """Nesine markets of a match from www.mackolik.com (keyed by the match uuid, so always the right match), in the
    shape of parsers.parse_odds_popup()['outcomes']. No winner marks. None if the request failed."""
    from selectolax.lexbor import LexborHTMLParser

    r = c.get(f"{WWW}/ajax/iddaa/markets/soccer/all/{uuid}?template=all")
    if not r.ok:
        return None
    tree = LexborHTMLParser((json.loads(r.text).get("data") or {}).get("html") or "")
    out, seen = [], set()
    for item in tree.css("li.widget-iddaa-markets__market-item"):
        header = item.css_first(".widget-iddaa-markets__header-text")
        if header is None or item.attributes.get("data-market-id") in seen:
            continue
        seen.add(item.attributes.get("data-market-id"))
        mbs = item.css_first(".widget-iddaa-markets__mbc")
        mbs = int(m[0]) if mbs and (m := re.findall(r"\d+", mbs.text())) else None
        for opt in item.css("li.widget-iddaa-markets__option"):
            label, value = opt.css_first(".widget-iddaa-markets__label"), opt.css_first(".widget-iddaa-markets__value")
            if label is None or (header.text(strip=True), label.text(strip=True)) in seen:
                continue  # the page lists every market twice (tabs)
            seen.add((header.text(strip=True), label.text(strip=True)))
            v = value.text(strip=True).replace(",", ".") if value is not None else ""
            out.append({"market_name": header.text(strip=True), "market_type_id": item.attributes.get("data-market"),
                        "selection": label.text(strip=True), "odds": float(v) if re.fullmatch(r"\d+(\.\d+)?", v) else None,
                        "mbs": mbs, "highlight": False})
    return out
