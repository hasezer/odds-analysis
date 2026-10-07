"""Mackolik responses -> SCHEMA.md rows (matches, teams, events, stats, odds, settlements).

Inputs: the www.mackolik.com date listing (livescores JSON), key events JSON, statistics page HTML and the arsiv
odds popup. Used by the backfill (closing_history prices) and, after the switch, by the daily jobs.
"""

from __future__ import annotations

import html as htmlmod
import re
from datetime import datetime, timedelta, timezone

from .catalog import classify, is_selected, selection_key, slug
from .parsers import parse_odds_popup
from .settle import Ctx, engine

TR = timezone(timedelta(hours=3))
PLAYOFF_STAGE = re.compile(r"play|playoff|final|yarı|çeyrek|son 16|eleme|üçüncülük|\d+\.(lik|lük|luk|lık) maçı|"
                           r"yükselme|küme düşme -|küme düşme play|kupa|cup|yeni sıralama|tur \(", re.IGNORECASE)
REGULAR_STAGE = re.compile(r"normal sezon|grubu|grup aşaması|^\d+\. (tur|aşama)$|^(açılış|kapanış)$|sezonu$|alt tablo",
                           re.IGNORECASE)


# ---------------------------------------------------------------- leagues / seasons

def season_type(stage: str | None, *, special: bool = False) -> str:
    if special:
        return "special"
    s = (stage or "").strip()
    if not s or REGULAR_STAGE.search(s):
        return "regular"
    return "playoff" if PLAYOFF_STAGE.search(s) else "regular"


def league_rows(leagues: list[dict]) -> list[dict]:
    return [{"league_id": lg["league_id"], "name_en": lg["name"], "name_tr": lg["name_tr"], "country": lg["country"],
             "tier": lg["tier"], "mackolik_new_id": lg["mackolik"]["competition_id"],
             "arsiv_code": (lg.get("arsiv") or {}).get("code"), "arsiv_league_id": (lg.get("arsiv") or {}).get("id"),
             "season_format": "calendar" if lg["calendar_year"] else "split", "active": True} for lg in leagues]


def team_id(league_id: str, name_tr: str) -> str:
    """Ours: <country of the league>-<ASCII slug of the Mackolik name>, e.g. TUR-GALATASARAY."""
    return f"{league_id.split('-')[0]}-{slug(name_tr).replace('/', '-')}"


# ---------------------------------------------------------------- matches

def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def match_status(state: str | None, substate: str | None) -> str:
    sub = (substate or "").lower()
    if state == "pre":
        return "postponed" if "postpon" in sub else ("cancelled" if "cancel" in sub else "scheduled")
    if state == "post":
        if "cancel" in sub:
            return "cancelled"
        if "postpon" in sub:
            return "postponed"
        if "abandon" in sub or "suspend" in sub:
            return "abandoned"
        return "finished"
    return "pending"


def match_row(m: dict, *, league_id: str, season: str, stage: str | None = None, special: bool = False) -> dict:
    """One match of the date listing (livescores JSON)."""
    ko = datetime.fromtimestamp(m["mstUtc"] / 1000, tz=timezone.utc)
    score = m.get("score") or {}
    ht, pen = score.get("ht") or {}, score.get("pen") or {}
    status = match_status(m.get("state"), m.get("substate"))
    fin = status == "finished"
    return {
        "match_id": m["id"], "iddaa_event_code": str(m["iddaaCode"]) if m.get("iddaaCode") else None,
        "arsiv_match_id": None, "league_id": league_id, "season": season,
        "season_type": season_type(stage, special=special), "round": stage or None,
        "kickoff_utc": ko, "kickoff_local_tr": ko.astimezone(TR).isoformat(),
        "home_team_id": team_id(league_id, m["homeTeam"]["name"]),
        "away_team_id": team_id(league_id, m["awayTeam"]["name"]),
        "status": status,
        "ht_home": _int(ht.get("home")) if fin else None, "ht_away": _int(ht.get("away")) if fin else None,
        "ft_home": _int(score.get("home")) if fin else None, "ft_away": _int(score.get("away")) if fin else None,
        "pen_home": _int(pen.get("home")), "pen_away": _int(pen.get("away")),
        "_home_tr": m["homeTeam"]["name"], "_away_tr": m["awayTeam"]["name"],
        "_home_new_id": m["homeTeam"].get("id"), "_away_new_id": m["awayTeam"].get("id"),
        "_substate": m.get("substate"),
    }


def apply_extra_time(match: dict, events: list[dict]) -> None:
    """Listing scores include extra time. With events from periods 3/4, ft = after 90 min, et = after 120 min."""
    et_goals = [e for e in events if e["event_type"] in ("goal", "penalty_goal", "own_goal") and (e.get("_period") or 0) in (3, 4)]
    sub = (match.get("_substate") or "").lower()
    if not et_goals and "extra" not in sub and "penalt" not in sub:
        return
    if match["ft_home"] is None:
        return
    eh = sum(e["team_side"] == "home" for e in et_goals)
    ea = sum(e["team_side"] == "away" for e in et_goals)
    match["et_home"], match["et_away"] = match["ft_home"], match["ft_away"]
    match["ft_home"], match["ft_away"] = match["ft_home"] - eh, match["ft_away"] - ea


