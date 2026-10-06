"""Parser tests on small excerpts of real responses (Portekiz-Norveç, 04.10.2026, MS 2-1, İY 1-1)."""

from odds_analysis.parsers import (
    parse_day_list,
    parse_match_data,
    parse_odds_popup,
    parse_odds_value,
    parse_stats_box,
)

DAY_LIST = """<table class="iddaa-oyna-table">
<tr class="iddaa-oyna-title2"><td colspan="7" class="sortratecls" rateSort="tarih_1">04.10.2026</td></tr>
<tr class="alt2" id="Tr2">
<td width="45" align="center">21:45</td>
<td width="25" style="cursor:pointer" onclick="popLeague(10975)"><img src="//im.mackolik.com/img/groups/545.gif" /></td>
<td width="35" style="cursor:pointer" onclick="popLeague(10975)">AVUL</td>
<td width="20"></td><td width="20"><a href="javascript:popComparison(4445150)"></a></td><td width="22">&nbsp;</td>
<td width="17" class="mbs-green"><img src="//im.mackolik.com/img5/iddaa/mbs1.png"></td>
<td><a class='iddaa-rows-style' href='javascript:popTeam(670)'>Portekiz <span class='cc-hand'></span></a>  <a class='iddaa-rows-style' href='javascript:popMatch(4445150,"ByDate")'> - </a>  <a class='iddaa-rows-style' href='javascript:popTeam(481)'>Norveç <span class='cc-hand'></span></a></td>
<td align="center">1-1</td>
<td align="center" onclick="popMatch(4445150)"><b>2 - 1</b></td>
<td align="center">22316</td>
<td><a href="javascript:openOddsDialog('1', 'Maç Sonucu', ['1','X','2'], ['1,50', '3,96', '3,93'], null, 'openBmIddaa', '3180547', '83210964', ['1','2','3'])" class="iddaa-rate MS1">1.50</a></td>
<td><a href="javascript:openOddsDialog('1', 'Maç Sonucu', ['1','X','2'], ['1,50', '3,96', '3,93'], null, 'openBmIddaa', '3180547', '83210964', ['1','2','3'])" class="iddaa-rate MSX">3.96</a></td>
<td align="center">22331</td>
<td><a href="javascript:openOddsDialog('1', '2,5 Gol Alt/Üst', ['Alt','Üst'], ['2,89', '-'], null, 'openBmIddaa', '3180547', '83214094', ['1','2'])" class="iddaa-rate AU1">2.89</a></td>
</tr></table>"""

MATCH_DATA = (
    '{"seq":133,"home":"Portekiz","away":"Norveç","d":{"s":"2 - 1","p":0,"st":"MS","ht":"1 - 1","ft":"","et":"","pt":"","time":90},'
    '"h":[],"a":[],"e":[[1,12,234897,"Joao Cancelo",2,{}],'
    '[2,36,284479,"Kristoffer Ajer",1,{"d":1,"astId":290143,"astName":"Martin Odegaard"}],'
    '[1,38,234897,"Joao Cancelo",1,{"d":1,"astId":566252,"astName":"Nuno Mendes"}],'
    '[1,63,391824,"Diogo Dalot",4,{"d":234897,"sub":"Joao Cancelo"}],'
    '[1,79,543105,"Gonçalo Ramos",1,{"d":1,"astId":475166,"astName":"Joao Felix"}],'
    '[1,86,562395,"Francisco Conceiçao",2,{}],[1,86,562395,"Francisco Conceiçao",3,{"d":1}],'
    '[1,88,237813,"Bruno Fernandes",2,{}]],"sv":["",""]}'
)

STATS = """<div class="match-statistics-rows-2"><div class="team-1-statistics-text">6</div>
<div class="statistics-title-text">Korner</div><div class="team-2-statistics-text">4</div></div>
<div class="match-statistics-rows"><div class="team-1-statistics-text">%59</div>
<div class="statistics-title-text">Topla Oynama</div><div class="team-2-statistics-text">%41</div></div>"""

POPUP = (
    '﻿{"source":"dn","date_time_utc":"2026-10-06 10:13:31","data":{"matches":[{"id":4931671,"status":"Played",'
    '"is_awarded":false,"start_time":"2026-10-04 18:45:00","iddaa_code":"3179478","bookies":[{"id":14,"name":"Nesine",'
    '"markets":[{"id":83123287,"code":"21959","name":"Maç Sonucu","mbc":1,"outcomes":['
    '{"name":"1","key":"1","value":"3.15","highlight":false,"market_type_id":1},'
    '{"name":"X","key":"x","value":"3.07","highlight":false,"market_type_id":1},'
    '{"name":"2","key":"2","value":"1.87","highlight":true,"market_type_id":1}]},'
    '{"id":1,"code":"21997","name":"0,5 Alt/Üst","sov":0.5,"mbc":1,"outcomes":['
    '{"name":"Alt","value":"9.36","highlight":false},{"name":"Üst","value":"-","highlight":true}]}]},'
    '{"id":15,"name":"Oley","markets":[]}]}]}}'
)


def test_parse_odds_value():
    assert parse_odds_value("2,58") == 2.58
    assert parse_odds_value("2.58") == 2.58
    assert parse_odds_value("-") is None
    assert parse_odds_value("") is None
    assert parse_odds_value(None) is None


