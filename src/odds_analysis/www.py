"""www.mackolik.com requests (the new backend): date listing, key events, statistics page, season fixtures."""

from __future__ import annotations

import json
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