def team_rows(matches: list[dict]) -> list[dict]:
    out = {}
    for m in matches:
        for side in ("home", "away"):
            tid = m[f"{side}_team_id"]
            out.setdefault(tid, {"team_id": tid, "name_tr": m[f"_{side}_tr"], "name_en": None,
                                 "mackolik_new_id": m.get(f"_{side}_new_id"), "arsiv_team_id": None,
                                 "country": m["league_id"].split("-")[0], "aliases": []})
    return list(out.values())


# ---------------------------------------------------------------- events / stats

EVENT = {("goal", "goal"): "goal", ("goal", "penalty-goal"): "penalty_goal", ("goal", "own-goal"): "own_goal",
         ("penalty-missed", "pm"): "missed_penalty", ("card", "yc"): "yellow", ("card", "y2c"): "second_yellow",
         ("card", "rc"): "red"}


def _minute(s: str | None) -> tuple[int | None, int | None]:
    m = re.match(r"\s*(\d+)\s*(?:\+\s*(\d+))?", s or "")
    return (int(m[1]), int(m[2]) if m[2] else None) if m else (None, None)


def event_rows(match_id: str, key_events: list[dict]) -> list[dict]:
    """Key events in feed order. A substitution becomes sub_out + sub_in. team_side of a goal = the side it counts
    for (own goals too), so score_after always matches."""
    rows = []
    for e in key_events:
        minute, added = _minute(e.get("timeMin"))
        base = {"match_id": match_id, "minute": minute, "added_minute": added, "team_side": e.get("position"),
                "_period": e.get("periodId")}
        if e.get("type") == "substitute":
            rows.append({**base, "event_type": "sub_out", "player_name": e.get("playerOutName")})
            rows.append({**base, "event_type": "sub_in", "player_name": e.get("playerName")})
            continue
        kind = EVENT.get((e.get("type"), e.get("subType")))
        if kind is None:
            continue  # unknown event types are skipped (and visible in the quality report via missing goals)
        rows.append({**base, "event_type": kind, "player_name": e.get("playerName"),
                     "assist_name": e.get("assistPlayerName"), "score_after": e.get("score") if e.get("type") == "goal" else None})
    for i, r in enumerate(rows, 1):
        r["event_order"] = i
    return rows


STAT_LABELS = {"corners": "Korner", "yellow_cards": "Sarı Kart", "shots": "Toplam Şut", "shots_on_target": "İsabetli Şut",
               "fouls": "Faul", "offsides": "Ofsayt", "crosses": "Toplam Orta"}


def stats_rows(match_id: str, page_html: str, events: list[dict]) -> list[dict]:
    """Statistics page ('Genel İstatistikler') + red cards / second yellows counted from the key events."""
    t = htmlmod.unescape(re.sub(r"<[^>]+>", " ", page_html))
    t = re.sub(r"\s+", " ", t)
    a, b = t.find("Genel İstatistikler"), t.find("Oyuncu İstatistikleri")
    if a < 0:
        return []
    block = t[a:b if b > a else None]
    vals = {}
    for key, label in STAT_LABELS.items():
        m = re.search(rf"(?<![\wçğıöşü]){label} (\d+) (\d+)", block)
        vals[key] = (int(m[1]), int(m[2])) if m else None
    pos = re.search(r"Topla Oynama %(\d+(?:,\d+)?) %(\d+(?:,\d+)?)", block)
    if vals["yellow_cards"] is None and vals["corners"] is not None and events:
        vals["yellow_cards"] = (0, 0)  # the page leaves out the row when nobody was booked (key events agree)
    out = []
    for i, side in enumerate(("home", "away")):
        reds = [e for e in events if e["team_side"] == side and e["event_type"] in ("red", "second_yellow")]
        out.append({"match_id": match_id, "team_side": side, "stats_source": "new",
                    **{k: (v[i] if v else None) for k, v in vals.items()},
                    "possession_pct": float(pos[i + 1].replace(",", ".")) if pos else None,
                    "red_cards": len(reds) if events else None,
                    "second_yellows": sum(e["event_type"] == "second_yellow" for e in reds) if events else None})
    return out


def stadium(page_html: str) -> str | None:
    m = re.search(r"Stat: ([^<(]+?)\s*(?:\(|<)", htmlmod.unescape(page_html))
    return m[1].strip() if m else None


# ---------------------------------------------------------------- odds / settlement

