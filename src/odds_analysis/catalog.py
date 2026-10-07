"""Nesine market/selection names -> SCHEMA.md keys.

Builds on markets.py (Turkish name -> internal key with the line inside, e.g. OU_2.5, used by the settlement
engine) and turns it into the stored form: market_key without the line (OU), family, line, handicap_home /
handicap_away, settle_source and a normalised selection_key (1, X, 2, OVER, UNDER, YES, NO, 1X, "1/1", "2-1"...).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache

import yaml

from .config import ROOT

from .markets import Market, normalize_market, normalize_selection

# internal key prefix (line removed, upper case) -> schema family
FAMILY_BY_KEY = {
    "1X2": "result", "DC": "result", "CORRECT_SCORE": "result", "WINNING_MARGIN": "result",
    "TEAM_WIN_TO_NIL_HOME": "result", "TEAM_WIN_TO_NIL_AWAY": "result",
    "OU": "goals", "BTTS": "goals", "ODD_EVEN": "goals", "GOAL_RANGE": "goals", "FIRST_GOAL": "goals",
    "TEAM_OU_HOME": "goals", "TEAM_OU_AWAY": "goals",
    "HANDICAP": "handicap",
    "1X2_AND_OU": "combo", "1X2_AND_BTTS": "combo", "OU_AND_BTTS": "combo", "HT_1X2_AND_HT_BTTS": "combo",
    "HT_1X2_AND_HT_OU": "combo",
    "PENALTY": "special",
}
ENGINE_KEYS = {  # no winner marks from Nesine (seen in the history popups): settled by our engine
    "FIRST_GOAL", "2H_BTTS", "PENALTY",
}
# selections that each cover several outcomes: implied probabilities sum to ~N (double chance: 2 of 3 results)
OVERLAP = {"DC": 2, "HT_DC": 2}
RENAME = {"CARDS_OU": "CARD_POINTS_OU", "HT_CARDS_OU": "HT_CARD_POINTS_OU", "MOST_CARDS": "MOST_CARD_POINTS"}
OLD_FAMILY = {"corners": "corners", "ht_corners": "corners", "corner_timing": "corners", "cards": "cards",
              "player": "player", "team_stats": "special", "special": "special", "penalty": "special"}

PLAYER_KEYS = {  # Nesine "Oyuncu ..." markets -> English keys (unknown ones keep the Turkish slug)
    "PLAYER_GOL_ATAR": "PLAYER_TO_SCORE", "PLAYER_ILK_GOLU_ATAR": "PLAYER_FIRST_GOAL",
    "PLAYER_SUT_CEKER": "PLAYER_SHOTS", "PLAYER_KALEYI_BULAN_SUT_CEKER": "PLAYER_SHOTS_ON_TARGET",
    "PLAYER_ASIST_YAPAR": "PLAYER_ASSISTS", "PLAYER_KART_GORUR": "PLAYER_CARDED",
    "PLAYER_OZEL_BAHISLERI": "PLAYER_SPECIALS", "PLAYER_FAUL_ALIR": "PLAYER_FOULED", "PLAYER_FAUL_YAPAR": "PLAYER_FOULS",
    "PLAYER_FRIKIKTEN_GOL_ATAR": "PLAYER_FREE_KICK_GOAL", "PLAYER_KAFA_ILE_GOL_ATAR": "PLAYER_HEADER_GOAL",
    "PLAYER_CEZA_SAHASI_DISINDAN_GOL_ATAR": "PLAYER_GOAL_OUTSIDE_BOX",
    "PLAYER_HER_IKI_YARIDA_DA_GOL_ATAR": "PLAYER_SCORES_BOTH_HALVES", "PLAYER_PAS_YAPAR": "PLAYER_PASSES",
    "PLAYER_TOP_CALAR": "PLAYER_TACKLES", "PLAYER_GOL_ATAR_VE_ASIST_YAPAR": "PLAYER_GOAL_AND_ASSIST",
    "PLAYER_GOL_ATAR_VEYA_ASIST_YAPAR": "PLAYER_GOAL_OR_ASSIST",
    "PLAYER_GOL_ATAR_VE_TAKIMI_KAZANIR": "PLAYER_SCORES_AND_TEAM_WINS", "PLAYER_HAT_TRICK_YAPAR": "PLAYER_HAT_TRICK",
    "PLAYER_OFSAYTA_DUSER": "PLAYER_OFFSIDE",
}
SEL = {"home": "1", "draw": "X", "away": "2", "over": "OVER", "under": "UNDER", "yes": "YES", "no": "NO",
       "odd": "ODD", "even": "EVEN", "1H": "1H", "2H": "2H", "equal": "EQUAL", "none": "NONE"}
_ASCII = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")


@dataclass(frozen=True)
class MarketInfo:
    market_key: str | None
    family: str | None
    line: float | None
    handicap_home: int | None
    handicap_away: int | None
    settle_source: str
    engine: Market | None  # internal market for the settlement engine


def _fmt(x: float) -> str:
    return f"{x:g}"


def classify(name_tr: str) -> MarketInfo:
    m = normalize_market(name_tr)
    if m is None:  # not mapped yet: stored, logged as unmapped, not settled
        return MarketInfo(None, None, None, None, None, "none", None)
    key, line = m.key, m.line
    hh = ha = None
    if key.startswith("HANDICAP_"):
        h = re.search(r"\((\d+):(\d+)\)", name_tr)
        hh, ha = (int(h[1]), int(h[2])) if h else (None, None)
        base, line = "HANDICAP", None
    else:
        base = key.replace(f"_{_fmt(line)}", "") if line is not None else key
    base = base.upper()
    base = RENAME.get(base, PLAYER_KEYS.get(base, base))
    family = OLD_FAMILY.get(m.family) or FAMILY_BY_KEY.get(base) or _family_from_prefix(base)
    if family in ("player", "special") and base not in ENGINE_KEYS:
        source = "none"
    elif family in ("corners", "cards") or base in ENGINE_KEYS or base.startswith(("RED_CARD",)):
        source = "engine"
    else:
        source = "official"
    return MarketInfo(base, family, line, hh, ha, source, m)


def _family_from_prefix(base: str) -> str:
    if base.startswith(("HT_", "2H_", "BOTH_HALVES", "MORE_GOALS_HALF", "TEAM_MORE_GOALS_HALF", "TEAM_SCORES_BOTH",
                        "TEAM_WIN_EITHER_HALF", "TEAM_WIN_BOTH_HALVES")):
        return "halves"
    return "special"


def slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9+\-/]+", "_", s.translate(_ASCII)).strip("_").upper()


def selection_key(info: MarketInfo, sel_tr: str, home: str | None = None, away: str | None = None) -> tuple[str, str]:
    """(stored selection_key, internal token for the settlement engine)."""
    sel_tr = re.sub(r"\s+", " ", (sel_tr or "").strip())
    if sel_tr in ("", "-"):  # Nesine's unnamed placeholder (seen in player markets, never priced)
        return "UNNAMED", sel_tr
    if info.engine is None:
        return slug(sel_tr) or "?", sel_tr
    tok = normalize_selection(info.engine, sel_tr, home, away)
    k = info.market_key or ""
    if tok in SEL:
        return SEL[tok], tok
    if tok in ("1X", "12", "X2"):
        return tok, tok
    if k in ("HT_FT", "HT_2H_BTTS") and "/" in tok:
        a, _, b = tok.partition("/")
        return f"{SEL.get(a, a)}/{SEL.get(b, b)}", tok
    if k in ("CORRECT_SCORE", "HT_CORRECT_SCORE", "HT_FT_CORRECT_SCORE"):
        return ("OTHER" if tok == "Diğer" else tok), tok
    if k == "WINNING_MARGIN":
        w = re.fullmatch(r"(home|away)_(\d+\+?)", tok)
        return (f"{SEL[w[1]]}_{w[2]}" if w else SEL.get(tok, slug(tok))), tok
    if "_" in tok and all(p in SEL for p in tok.split("_")):  # combos: home_over -> 1&OVER
        return "&".join(SEL[p] for p in tok.split("_")), tok
    if re.fullmatch(r"\d+(-\d+|\+)", tok):  # goal/corner ranges 2-3, 6+
        return tok, tok
    return slug(tok) or "?", tok


@cache
def selected_markets() -> tuple[dict, ...]:
    """config/markets.yaml: the markets this project collects, in view-column order."""
    data = yaml.safe_load((ROOT / "config" / "markets.yaml").read_text(encoding="utf-8"))
    return tuple(data["markets"])


def selection_index() -> dict[tuple[str, float | None], dict]:
    return {(m["key"], m.get("line")): m for m in selected_markets()}


def is_selected(info: MarketInfo) -> bool:
    return info.market_key is not None and (info.market_key, info.line) in selection_index()
