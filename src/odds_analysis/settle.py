"""Settlement: every stored selection -> hit_official (Nesine's marks), hit_engine (our rules), final hit.

final hit = official if Nesine marked the market, else engine.
Corner and card markets are engine-only (Nesine publishes no marks for them) and flagged as such.
Void matches (postponed/cancelled) -> outcome 'void'.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

import pandas as pd

from pathlib import Path

from .config import DATA, load
from .storage import frame, read_partition, read_table, upsert_partition, write_log_frame

log = logging.getLogger(__name__)

ENGINE_ONLY_FAMILIES = {"corners", "ht_corners", "corner_timing", "cards"}
SIGN = {1: "home", 0: "draw", -1: "away"}


def _sign(x: int) -> str:
    return SIGN[(x > 0) - (x < 0)]


@dataclass
class Ctx:
    """Everything the engine knows about one finished match."""
    H: int
    A: int
    h1: int | None = None
    a1: int | None = None
    goals: list[str] | None = None          # ordered scoring sides if events are complete, else None
    corners: tuple[int, int] | None = None
    ht_corners: tuple[int, int] | None = None
    card_points: tuple[int, int] | None = None
    ht_card_points: tuple[int, int] | None = None
    reds: int | None = None
    penalty: bool | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def h2(self): return None if self.h1 is None else self.H - self.h1
    @property
    def a2(self): return None if self.a1 is None else self.A - self.a1
    @property
    def has_ht(self): return self.h1 is not None and self.a1 is not None


def _range_hit(total: int, sel: str) -> bool | None:
    m = re.fullmatch(r"(\d+)\+", sel)
    if m:
        return total >= int(m[1])
    m = re.fullmatch(r"(\d+)-(\d+)", sel)
    if m:
        return int(m[1]) <= total <= int(m[2])
    return None


def _ou(total: int | None, line: float, sel: str) -> bool | None:
    if total is None or sel not in ("over", "under"):
        return None
    return total > line if sel == "over" else total < line


def _yn(value: bool | None, sel: str) -> bool | None:
    if value is None or sel not in ("yes", "no"):
        return None
    return value if sel == "yes" else not value


def _line(key: str) -> float:
    return float(key.rsplit("_", 1)[1])


def engine(key: str, sel: str, c: Ctx, siblings: list[str] | None = None) -> bool | None:
    """True/False if our data decides the selection, None if it cannot.

    siblings: the other selections of the same market (needed for 'Diğer' = any score not listed).
    """
    if sel == "Diğer" and key in ("CORRECT_SCORE", "HT_CORRECT_SCORE"):
        listed = [engine(key, s, c) for s in (siblings or []) if s != "Diğer"]
        return None if not listed or any(x is None for x in listed) else not any(listed)
    H, A = c.H, c.A
    side_goals = {"home": H, "away": A}
    # ---- full time
    if key == "1X2":
        return _sign(H - A) == sel
    if key == "DC":
        return _sign(H - A) in {"1X": ("home", "draw"), "12": ("home", "away"), "X2": ("draw", "away")}.get(sel, ())
    if key == "BTTS":
        return _yn(H > 0 and A > 0, sel)
    if re.fullmatch(r"OU_[\d.]+", key):
        return _ou(H + A, _line(key), sel)
    if key == "ODD_EVEN":
        return ((H + A) % 2 == 1) == (sel == "odd") if sel in ("odd", "even") else None
    if key == "GOAL_RANGE":
        return _range_hit(H + A, sel)
    if key.startswith("HANDICAP_"):
        return _sign(H + float(key.split("_", 1)[1]) - A) == sel
    if m := re.fullmatch(r"TEAM_OU_(home|away)_([\d.]+)", key):
        return _ou(side_goals[m[1]], float(m[2]), sel)
    if key == "CORRECT_SCORE":
        return sel == f"{H}-{A}" if re.fullmatch(r"\d+-\d+", sel) else None
    if key == "WINNING_MARGIN":
        d = H - A
        if sel == "draw":
            return d == 0
        m = re.fullmatch(r"(home|away)_(\d+)(\+?)", sel)
        if not m:
            return None
        diff = d if m[1] == "home" else -d
        return diff >= int(m[2]) if m[3] else diff == int(m[2])
    if m := re.fullmatch(r"TEAM_WIN_TO_NIL_(home|away)", key):
        won = H > A if m[1] == "home" else A > H
        conceded = A if m[1] == "home" else H
        return _yn(won and conceded == 0, sel)
    if m := re.fullmatch(r"1X2_AND_OU_([\d.]+)", key):
        r, _, ou = sel.partition("_")
        return None if not ou else (_sign(H - A) == r and _ou(H + A, float(m[1]), ou))
    if key == "1X2_AND_BTTS":
        r, _, b = sel.partition("_")
        return None if not b else (_sign(H - A) == r and _yn(H > 0 and A > 0, b))
    if m := re.fullmatch(r"OU_([\d.]+)_AND_BTTS", key):
        ou, _, b = sel.partition("_")
        return None if not b else (_ou(H + A, float(m[1]), ou) and _yn(H > 0 and A > 0, b))
    if key == "FIRST_GOAL":
        if H + A == 0:
            return sel == "none"
        if c.goals is None:
            return None  # goal order unknown (no or inconsistent events)
        return c.goals[0] == sel

    # ---- halves (need İY score)
    if not c.has_ht:
        half_keys = ("HT_", "2H_", "MORE_GOALS_HALF", "TEAM_MORE_GOALS_HALF", "TEAM_SCORES_BOTH_HALVES",
                     "TEAM_WIN_EITHER_HALF", "TEAM_WIN_BOTH_HALVES", "BOTH_HALVES")
        if key.startswith(half_keys) and not key.startswith(("HT_CORNER", "HT_MOST_CORNERS", "HT_CARDS")):
            return None
    h1, a1, h2, a2 = c.h1, c.a1, c.h2, c.a2
    if key == "HT_1X2":
        return _sign(h1 - a1) == sel
    if key == "2H_1X2":
        return _sign(h2 - a2) == sel
    if key == "HT_DC":
        return _sign(h1 - a1) in {"1X": ("home", "draw"), "12": ("home", "away"), "X2": ("draw", "away")}.get(sel, ())
    if m := re.fullmatch(r"HT_OU_([\d.]+)", key):
        return _ou(h1 + a1, float(m[1]), sel)
    if m := re.fullmatch(r"2H_OU_([\d.]+)", key):
        return _ou(h2 + a2, float(m[1]), sel)
    if key == "HT_BTTS":
        return _yn(h1 > 0 and a1 > 0, sel)
    if key == "2H_BTTS":
        return _yn(h2 > 0 and a2 > 0, sel)
    if key == "HT_2H_BTTS":
        x, _, y = sel.partition("/")
        return None if not y else (_yn(h1 > 0 and a1 > 0, x) and _yn(h2 > 0 and a2 > 0, y))
    if key == "HT_FT":
        x, _, y = sel.partition("/")
        return _sign(h1 - a1) == x and _sign(H - A) == y
    if key == "HT_ODD_EVEN":
        return ((h1 + a1) % 2 == 1) == (sel == "odd") if sel in ("odd", "even") else None
    if key == "HT_GOAL_RANGE":
        return _range_hit(h1 + a1, sel)
    if m := re.fullmatch(r"HT_TEAM_OU_(home|away)_([\d.]+)", key):
        return _ou(h1 if m[1] == "home" else a1, float(m[2]), sel)
    if key == "HT_CORRECT_SCORE":
        return sel == f"{h1}-{a1}" if re.fullmatch(r"\d+-\d+", sel) else None
    if key == "HT_FT_CORRECT_SCORE":
        return sel == f"{h1}-{a1}/{H}-{A}" if re.fullmatch(r"\d+-\d+/\d+-\d+", sel) else None
    if key == "MORE_GOALS_HALF":
        return {"1H": h1 + a1 > h2 + a2, "2H": h2 + a2 > h1 + a1, "equal": h1 + a1 == h2 + a2}.get(sel)
    if m := re.fullmatch(r"TEAM_MORE_GOALS_HALF_(home|away)", key):
        g1, g2 = (h1, h2) if m[1] == "home" else (a1, a2)
        return {"1H": g1 > g2, "2H": g2 > g1, "equal": g1 == g2}.get(sel)
    if m := re.fullmatch(r"TEAM_SCORES_BOTH_HALVES_(home|away)", key):
        g1, g2 = (h1, h2) if m[1] == "home" else (a1, a2)
        return _yn(g1 > 0 and g2 > 0, sel)
    if m := re.fullmatch(r"TEAM_WIN_EITHER_HALF_(home|away)", key):
        w = (h1 > a1 or h2 > a2) if m[1] == "home" else (a1 > h1 or a2 > h2)
        return _yn(w, sel)
    if m := re.fullmatch(r"TEAM_WIN_BOTH_HALVES_(home|away)", key):
        w = (h1 > a1 and h2 > a2) if m[1] == "home" else (a1 > h1 and a2 > h2)
        return _yn(w, sel)
    if m := re.fullmatch(r"BOTH_HALVES_(UNDER|OVER)_([\d.]+)", key):
        ln = float(m[2])
        w = (h1 + a1 < ln and h2 + a2 < ln) if m[1] == "UNDER" else (h1 + a1 > ln and h2 + a2 > ln)
        return _yn(w, sel)
    if key == "HT_1X2_AND_HT_BTTS":
        r, _, b = sel.partition("_")
        return None if not b else (_sign(h1 - a1) == r and _yn(h1 > 0 and a1 > 0, b))
    if m := re.fullmatch(r"HT_1X2_AND_HT_OU_([\d.]+)", key):
        r, _, ou = sel.partition("_")
        return None if not ou else (_sign(h1 - a1) == r and _ou(h1 + a1, float(m[1]), ou))

    # ---- corners (total from the stats box; no first-half split exists)
    if key.startswith(("CORNERS_", "MOST_CORNERS", "CORNER_RANGE")):
        if c.corners is None:
            return None
        ch, ca = c.corners
        if m := re.fullmatch(r"CORNERS_OU_([\d.]+)", key):
            return _ou(ch + ca, float(m[1]), sel)
        if key == "CORNERS_ODD_EVEN":
            return ((ch + ca) % 2 == 1) == (sel == "odd") if sel in ("odd", "even") else None
        if key == "MOST_CORNERS":
            return _sign(ch - ca) == sel
        if key == "CORNER_RANGE":
            return _range_hit(ch + ca, sel)
    if key.startswith(("HT_CORNERS", "HT_MOST_CORNERS", "HT_CORNER_RANGE", "FIRST_CORNER")):
        return None

    # ---- cards (Kart Puanı)
    if m := re.fullmatch(r"(HT_)?CARDS_OU_([\d.]+)", key):
        pts = c.ht_card_points if m[1] else c.card_points
        return None if pts is None else _ou(sum(pts), float(m[2]), sel)
    if key == "MOST_CARDS":
        return None if c.card_points is None else _sign(c.card_points[0] - c.card_points[1]) == sel
    if key == "RED_CARD":
        return None if c.reds is None else _yn(c.reds > 0, sel)
    if key == "PENALTY":
        return _yn(c.penalty, sel)
    return None


def card_points(events: list[dict], rules: dict, *, until_minute: int | None = None,
                regulation_max: int | None = None) -> tuple[tuple[int, int], int]:
    """Nesine 'Kart Puanı' per team from card events -> ((home, away), red_cards)."""
    subbed_off: dict[str, int] = {}
    if rules.get("exclude_after_substitution", True):
        for e in events:
            if e["type"] == "sub" and e.get("player_out_id"):
                subbed_off[str(e["player_out_id"])] = int(e["minute"] or 0)
    per_player: dict[tuple[str, str], dict] = {}
    for e in events:
        if e["type"] not in ("yellow", "red"):
            continue
        minute = int(e["minute"] or 0)
        if until_minute is not None and minute > until_minute:
            continue
        if regulation_max is not None and minute > regulation_max:
            continue
        pid = str(e.get("player_id") or e.get("player") or f"anon{len(per_player)}")
        if pid in subbed_off and minute > subbed_off[pid]:
            continue  # card shown to a player no longer on the pitch
        p = per_player.setdefault((e["team"], pid), {"yellow": False, "red": False, "second_yellow": False})
        if e["type"] == "yellow":
            p["yellow"] = True
        else:
            p["red"] = True
            p["second_yellow"] |= e.get("detail") == "second_yellow"
    pts = {"home": 0, "away": 0}
    reds = 0
    for (team, _), p in per_player.items():
        if p["second_yellow"]:
            pts[team] += rules.get("second_yellow_red_total", 3)
        else:
            pts[team] += (rules.get("yellow", 1) if p["yellow"] else 0) + (rules.get("red", 2) if p["red"] else 0)
        reds += p["red"]
    return (pts["home"], pts["away"]), reds


def _int(v) -> int | None:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def build_ctx(result: dict, events: list[dict], rules: dict) -> Ctx:
    H, A = _int(result.get("ft_home")), _int(result.get("ft_away"))
    c = Ctx(H=H, A=A, h1=_int(result.get("ht_home")), a1=_int(result.get("ht_away")))
    complete = str(result.get("events_complete")) in ("1", "True", "true")
    extra_time = bool(result.get("et_score")) or bool(result.get("pen_score"))
    reg_max = 90 if extra_time and rules.get("regulation_only", True) else None
    goals = [e for e in events if e["type"] == "goal" and (reg_max is None or int(e["minute"] or 0) <= reg_max)]
    if complete:
        c.goals = [e["team"] for e in sorted(goals, key=lambda e: (int(e["minute"] or 0), int(e.get("seq") or 0)))]
    ch, ca = _int(result.get("corners_home")), _int(result.get("corners_away"))
    if ch is not None and ca is not None:
        c.corners = (ch, ca)
    hch, hca = _int(result.get("ht_corners_home")), _int(result.get("ht_corners_away"))
    if hch is not None and hca is not None:
        c.ht_corners = (hch, hca)
    if events:  # no events at all = card data unknown
        c.card_points, c.reds = card_points(events, rules, regulation_max=reg_max)
        c.ht_card_points, _ = card_points(events, rules, until_minute=45)
        pens = any(e["type"] == "missed_penalty" or (e["type"] == "goal" and e.get("detail") == "penalty")
                   for e in events if reg_max is None or int(e["minute"] or 0) <= reg_max)
        c.penalty = True if pens else (False if complete else None)
    return c


def _b(v) -> int | None:
    return None if v is None else int(bool(v))


def settle_date(date: str, rules: dict | None = None, root: Path = DATA) -> pd.DataFrame:
    """Settle every stored selection of one match date. Returns the settled frame (also written)."""
    rules = rules or load("card_rules")
    results = read_partition("results", date, root)
    odds = read_partition("odds", date, root)
    if results.empty or odds.empty:
        return pd.DataFrame()
    events = read_partition("events", date, root)
    official = read_partition("official", date, root)
    ev_by_match = {mid: g.to_dict("records") for mid, g in events.groupby("match_id")} if not events.empty else {}
    off = {}
    if not official.empty:
        for r in official.itertuples(index=False):
            off[(r.event_code, r.market_id, r.selection_tr)] = (r.market_decided, r.highlight)

    sel = (odds.drop_duplicates(["event_code", "market_id", "selection_tr"], keep="last")
           .reindex(columns=["event_code", "match_id", "market_id", "market_type_id", "market_tr", "market_key", "line",
                             "family", "selection_tr", "selection"]))
    out = []
    for res in results.to_dict("records"):
        mid = res["match_id"]
        rows = sel[sel["match_id"] == mid]
        if rows.empty:
            continue
        void = res.get("result_type") == "void"
        ctx = None if void else build_ctx(res, [{**e, "minute": e.get("minute") or 0} for e in ev_by_match.get(mid, [])], rules)
        siblings = rows.groupby("market_id")["selection"].apply(list).to_dict()
        for r in rows.to_dict("records"):
            fam = r.get("family") or ""
            decided, hl = off.get((r["event_code"], r["market_id"], r["selection_tr"]), (None, None))
            hit_off = None if void or decided not in ("1", "True") else hl in ("1", "True")
            hit_eng = None
            if not void and ctx is not None and ctx.H is not None and r.get("market_key"):
                try:
                    hit_eng = engine(r["market_key"], r.get("selection") or "", ctx, siblings.get(r["market_id"]))
                except Exception:  # noqa: BLE001 - a malformed selection must not stop settlement
                    log.exception("engine failed for %s %s", r["market_key"], r.get("selection"))
            engine_only = fam in ENGINE_ONLY_FAMILIES
            if void:
                outcome, source = "void", "void"
            elif engine_only:
                outcome, source = hit_eng, "engine" if hit_eng is not None else "none"
            elif hit_off is not None:
                outcome, source = hit_off, "official"
            else:
                outcome, source = hit_eng, "engine" if hit_eng is not None else "none"
            out.append({
                **r, "date": date,
                "hit_official": _b(hit_off), "hit_engine": _b(hit_eng),
                "hit": outcome if outcome == "void" else _b(outcome),
                "hit_source": source,
                "engine_only": engine_only,
                "card_rule": rules.get("source") if fam == "cards" else None,
                "agree": None if hit_off is None or hit_eng is None else int(bool(hit_off) == bool(hit_eng)),
            })
    df = frame(out)
    if not df.empty:
        upsert_partition("settled", date, df, root)
        df = read_partition("settled", date, root)
    return df


def settle_dates(dates: list[str]) -> dict:
    rules = load("card_rules")
    stats = {"dates": [], "selections": 0, "official": 0, "engine": 0, "none": 0, "void": 0, "disagree": 0}
    for d in dates:
        df = settle_date(d, rules)
        if df.empty:
            continue
        stats["dates"].append(d)
        stats["selections"] += len(df)
        for k, v in df["hit_source"].value_counts().items():
            stats[k] = stats.get(k, 0) + int(v)
        stats["disagree"] += int((df["agree"] == 0).sum())
    write_mismatch_log()
    return stats


def write_mismatch_log(root: Path = DATA) -> int:
    """Rebuild data/settlement_mismatches.csv from all settled partitions (official vs engine disagreements)."""
    settled = read_table("settled", root=root)
    if settled.empty:
        return 0
    bad = settled[settled["agree"] == "0"]
    cols = ["date", "match_id", "event_code", "market_key", "market_tr", "line", "selection_tr", "selection",
            "hit_official", "hit_engine"]
    write_log_frame("settlement_mismatches", bad.reindex(columns=cols).sort_values(["date", "match_id", "market_key"]), root)
    return len(bad)