def odds_rows(match: dict, popup_text: str, *, price_type: str = "closing_history", captured_at=None) -> tuple[list[dict], list[dict]]:
    """Popup -> odds rows + the raw outcomes (with the official winner marks) for settlement.
    Raises ValueError if the popup belongs to another match (uuid check)."""
    import json

    data = json.loads(popup_text.lstrip("﻿"))
    pm = ((data.get("data") or {}).get("matches") or [{}])[0]
    if pm.get("uuid") != match["match_id"]:
        raise ValueError(f"popup shows match {pm.get('uuid')}, not {match['match_id']}")
    p = parse_odds_popup(popup_text)
    rows, outs = [], []
    for o in p["outcomes"]:
        info = classify(o["market_name"])
        if not is_selected(info):  # only the markets in config/markets.yaml are stored
            continue
        sk, tok = selection_key(info, o["selection"], match.get("_home_tr"), match.get("_away_tr"))
        mins = None
        if captured_at is not None:
            mins = int((match["kickoff_utc"] - captured_at).total_seconds() // 60)
        row = {"match_id": match["match_id"], "market_type_id": str(o["market_type_id"]), "market_key": info.market_key,
               "line": info.line, "handicap_home": info.handicap_home, "handicap_away": info.handicap_away,
               "selection_key": sk,
               "selection_name_tr": None if sk == "UNNAMED" else o["selection"], "odds": o["odds"], "mbs": o["mbs"],
               "price_type": price_type, "captured_at_utc": captured_at, "minutes_before_kickoff": mins, "source": "arsiv"}
        rows.append(row)
        outs.append({**row, "_name_tr": o["market_name"], "_info": info, "_tok": tok, "_highlight": o["highlight"]})
    return rows, outs


def engine_ctx(match: dict, events: list[dict], stats: list[dict]) -> Ctx | None:
    if match.get("status") != "finished" or match.get("ft_home") is None:
        return None
    c = Ctx(H=match["ft_home"], A=match["ft_away"], h1=match.get("ht_home"), a1=match.get("ht_away"))
    reg = [e for e in events if (e.get("_period") or 0) in (1, 2)]
    goals = [e for e in reg if e["event_type"] in ("goal", "penalty_goal", "own_goal")]
    if events and (sum(e["team_side"] == "home" for e in goals), sum(e["team_side"] == "away" for e in goals)) == (c.H, c.A):
        c.goals = [e["team_side"] for e in goals]  # complete goal list -> first goal etc.
    st = {s["team_side"]: s for s in stats}
    if st.get("home", {}).get("corners") is not None and st.get("away", {}).get("corners") is not None:
        c.corners = (st["home"]["corners"], st["away"]["corners"])
    if events:
        pens = any(e["event_type"] in ("penalty_goal", "missed_penalty") for e in reg)
        c.penalty = True if pens else (False if c.goals is not None else None)
    return c


def settlement_rows(match: dict, outcomes: list[dict], ctx: Ctx | None, settled_at: datetime, *,
                    unsettleable_families: set[str] = frozenset()) -> list[dict]:
    """hit_official = Nesine's winner mark (only for markets where Nesine marks winners and at least one
    selection is marked); hit_engine = our engine; hit = official if present else engine."""
    marked = {(o["market_type_id"], o["line"], o["handicap_home"]) for o in outcomes if o["_highlight"]}
    siblings: dict[tuple, list[str]] = {}
    for o in outcomes:
        siblings.setdefault((o["market_type_id"], o["line"], o["handicap_home"]), []).append(o["_tok"])
    rows = []
    for o in outcomes:
        info, mkey = o["_info"], (o["market_type_id"], o["line"], o["handicap_home"])
        official = None
        if info.settle_source == "official" and mkey in marked:
            official = bool(o["_highlight"])
        eng = None
        if ctx is not None and info.engine is not None and info.settle_source != "none":
            try:
                eng = engine(info.engine.key, o["_tok"], ctx, siblings[mkey])
            except Exception:  # noqa: BLE001 - a malformed selection must not stop settlement
                eng = None
        hit = official if official is not None else eng
        if match.get("status") in ("postponed", "cancelled", "abandoned"):
            status, hit = "void", None
        elif info.family in unsettleable_families:
            status, hit = "unsettleable", None
        elif hit is None:
            status = "pending" if match.get("status") != "finished" else "unsettleable"
        else:
            status = "settled"
        rows.append({"match_id": o["match_id"], "market_type_id": o["market_type_id"], "line": o["line"],
                     "handicap_home": o["handicap_home"], "handicap_away": o["handicap_away"],
                     "selection_key": o["selection_key"], "hit_official": official, "hit_engine": eng, "hit": hit,
                     "status": status, "settle_basis": None if hit is None else ("official" if official is not None else "engine"),
                     "settled_at_utc": settled_at})
    return rows


def market_rows(outcomes: list[dict], season: str) -> list[dict]:
    out = {}
    for o in outcomes:
        info = o["_info"]
        out.setdefault(o["market_type_id"], {"market_type_id": o["market_type_id"], "market_key": info.market_key,
                                             "name_tr": o["_name_tr"], "family": info.family,
                                             "has_line": info.line is not None, "settle_source": info.settle_source,
                                             "first_seen_season": season, "_names": set()})["_names"].add(o["_name_tr"])
    for r in out.values():  # a type id shared by several lines (corners 8,5/9,5/10,5) is named without the line
        if len(r["_names"]) > 1:
            r["name_tr"] = re.sub(r"\s*\d+,\d+\s*", " ", sorted(r["_names"])[0]).strip()
        del r["_names"]
    return list(out.values())
