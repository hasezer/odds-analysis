"""Parsers for the Mackolik/Nesine endpoints verified in Phase 0.

A/C  day list & program page  -> parse_day_list()
B    odds popup JSON          -> parse_odds_popup()
D    match page / data / stats -> parse_match_page(), parse_match_data(), parse_stats_box()
"""

from __future__ import annotations

import json
import re
from datetime import datetime

from selectolax.lexbor import LexborHTMLParser as HTMLParser, LexborNode as Node

NESINE_BOOKIE_ID = 14

_ODDS_DIALOG = re.compile(r"openOddsDialog\((.*)\)", re.S)
_JS_STRING = re.compile(r"'((?:[^'\\]|\\.)*)'")
_ID_IN = {
    "match": re.compile(r"popMatch\((\d+)"),
    "team": re.compile(r"popTeam\((\d+)\)"),
    "league": re.compile(r"popLeague\((\d+)\)"),
}
_MBS = re.compile(r"mbs(\d+)\.png")
_SCORE = re.compile(r"(\d+)\s*-\s*(\d+)")


def parse_odds_value(raw: str | None) -> float | None:
    """'2,58' / '2.58' -> 2.58; '-', '' and None -> None."""
    if raw is None:
        return None
    s = raw.strip().replace(",", ".")
    if s in ("", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_score(raw: str | None) -> tuple[int, int] | None:
    if not raw:
        return None
    m = _SCORE.search(raw)
    return (int(m.group(1)), int(m.group(2))) if m else None


def _iso_date(ddmmyyyy: str) -> str:
    return datetime.strptime(ddmmyyyy.strip(), "%d.%m.%Y").date().isoformat()


def _js_args(call: str) -> list:
    """Split the argument list of openOddsDialog(...) into str / list[str] / None items."""
    args, depth, cur, in_str = [], 0, "", False
    for ch in call:
        if ch == "'" and not cur.endswith("\\"):
            in_str = not in_str
        if not in_str:
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
            elif ch == "," and depth == 0:
                args.append(cur.strip())
                cur = ""
                continue
        cur += ch
    if cur.strip():
        args.append(cur.strip())
    out = []
    for a in args:
        if a.startswith("["):
            out.append(_JS_STRING.findall(a))
        elif a == "null":
            out.append(None)
        else:
            strs = _JS_STRING.findall(a)
            out.append(strs[0] if strs else a)
    return out


def _text(node: Node | None) -> str:
    return re.sub(r"\s+", " ", node.text(separator=" ")).strip() if node else ""


def parse_day_list(html: str) -> list[dict]:
    """Rows of endpoint A (AJAX day list) or C (Iddaa-Programi page).

    Each match row yields one dict with match metadata, list scores and a `markets`
    list of {market, list_code, market_no, outcomes:[{name, odds}]}.
    Dates come from the section header rows; kickoff times are Turkey local time (UTC+3).
    """
    tree = HTMLParser(html)
    rows: list[dict] = []
    section_date: str | None = None
    for tr in tree.css("tr"):
        header = tr.css_first('td[ratesort="tarih_1"]') or tr.css_first('td[rateSort="tarih_1"]')
        if header is not None:
            try:
                section_date = _iso_date(_text(header))
            except ValueError:
                pass
            continue
        tr_html = tr.html or ""
        if "popMatch(" not in tr_html or "popTeam(" not in tr_html:
            continue
        tds = tr.css("td")
        team_links = [a for a in tr.css("a") if "popTeam(" in (a.attributes.get("href") or "")]
        if len(team_links) < 2:
            continue
        home_a, away_a = team_links[0], team_links[1]
        teams_td_idx = next(i for i, td in enumerate(tds) if "popTeam(" in (td.html or ""))
        after = tds[teams_td_idx + 1 :]
        ht = ft = None
        if after and after[0].attributes.get("colspan") != "2" and len(after) >= 2:
            ht = parse_score(_text(after[0]))
            ft = parse_score(_text(after[1]))
        league_td = next((td for td in tds if "popLeague(" in (td.attributes.get("onclick") or "") and not td.css_first("img")), None)
        league_id = _ID_IN["league"].search(tr_html)
        mbs = _MBS.search(tr_html)
        match_id = _ID_IN["match"].search(tr_html)

        markets: dict[str, dict] = {}
        pending_code: str | None = None
        event_code: str | None = None
        for td in after:
            a = td.css_first("a")
            href = a.attributes.get("href", "") if a else ""
            if "openOddsDialog" not in href:
                t = _text(td)
                pending_code = t if t.isdigit() else pending_code
                continue
            args = _js_args(_ODDS_DIALOG.search(href).group(1))
            # (mbs, market name, outcome names, odds, ?, 'openBmIddaa', EVENT_CODE, market_no, outcome ids)
            name, out_names, out_vals = args[1], args[2], args[3]
            event_code = args[6] if len(args) > 6 else event_code
            if name not in markets:
                markets[name] = {
                    "market": name,
                    "list_code": pending_code,
                    "market_no": args[7] if len(args) > 7 else None,
                    "outcomes": [
                        {"name": n, "odds": parse_odds_value(v)} for n, v in zip(out_names or [], out_vals or [])
                    ],
                }
                pending_code = None

        rows.append(
            {
                "date": section_date,
                "kickoff_local": _text(tds[0]) or None,
                "league_code": _text(league_td) or None if league_td else None,
                "league_id": int(league_id.group(1)) if league_id else None,
                "mbs": int(mbs.group(1)) if mbs else None,
                "mackolik_match_id": int(match_id.group(1)) if match_id else None,
                "home_team_id": int(_ID_IN["team"].search(home_a.attributes["href"]).group(1)),
                "home_team": _text(home_a),
                "away_team_id": int(_ID_IN["team"].search(away_a.attributes["href"]).group(1)),
                "away_team": _text(away_a),
                "ht_home": ht[0] if ht else None,
                "ht_away": ht[1] if ht else None,
                "ft_home": ft[0] if ft else None,
                "ft_away": ft[1] if ft else None,
                "event_code": event_code,
                "markets": list(markets.values()),
            }
        )
    return rows


def parse_odds_popup(text: str, bookie_id: int = NESINE_BOOKIE_ID) -> dict:
    """Endpoint B. Returns {'match': {...}, 'outcomes': [one row per market outcome]}."""
    data = json.loads(text.lstrip("﻿"))
    matches = (data.get("data") or {}).get("matches") or []
    if not matches:
        return {"match": None, "outcomes": [], "fetched_utc": data.get("date_time_utc")}
    m = matches[0]
    meta = {k: m.get(k) for k in ("id", "status", "is_awarded", "start_time", "iddaa_code")}
    meta["bookies"] = [b.get("name") for b in m.get("bookies", [])]
    book = next((b for b in m.get("bookies", []) if b.get("id") == bookie_id), None)
    rows = []
    for mk in (book or {}).get("markets", []):
        for o in mk.get("outcomes", []):
            rows.append(
                {
                    "market_id": mk.get("id"),
                    # coupon code: changes per event. market_type_id is the stable market type.
                    "market_code": mk.get("code"),
                    "market_type_id": o.get("market_type_id"),
                    "market_name": (mk.get("name") or "").strip(),
                    "mbs": mk.get("mbc"),
                    "line": mk.get("sov"),
                    "handicap_value": mk.get("handicap_value"),
                    "handicap_team": mk.get("handicap_team"),
                    "name_secondary": mk.get("name_secondary"),
                    "selection": (o.get("name") or "").strip(),
                    "selection_key": o.get("key"),
                    "odds": parse_odds_value(o.get("value")),
                    "highlight": bool(o.get("highlight")),
                }
            )
    return {"match": meta, "outcomes": rows, "fetched_utc": data.get("date_time_utc"), "nesine_found": book is not None}


EVENT_TYPES = {1: "goal", 2: "yellow", 3: "red", 4: "sub", 7: "missed_penalty"}
GOAL_DETAIL = {1: "normal", 2: "penalty", 3: "own_goal"}


def parse_match_data(text: str) -> dict:
    """D via /Match/MatchData.aspx?t=dtl (the JSON Match.js renders into the page).

    Event tuple: [team(1=home,2=away), minute, player_id, player_name, type, extra].
    For goals `team` is the side credited with the goal (own goals included), so the
    running score is computed exactly like Match.js does.
    """
    data = json.loads(text.lstrip("﻿"))
    d = data.get("d") or {}
    events = []
    h = a = 0
    for ev in data.get("e") or []:
        team, minute, player_id, player_name, etype, extra = (ev + [None] * 6)[:6]
        extra = extra or {}
        kind = EVENT_TYPES.get(etype, f"type_{etype}")
        row = {
            "team": "home" if team == 1 else "away",
            "minute": minute,
            "type": kind,
            "player_id": player_id or None,
            "player": player_name if player_id else extra.get("p"),
            "detail": None,
            "assist_id": None,
            "assist": None,
            "score_after": None,
            "player_out_id": None,
            "player_out": None,
        }
        if kind == "goal":
            h, a = (h + 1, a) if team == 1 else (h, a + 1)
            row["detail"] = GOAL_DETAIL.get(extra.get("d"), str(extra.get("d")))
            row["assist_id"] = extra.get("astId")
            row["assist"] = extra.get("astName")
            row["score_after"] = f"{h}-{a}"
        elif kind == "red":
            row["detail"] = "second_yellow" if extra.get("d") == 1 else "straight_red"
        elif kind == "sub":
            row["player_out_id"] = extra.get("d")
            row["player_out"] = extra.get("sub")
        events.append(row)
    return {
        "home": data.get("home"),
        "away": data.get("away"),
        "status": d.get("st"),
        "is_playing": d.get("p"),
        "score": parse_score(d.get("s")),
        "ht": parse_score(d.get("ht")),
        "ft_field": parse_score(d.get("ft")),
        "et": parse_score(d.get("et")),
        "pen": parse_score(d.get("pt")),
        "events": events,
        "goal_score_from_events": (h, a),
    }


def parse_stats_box(html: str) -> dict[str, tuple[str, str]]:
    """'İstatistikler' box (page-embedded, optaStats or rbStats): {title: (home, away)} as raw strings."""
    tree = HTMLParser(html)
    out: dict[str, tuple[str, str]] = {}
    for title in tree.css(".statistics-title-text"):
        parent = title.parent
        home = parent.css_first(".team-1-statistics-text")
        away = parent.css_first(".team-2-statistics-text")
        if home is not None and away is not None:
            out[_text(title)] = (_text(home), _text(away))
    if out:
        return out
    # rbStats uses a different layout: "<home> <title> <away>" triplets
    text = _text(tree.body) if tree.body else ""
    for m in re.finditer(r"(%?\d+(?:/\d+)?)\s+([A-Za-zÇĞİÖŞÜçğıöşü%(). ]+?)\s+(%?\d+(?:/\d+)?)(?=\s|$)", text):
        out[m.group(2).strip()] = (m.group(1), m.group(3))
    return out


def parse_match_page(html: str) -> dict:
    """D header: league/season, date-time, teams, score text, stadium, referee, attendance, stats box."""
    tree = HTMLParser(html)
    season = tree.css_first(".match-info-wrapper-season b")
    date_div = _text(tree.css_first(".match-info-date")).replace("Tarih :", "").strip()
    referee = tree.css_first('.match-info-detail-text a[href*="/Hakem/"] b')
    stadium = tree.css_first('.match-info-detail-text a[href*="/Stadyum/"]')
    attendance = re.search(r"Seyirci\s*:\s*([\d.]+)", html)
    stats_html = tree.css_first("#dvOPTAStats")
    return {
        "league": _text(season) or None,
        "kickoff_local": date_div or None,
        "home_team": _text(tree.css_first(".left-block-team-name")) or None,
        "away_team": _text(tree.css_first(".r-left-block-team-name")) or None,
        "status_text": _text(tree.css_first("#dvStatusText")) or None,
        "score": parse_score(_text(tree.css_first("#dvScoreText"))),
        "stadium": _text(stadium) or None,
        "referee": _text(referee) or None,
        "attendance": int(attendance.group(1).replace(".", "")) if attendance else None,
        "stats": parse_stats_box(stats_html.html) if stats_html is not None else {},
    }
