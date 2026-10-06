"""Settlement engine tests on real matches (04.10.2026), checked against Nesine's own result marks."""

import csv
import json
from pathlib import Path

import pytest

from odds_analysis.markets import normalize_market, normalize_selection
from odds_analysis.parsers import parse_match_data
from odds_analysis.results import events_complete, ft90
from odds_analysis.settle import Ctx, build_ctx, card_points, engine

FIX = Path(__file__).parent / "fixtures"
RULES = {"yellow": 1, "red": 2, "second_yellow_red_total": 3, "exclude_after_substitution": True, "regulation_only": True}
TEAMS = {4445150: ("Portekiz", "Norveç"), 4445151: ("Galler", "Danimarka"), 4445126: ("Yunanistan", "Almanya")}


def ctx_for(mid: int, corners=None) -> Ctx:
    raw = json.loads((FIX / "match_data.json").read_text(encoding="utf-8"))[str(mid)]
    md = parse_match_data(json.dumps(raw))
    score = ft90(md)
    result = {"ft_home": score[0], "ft_away": score[1], "ht_home": md["ht"][0], "ht_away": md["ht"][1],
              "events_complete": events_complete(md, score),
              "corners_home": corners[0] if corners else None, "corners_away": corners[1] if corners else None}
    events = [{**e, "seq": i} for i, e in enumerate(md["events"])]
    return build_ctx(result, events, RULES)


def official_marks():
    with (FIX / "official_marks.csv").open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["market_decided"] == "1":
                yield int(r["match_id"]), r["market_tr"], r["selection_tr"], r["highlight"] == "1"


def test_portekiz_norvec_basics():
    c = ctx_for(4445150, corners=(6, 4))
    assert (c.H, c.A, c.h1, c.a1, c.h2, c.a2) == (2, 1, 1, 1, 1, 0)
    assert c.goals == ["away", "home", "home"]
    assert engine("1X2", "home", c) and not engine("1X2", "draw", c)
    assert engine("HT_FT", "draw/home", c)
    assert engine("OU_2.5", "over", c) and engine("BTTS", "yes", c)
    assert engine("FIRST_GOAL", "away", c)
    assert engine("2H_1X2", "home", c)
    assert engine("HANDICAP_-1", "draw", c)      # Hnd. MS (0:1): 2-(1+1) = draw
    assert engine("HANDICAP_1", "home", c)       # Hnd. MS (1:0): (2+1)-1
    assert engine("TEAM_SCORES_BOTH_HALVES_home", "yes", c)
    assert engine("TEAM_SCORES_BOTH_HALVES_away", "no", c)
    assert engine("1X2_AND_OU_2.5", "home_over", c)
    assert engine("WINNING_MARGIN", "home_1", c)
    assert engine("HT_FT_CORRECT_SCORE", "1-1/2-1", c)
    assert engine("CORNERS_OU_9.5", "over", c) and engine("MOST_CORNERS", "home", c)
    assert engine("CORNER_RANGE", "9-11", c)
    assert engine("HT_CORNERS_OU_4.5", "over", c) is None  # no first-half corners anywhere


def test_portekiz_norvec_card_points():
    # 12' Cancelo Y, 86' Conceição Y + 2nd-yellow red, 88' B. Fernandes Y (subbed off at 90' -> card before the sub counts)
    c = ctx_for(4445150)
    assert c.card_points == (1 + 3 + 1, 0)
    assert c.reds == 1
    assert c.ht_card_points == (1, 0)
    assert engine("CARDS_OU_4.5", "over", c)
    assert engine("MOST_CARDS", "home", c)
    assert engine("RED_CARD", "yes", c)


def test_card_after_substitution_ignored():
    events = [
        {"type": "sub", "minute": 60, "team": "home", "player_id": 2, "player_out_id": 1},
        {"type": "yellow", "minute": 70, "team": "home", "player_id": 1},   # already off: bench card
        {"type": "red", "minute": 80, "team": "away", "player_id": 9, "detail": "straight_red"},
    ]
    assert card_points(events, RULES) == ((0, 2), 1)


def test_disallowed_goal_does_not_break_first_goal():
    c = ctx_for(4445126)  # Yunanistan-Almanya 0-0; feed still lists a 32' Almanya goal
    assert (c.H, c.A) == (0, 0)
    assert c.goals is None
    assert engine("FIRST_GOAL", "none", c) is True
    assert engine("FIRST_GOAL", "away", c) is False


