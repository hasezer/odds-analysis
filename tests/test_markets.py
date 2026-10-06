import pytest

from odds_analysis.markets import normalize_market, normalize_selection


@pytest.mark.parametrize("name,key,line,family", [
    ("Maç Sonucu", "1X2", None, "score"),
    ("2,5 Alt/Üst", "OU_2.5", 2.5, "score"),
    ("1. Yarı 1,5 Alt/Üst", "HT_OU_1.5", 1.5, "score"),
    ("Hnd. MS (0:1)", "HANDICAP_-1", -1.0, "score"),
    ("Hnd. MS (2:0)", "HANDICAP_2", 2.0, "score"),
    ("Ev Sahibi 1,5 Alt/Üst", "TEAM_OU_home_1.5", 1.5, "score"),
    ("1. Yarı Deplasman 0,5 Alt/Üst", "HT_TEAM_OU_away_0.5", 0.5, "score"),
    ("MS ve 2,5 Alt/Üst", "1X2_AND_OU_2.5", 2.5, "score"),
    ("2,5 Alt/Üst ve Karşılıklı Gol", "OU_2.5_AND_BTTS", 2.5, "score"),
    ("1.Yarı ve 1.Yarı 1,5 Alt/Üst", "HT_1X2_AND_HT_OU_1.5", 1.5, "score"),
    ("10,5 Korner Alt/Üst", "CORNERS_OU_10.5", 10.5, "corners"),
    ("1.Yarı 4,5 Korner Alt/Üst", "HT_CORNERS_OU_4.5", 4.5, "ht_corners"),
    ("KornerTek/çift", "CORNERS_ODD_EVEN", None, "corners"),
    ("3,5 Kart Puanı Alt/Üst", "CARDS_OU_3.5", 3.5, "cards"),
    ("İlk Gol", "FIRST_GOAL", None, "first_goal"),
    ("Deplasman İki Yarıda da Gol Atar", "TEAM_SCORES_BOTH_HALVES_away", None, "score"),
    ("Takım İsabetli Şut", "TEAM_SHOTS_ON_TARGET", None, "team_stats"),
    ("Oyuncu Gol Atar", "PLAYER_GOL_ATAR", None, "player"),
])
def test_market_keys(name, key, line, family):
    m = normalize_market(name)
    assert (m.key, m.line, m.family) == (key, line, family)


def test_unknown_market():
    assert normalize_market("Tamamen Yeni Bir Market") is None


@pytest.mark.parametrize("name,sel,expected", [
    ("Maç Sonucu", "X", "draw"),
    ("Çifte Şans", "1-X", "1X"),
    ("2,5 Alt/Üst", "Üst", "over"),
    ("İlk Yarı/Maç Sonucu", "X/2", "draw/away"),
    ("MS ve Karşılıklı Gol", " MS1 & Yok", "home_no"),
    ("MS ve 2,5 Alt/Üst", "2 ve Üst", "away_over"),
    ("Hangi Takım Kaç Farkla Kazanır?", "Ev 3+", "home_3+"),
    ("İlk Gol", "Olmaz", "none"),
    ("1. Yarı / 2. Yarı Karşılıklı Gol", "Evet/Hayır", "yes/no"),
    ("İlk Yarı / Maç Skoru", "0-0 / 0-1", "0-0/0-1"),
    ("En Çok Gol Olacak Yarı", "2. Yarı", "2H"),
])
def test_selections(name, sel, expected):
    assert normalize_selection(normalize_market(name), sel) == expected


def test_team_names_replaced():
    m = normalize_market("Takım Şut")
    assert normalize_selection(m, "Galler 10+", "Galler", "Danimarka") == "home 10+"