def test_day_list_row():
    (row,) = parse_day_list(DAY_LIST)
    assert row["date"] == "2026-10-04"
    assert row["kickoff_local"] == "21:45"
    assert row["league_code"] == "AVUL"
    assert row["mbs"] == 1
    assert row["mackolik_match_id"] == 4445150
    assert (row["home_team"], row["away_team"]) == ("Portekiz", "Norveç")
    assert (row["ht_home"], row["ht_away"], row["ft_home"], row["ft_away"]) == (1, 1, 2, 1)
    assert row["event_code"] == "3180547"  # 7th openOddsDialog argument, not the visible Kod column
    ms, ou = row["markets"]
    assert ms["list_code"] == "22316"
    assert [o["odds"] for o in ms["outcomes"]] == [1.5, 3.96, 3.93]
    assert ou["outcomes"][1]["odds"] is None


def test_match_data_events():
    md = parse_match_data(MATCH_DATA)
    assert md["status"] == "MS"
    assert md["score"] == (2, 1)
    assert md["ht"] == (1, 1)
    goals = [e for e in md["events"] if e["type"] == "goal"]
    assert [(g["minute"], g["team"], g["score_after"]) for g in goals] == [
        (36, "away", "0-1"),
        (38, "home", "1-1"),
        (79, "home", "2-1"),
    ]
    assert goals[0]["assist"] == "Martin Odegaard"
    reds = [e for e in md["events"] if e["type"] == "red"]
    assert reds[0]["detail"] == "second_yellow"
    assert sum(e["type"] == "yellow" for e in md["events"]) == 3
    assert md["goal_score_from_events"] == (2, 1)


def test_stats_box():
    assert parse_stats_box(STATS) == {"Korner": ("6", "4"), "Topla Oynama": ("%59", "%41")}


def test_odds_popup_nesine_only():
    pop = parse_odds_popup(POPUP)
    assert pop["match"]["iddaa_code"] == "3179478"
    assert pop["nesine_found"]
    assert len(pop["outcomes"]) == 5
    ms2 = pop["outcomes"][2]
    assert (ms2["selection"], ms2["odds"], ms2["highlight"], ms2["market_type_id"]) == ("2", 1.87, True, 1)
    assert pop["outcomes"][4]["odds"] is None


def test_match_data_tolerates_js_escapes():
    text = MATCH_DATA.replace('"Diogo Dalot"', r'"T\'Khoy Morton"')
    assert "\\'" in text
    md = parse_match_data(text)
    assert any(e["player"] == "T'Khoy Morton" for e in md["events"])


def test_popup_must_be_our_match():
    from odds_analysis.parsers import popup_matches
    pop = parse_odds_popup(POPUP)  # iddaa_code 3179478, start 2026-10-04 18:45 UTC
    assert popup_matches(pop, "3179478", "2026-10-04T18:45:00Z")
    assert not popup_matches(pop, "3261583", "2026-10-04T18:45:00Z")   # code resolved to another match
    assert not popup_matches(pop, "3179478", "2026-10-09T18:45:00Z")   # same code, different date


MOREBETS = (
    '{Match:"Hırvatistan - İspanya",Event:{"EventId":3185400,"Markets":['
    '{"MarketId":83450710,"MarketNo":15827,"MarketType":{"Id":268,"Name":"Handikaplı Maç Sonucu ({{SOV}})"},"MBS":1,"SOV":1.0,'
    '"Outcomes":[{"OutcomeNo":1,"OutcomeName":"1","Odd":3.11},{"OutcomeNo":2,"OutcomeName":"X","Odd":3.62},{"OutcomeNo":3,"OutcomeName":"2","Odd":1.58}]},'
    '{"MarketId":83450740,"MarketNo":15849,"MarketType":{"Id":155,"Name":"{{SOV}} Alt/Üst"},"MBS":1,"SOV":4.5,'
    '"Outcomes":[{"OutcomeNo":1,"OutcomeName":"Alt","Odd":1.15},{"OutcomeNo":2,"OutcomeName":"Üst","Odd":1.0}]},'
    '{"MarketId":83966457,"MarketNo":12,"MarketType":{"Id":301,"Name":"({{SOV}}) Kart Alt/Üst"},"MBS":1,"SOV":2.5,'
    '"Outcomes":[{"OutcomeNo":1,"OutcomeName":"Alt","Odd":2.4},{"OutcomeNo":2,"OutcomeName":"Üst","Odd":1.26}]},'
    '{"MarketId":83450721,"MarketNo":15884,"MarketType":{"Id":48,"Name":"Daha Çok Gol Olacak Yarı"},"MBS":1,"SOV":0.0,'
    '"Outcomes":[{"OutcomeNo":1,"OutcomeName":"1.Y","Odd":2.66},{"OutcomeNo":2,"OutcomeName":"Eşit","Odd":3.7}]}]}}'
)


def test_morebets_maps_to_popup_names():
    from odds_analysis.parsers import parse_morebets
    mb = parse_morebets(MOREBETS)
    assert mb["match"]["iddaa_code"] == "3185400"
    names = [o["market_name"] for o in mb["outcomes"]]
    assert names[0] == "Hnd. MS (1:0)"
    assert "4,5 Alt/Üst" in names and "2,5 Kart Puanı Alt/Üst" in names and "En Çok Gol Olacak Yarı" in names
    assert [o["odds"] for o in mb["outcomes"] if o["market_name"] == "4,5 Alt/Üst"] == [1.15, None]  # 1.0 = closed
    assert mb["outcomes"][-2]["selection"] == "1. Yarı"