@pytest.mark.parametrize("mid", [4445150, 4445151, 4445126])
def test_engine_agrees_with_nesine_marks(mid):
    """Every market Nesine marked after full time must be settled identically by the engine."""
    c = ctx_for(mid)
    home, away = TEAMS[mid]
    checked, disagreements = 0, []
    siblings: dict[str, list[str]] = {}
    for m, market_tr, sel_tr, _ in official_marks():
        if m == mid:
            siblings.setdefault(market_tr, []).append(sel_tr)
    for m, market_tr, sel_tr, won in official_marks():
        if m != mid:
            continue
        mk = normalize_market(market_tr)
        if mk is None or mk.family in ("player", "team_stats", "special", "corners", "cards"):
            continue
        got = engine(mk.key, normalize_selection(mk, sel_tr, home, away), c, siblings.get(market_tr))
        if got is None:
            continue
        checked += 1
        if got != won:
            disagreements.append((market_tr, sel_tr, won, got))
    assert checked > 100
    assert disagreements == []


def test_other_score():
    c = ctx_for(4445150)  # 2-1
    assert engine("CORRECT_SCORE", "Diğer", c, ["1-0", "2-1", "Diğer"]) is False
    assert engine("CORRECT_SCORE", "Diğer", c, ["1-0", "2-0", "Diğer"]) is True


def test_settle_date_end_to_end(tmp_path):
    """Storage -> settlement: official wins where marked, engine elsewhere, corners/cards engine-only, void match."""
    from odds_analysis import storage
    from odds_analysis.settle import settle_date

    d = "2026-10-04"
    storage.upsert_partition("results", d, storage.frame([
        {"match_id": 4445150, "event_code": "3180547", "result_type": "final", "status": "MS", "ft_home": 2, "ft_away": 1,
         "ht_home": 1, "ht_away": 1, "events_complete": 1, "corners_home": 6, "corners_away": 4},
        {"match_id": 999, "event_code": "111", "result_type": "void", "status": "Ert."},
    ]), root=tmp_path)
    storage.upsert_partition("events", d, storage.frame([
        {"match_id": 4445150, "seq": 0, "minute": 36, "team": "away", "type": "goal"},
        {"match_id": 4445150, "seq": 1, "minute": 38, "team": "home", "type": "goal"},
        {"match_id": 4445150, "seq": 2, "minute": 79, "team": "home", "type": "goal"},
        {"match_id": 4445150, "seq": 3, "minute": 86, "team": "home", "type": "red", "detail": "second_yellow", "player_id": 5},
    ]), root=tmp_path)
    odds = [
        ("3180547", 4445150, "m1", "1X2", "score", "1", "home"), ("3180547", 4445150, "m1", "1X2", "score", "X", "draw"),
        ("3180547", 4445150, "m2", "FIRST_GOAL", "first_goal", "2", "away"),
        ("3180547", 4445150, "m3", "CORNERS_OU_9.5", "corners", "Üst", "over"),
        ("3180547", 4445150, "m4", "CARDS_OU_2.5", "cards", "Üst", "over"),
        ("3180547", 4445150, "m5", "PLAYER_GOL_ATAR", "player", "Ramos", "Ramos"),
        ("111", 999, "m9", "1X2", "score", "1", "home"),
    ]
    storage.upsert_partition("odds", d, storage.frame([
        {"event_code": e, "match_id": mid, "market_id": mk, "market_key": key, "family": fam, "selection_tr": st,
         "selection": sel, "snapshot_utc": "2026-10-04T10:00:00Z", "odds": 2.0, "snapshot_type": "opening"}
        for e, mid, mk, key, fam, st, sel in odds]), root=tmp_path)
    storage.upsert_partition("official", d, storage.frame([
        {"event_code": "3180547", "market_id": "m1", "selection_tr": "1", "market_decided": 1, "highlight": 1},
        {"event_code": "3180547", "market_id": "m1", "selection_tr": "X", "market_decided": 1, "highlight": 0},
    ]), root=tmp_path)

    df = settle_date(d, RULES, root=tmp_path).set_index(["match_id", "market_id", "selection_tr"])
    row = lambda m, mk, s: df.loc[(str(m), mk, s)]
    assert (row(4445150, "m1", "1")[["hit", "hit_source", "hit_official", "hit_engine", "agree"]].tolist()
            == ["1", "official", "1", "1", "1"])
    assert row(4445150, "m1", "X")["hit"] == "0"
    assert (row(4445150, "m2", "2")[["hit", "hit_source"]].tolist()) == ["1", "engine"]
    assert (row(4445150, "m3", "Üst")[["hit", "hit_source", "engine_only"]].tolist()) == ["1", "engine", "1"]
    assert (row(4445150, "m4", "Üst")[["hit", "hit_source"]].tolist()) == ["1", "engine"]  # 3 card points > 2.5
    assert row(4445150, "m5", "Ramos")["hit_source"] == "none"
    assert (row(999, "m9", "1")[["hit", "hit_source"]].tolist()) == ["void", "void"]
