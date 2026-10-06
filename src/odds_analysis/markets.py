"""Turkish Nesine market names -> English market_key, line and normalized selection.

normalize() returns None for markets it does not know; callers log those to
data/unmapped_markets.csv. Known-but-not-engine-settleable markets (players, team
shots, specials...) are mapped with family 'player'/'team_stats'/'special' so the
official result (B highlight) can still settle them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

SIDE = {"Ev Sahibi": "home", "Deplasman": "away"}
RES = {"1": "home", "X": "draw", "2": "away", "0": "draw"}
OU = {"Alt": "under", "Üst": "over"}
YN = {"Var": "yes", "Yok": "no", "Evet": "yes", "Hayır": "no"}
HALF = {"1. Yarı": "1H", "2. Yarı": "2H", "Eşit": "equal"}
ODD_EVEN = {"Tek": "odd", "Çift": "even"}
DC = {"1-X": "1X", "1/X": "1X", "1-2": "12", "1/2": "12", "X-2": "X2", "X/2": "X2"}


@dataclass(frozen=True)
class Market:
    key: str
    line: float | None
    family: str  # score | first_goal | corners | ht_corners | corner_timing | cards | penalty | player | team_stats | special


def _num(s: str) -> float:
    return float(s.replace(",", "."))


def _fmt_line(x: float) -> str:
    return f"{x:g}"


# (regex, builder(match) -> (key_template, line, family))
_RULES: list[tuple[re.Pattern, callable]] = []


def rule(pattern: str):
    def deco(fn):
        _RULES.append((re.compile(pattern), fn))
        return fn
    return deco


@rule(r"^Maç Sonucu$")
def _(m): return "1X2", None, "score"
@rule(r"^Çifte Şans$")
def _(m): return "DC", None, "score"
@rule(r"^Karşılıklı Gol$")
def _(m): return "BTTS", None, "score"
@rule(r"^(\d+,\d) Alt/Üst$")
def _(m): return "OU_{l}", _num(m[1]), "score"
@rule(r"^1\. Yarı Sonucu$")
def _(m): return "HT_1X2", None, "score"
@rule(r"^2\. Yarı Sonucu$")
def _(m): return "2H_1X2", None, "score"
@rule(r"^1\. Yarı Çifte Şans$")
def _(m): return "HT_DC", None, "score"
@rule(r"^1\. Yarı (\d+,\d) Alt/Üst$")
def _(m): return "HT_OU_{l}", _num(m[1]), "score"
@rule(r"^2\. Yarı (\d+,\d) Alt/Üst$")
def _(m): return "2H_OU_{l}", _num(m[1]), "score"
@rule(r"^1\. Yarı Karşılıklı Gol$")
def _(m): return "HT_BTTS", None, "score"
@rule(r"^2\. Yarı Karşılıklı Gol$")
def _(m): return "2H_BTTS", None, "score"
@rule(r"^1\. Yarı / 2\. Yarı Karşılıklı Gol$")
def _(m): return "HT_2H_BTTS", None, "score"
@rule(r"^İlk Yarı ?/ ?Maç Sonucu$")
def _(m): return "HT_FT", None, "score"
@rule(r"^Hnd\. MS \((\d+):(\d+)\)$")
def _(m): return "HANDICAP_{l}", float(int(m[1]) - int(m[2])), "score"
@rule(r"^Tek/Çift$")
def _(m): return "ODD_EVEN", None, "score"
@rule(r"^1\. Yarı Tek/Çift$")
def _(m): return "HT_ODD_EVEN", None, "score"
@rule(r"^Toplam Gol Aralığı$")
def _(m): return "GOAL_RANGE", None, "score"
@rule(r"^1\. Yarı Gol Aralığı$")
def _(m): return "HT_GOAL_RANGE", None, "score"
@rule(r"^(Ev Sahibi|Deplasman) (\d+,\d) Alt/Üst$")
def _(m): return f"TEAM_OU_{SIDE[m[1]]}_{{l}}", _num(m[2]), "score"
@rule(r"^1\. Yarı (Ev Sahibi|Deplasman) (\d+,\d) Alt/Üst$")
def _(m): return f"HT_TEAM_OU_{SIDE[m[1]]}_{{l}}", _num(m[2]), "score"
@rule(r"^İlk Gol$")
def _(m): return "FIRST_GOAL", None, "first_goal"
@rule(r"^En Çok Gol Olacak Yarı$")
def _(m): return "MORE_GOALS_HALF", None, "score"
@rule(r"^(Ev Sahibi|Deplasman) Hangi Yarıda Daha Çok Gol Atar$")
def _(m): return f"TEAM_MORE_GOALS_HALF_{SIDE[m[1]]}", None, "score"
@rule(r"^(Ev Sahibi|Deplasman) İki Yarıda da Gol Atar$")
def _(m): return f"TEAM_SCORES_BOTH_HALVES_{SIDE[m[1]]}", None, "score"
@rule(r"^(Ev Sahibi|Deplasman) Gol Yemeden Kazanır$")
def _(m): return f"TEAM_WIN_TO_NIL_{SIDE[m[1]]}", None, "score"
@rule(r"^(Ev Sahibi|Deplasman) Yarı Kazanır$")
def _(m): return f"TEAM_WIN_EITHER_HALF_{SIDE[m[1]]}", None, "score"
@rule(r"^(Ev Sahibi|Deplasman) İki Yarıyı da Kazanır$")
def _(m): return f"TEAM_WIN_BOTH_HALVES_{SIDE[m[1]]}", None, "score"
@rule(r"^İki Yarı da (\d+,\d) Alt$")
def _(m): return "BOTH_HALVES_UNDER_{l}", _num(m[1]), "score"
@rule(r"^İki Yarı da (\d+,\d) Üst$")
def _(m): return "BOTH_HALVES_OVER_{l}", _num(m[1]), "score"
@rule(r"^Hangi Takım Kaç Farkla Kazanır\??$")
def _(m): return "WINNING_MARGIN", None, "score"
@rule(r"^Maç Skoru$")
def _(m): return "CORRECT_SCORE", None, "score"
@rule(r"^1\. Yarı Skoru$")
def _(m): return "HT_CORRECT_SCORE", None, "score"
@rule(r"^İlk Yarı / Maç Skoru$")
def _(m): return "HT_FT_CORRECT_SCORE", None, "score"
@rule(r"^MS ve (\d+,\d) Alt/Üst$")
def _(m): return "1X2_AND_OU_{l}", _num(m[1]), "score"
@rule(r"^MS ve Karşılıklı Gol$")
def _(m): return "1X2_AND_BTTS", None, "score"
@rule(r"^(\d+,\d) Alt/Üst ve Karşılıklı Gol$")
def _(m): return "OU_{l}_AND_BTTS", _num(m[1]), "score"
@rule(r"^1\. ?Yarı ve 1\. ?Yarı KG$")
def _(m): return "HT_1X2_AND_HT_BTTS", None, "score"
@rule(r"^1\. ?Yarı ve 1\. ?Yarı (\d+,\d) Alt/Üst$")
def _(m): return "HT_1X2_AND_HT_OU_{l}", _num(m[1]), "score"
# corners
@rule(r"^(\d+,\d) Korner Alt/Üst$")
def _(m): return "CORNERS_OU_{l}", _num(m[1]), "corners"
@rule(r"^1\. ?Yarı (\d+,\d) Korner Alt/Üst$")
def _(m): return "HT_CORNERS_OU_{l}", _num(m[1]), "ht_corners"
@rule(r"^En Çok Korner$")
def _(m): return "MOST_CORNERS", None, "corners"
@rule(r"^1\. Yarı En Çok Korner$")
def _(m): return "HT_MOST_CORNERS", None, "ht_corners"
@rule(r"^Toplam Korner Aralığı$")
def _(m): return "CORNER_RANGE", None, "corners"
@rule(r"^1\. Yarı Korner Aralığı$")
def _(m): return "HT_CORNER_RANGE", None, "ht_corners"
@rule(r"^İlk Korner$")
def _(m): return "FIRST_CORNER", None, "corner_timing"
@rule(r"^Korner ?Tek/[çÇ]ift$")
def _(m): return "CORNERS_ODD_EVEN", None, "corners"
# cards
@rule(r"^(\d+,\d) Kart Puanı Alt/Üst$")
def _(m): return "CARDS_OU_{l}", _num(m[1]), "cards"
@rule(r"^1\. Yarı (\d+,\d) Kart Puanı Alt/Üst$")
def _(m): return "HT_CARDS_OU_{l}", _num(m[1]), "cards"
@rule(r"^Hangi Takım Daha Çok Kart Puanı Alır\??$")
def _(m): return "MOST_CARDS", None, "cards"
@rule(r"^Kırmızı Kart$")
def _(m): return "RED_CARD", None, "cards"
@rule(r"^Penaltı Olur Mu\??$")
def _(m): return "PENALTY", None, "penalty"
# no engine settlement: official result only
@rule(r"^Oyuncu (.+)$")
def _(m): return "PLAYER_" + _slug(m[1]), None, "player"
@rule(r"^Kaleci En Az Kaç Kurtarış Yapar\??$")
def _(m): return "GK_SAVES", None, "player"
TEAM_STAT_KEYS = {"Şut": "SHOTS", "İsabetli Şut": "SHOTS_ON_TARGET", "Faul": "FOULS", "Ofsayt": "OFFSIDES",
                  "Kale Vuruşu": "GOAL_KICKS", "Taç Atışı": "THROW_INS"}
@rule(r"^Takım (Şut|İsabetli Şut|Faul|Ofsayt|Kale Vuruşu|Taç Atışı)$")
def _(m): return "TEAM_" + TEAM_STAT_KEYS[m[1]], None, "team_stats"
@rule(r"^Karşılaşma (Özel|Kombo) Bahisleri$")
def _(m): return "MATCH_" + ("SPECIALS" if m[1] == "Özel" else "COMBOS"), None, "special"


_SLUG = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")


def _slug(s: str) -> str:
    s = re.sub(r"\(Uzt\. Dahil\)", "", s).translate(_SLUG)
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_").upper()


def normalize_market(name: str) -> Market | None:
    name = re.sub(r"\s+", " ", (name or "").strip())
    for pat, fn in _RULES:
        m = pat.match(name)
        if m:
            key, line, family = fn(m)
            key = key.replace("{l}", _fmt_line(line)) if line is not None else key
            return Market(key, line, family)
    return None


def _team_sub(sel: str, home: str | None, away: str | None) -> str:
    for name, tag in ((home, "home"), (away, "away")):
        if name and name in sel:
            sel = sel.replace(name, tag)
    return sel


def normalize_selection(market: Market, sel: str, home: str | None = None, away: str | None = None) -> str:
    """Raw Turkish outcome name -> normalized English token (unknown parts are kept as-is)."""
    s = re.sub(r"\s+", " ", (sel or "").strip())
    k = market.key
    if k in ("1X2", "HT_1X2", "2H_1X2", "MOST_CORNERS", "FIRST_CORNER", "HT_MOST_CORNERS", "MOST_CARDS", "FIRST_GOAL") or k.startswith("HANDICAP_"):
        return {"Olmaz": "none"}.get(s, RES.get(s, s))
    if k in ("DC", "HT_DC"):
        return DC.get(s, s)
    if "OU_" in k and "_AND_" not in k and not k.startswith("1X2") and not k.startswith("HT_1X2"):
        return OU.get(s, s)
    if k in ("BTTS", "HT_BTTS", "2H_BTTS", "PENALTY", "RED_CARD") or k.startswith(("TEAM_SCORES", "TEAM_WIN", "BOTH_HALVES")):
        return YN.get(s, s)
    if k in ("ODD_EVEN", "HT_ODD_EVEN", "CORNERS_ODD_EVEN"):
        return ODD_EVEN.get(s, s)
    if k == "MORE_GOALS_HALF" or k.startswith("TEAM_MORE_GOALS_HALF"):
        return HALF.get(s, s)
    if k == "HT_FT":
        a, _, b = s.partition("/")
        return f"{RES.get(a.strip(), a)}/{RES.get(b.strip(), b)}"
    if k == "HT_2H_BTTS":
        a, _, b = s.partition("/")
        return f"{YN.get(a.strip(), a)}/{YN.get(b.strip(), b)}"
    if k in ("CORRECT_SCORE", "HT_CORRECT_SCORE"):
        return s.replace(" ", "")
    if k == "HT_FT_CORRECT_SCORE":
        return s.replace(" ", "")
    if k == "WINNING_MARGIN":
        m = re.match(r"^(Ev|Dep) (\d\+?)$", s)
        return f"{'home' if m[1] == 'Ev' else 'away'}_{m[2]}" if m else ("draw" if s in ("0", "X", "Beraberlik") else s)
    if k.startswith("1X2_AND_OU_"):
        m = re.match(r"^([1X2]) ve (Alt|Üst)$", s)
        return f"{RES[m[1]]}_{OU[m[2]]}" if m else s
    if k == "1X2_AND_BTTS":
        m = re.match(r"^MS([1X2]) & (Var|Yok)$", s)
        return f"{RES[m[1]]}_{YN[m[2]]}" if m else s
    if k.startswith("OU_") and k.endswith("_AND_BTTS"):
        m = re.match(r"^(Alt|Üst) & (Var|Yok)$", s)
        return f"{OU[m[1]]}_{YN[m[2]]}" if m else s
    if k == "HT_1X2_AND_HT_BTTS":
        m = re.match(r"^1\.Y ([1X2]) & (Var|Yok)$", s)
        return f"{RES[m[1]]}_{YN[m[2]]}" if m else s
    if k.startswith("HT_1X2_AND_HT_OU_"):
        m = re.match(r"^1\.Y ([1X2]) & (Alt|Üst)$", s)
        return f"{RES[m[1]]}_{OU[m[2]]}" if m else s
    if market.family in ("team_stats", "special", "player"):
        return _team_sub(s, home, away)
    return s
