from datetime import datetime, timezone

import pandas as pd
import pytest

from odds_analysis import flat, ingest, quality, store
from odds_analysis.catalog import classify, is_selected, selected_markets, selection_key
from odds_analysis.schema import TABLES, season_label, season_path

UTC = timezone.utc
T0 = datetime(2026, 10, 7, 9, tzinfo=UTC)
PART = {"season": "2025/26", "league_id": "ENG-1"}


def odds(**kw):
    base = {"match_id": "m1", "market_type_id": "12", "market_key": "OU", "line": 2.5, "selection_key": "OVER",
            "selection_name_tr": "Üst", "odds": 1.85, "mbs": 1, "price_type": "closing_history", "source": "arsiv", **PART}
    return {**base, **kw}


def test_season_labels():
    assert season_label(2024, calendar=True) == "2024"
    assert season_label(2024, calendar=False) == "2024/25"
    assert season_path("2024/25") == "2024-25"


def test_every_table_has_meta_columns_and_key_columns():
    for t in TABLES.values():
        names = [c.name for c in t.all_columns]
        assert "schema_version" in names and "ingested_at_utc" in names
        assert set(t.key) <= set(names), t.name


def test_layout_and_roundtrip(tmp_path):
    store.upsert("odds", [odds(), odds(selection_key="UNDER", selection_name_tr="Alt", odds="2,051"),
                          odds(price_type="opening_snapshot", captured_at_utc="2026-10-07T08:07:00Z", odds=1.9)],
                 root=tmp_path, ingested_at=T0)
    files = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*.parquet"))
    assert files == ["odds/season=2025-26/league=ENG-1/date=2026-10-07/part-0000.parquet",
                     "odds/season=2025-26/league=ENG-1/part-0000.parquet"]
    df = store.read("odds", root=tmp_path)
    assert set(df["odds"]) == {1.85, 2.05, 1.9}  # "2,051" -> 2.05 (dot decimal, 2 dp)
    assert set(df["season"]) == {"2025/26"} and set(df["league_id"]) == {"ENG-1"}


def test_unchanged_rows_keep_bytes_and_changed_rows_win(tmp_path):
    store.upsert("odds", [odds()], root=tmp_path, ingested_at=T0)
    f = next(tmp_path.rglob("*.parquet"))
    before = f.read_bytes()
    store.upsert("odds", [odds()], root=tmp_path, ingested_at=datetime(2026, 10, 8, tzinfo=UTC))
    assert f.read_bytes() == before
    store.upsert("odds", [odds(odds=1.95)], root=tmp_path, ingested_at=datetime(2026, 10, 8, tzinfo=UTC))
    df = store.read("odds", root=tmp_path)
    assert len(df) == 1 and df["odds"][0] == 1.95


@pytest.mark.parametrize("bad", [{"odds": "-"}, {"selection_key": ""}, {"price_type": "closing"},
                                 {"market_type_id": None}, {"captured_at_utc": "2026-10-07T08:00:00"}])
def test_validation_rejects(tmp_path, bad):
    with pytest.raises(store.SchemaError):
        store.upsert("odds", [odds(**bad)], root=tmp_path)


def test_files_are_split_below_the_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "MAX_FILE_BYTES", 6000)
    rows = [odds(match_id=f"m{i:04d}", selection_key=k) for i in range(400) for k in ("OVER", "UNDER")]
    store.upsert("odds", rows, root=tmp_path)
    parts = list(tmp_path.rglob("part-*.parquet"))
    assert len(parts) > 1 and all(p.stat().st_size <= 6000 for p in parts)
    assert len(store.read("odds", root=tmp_path)) == 800


def test_catalog():
    i = classify("Hnd. MS (0:1)")
    assert (i.market_key, i.family, i.line, i.handicap_home, i.handicap_away) == ("HANDICAP", "handicap", None, 0, 1)
    assert selection_key(i, "X")[0] == "X"
    i = classify("9,5 Korner Alt/Üst")
    assert (i.market_key, i.line, i.settle_source) == ("CORNERS_OU", 9.5, "engine")
    assert classify("4,5 Kart Puanı Alt/Üst").market_key == "CARD_POINTS_OU"
    assert selection_key(classify("İlk Yarı/Maç Sonucu"), "X/2")[0] == "X/2"
    assert selection_key(classify("MS ve 2,5 Alt/Üst"), "1 ve Üst")[0] == "1&OVER"
    assert selection_key(classify("Maç Skoru"), "2-1")[0] == "2-1"
    assert selection_key(classify("Toplam Gol Aralığı"), "2-3")[0] == "2-3"
    assert classify("Oyuncu Gol Atar").market_key == "PLAYER_TO_SCORE"
    assert selection_key(classify("Oyuncu Gol Atar"), "-")[0] == "UNNAMED"
    assert classify("Bilinmeyen Pazar").market_key is None


def test_only_selected_markets_are_kept():
    assert len(selected_markets()) == 45
    keep = ["Maç Sonucu", "Çifte Şans", "2,5 Alt/Üst", "MS ve 3,5 Alt/Üst", "1. Yarı Deplasman 0,5 Alt/Üst",
            "İki Yarı da 1,5 Üst", "12,5 Korner Alt/Üst", "Maç Skoru", "1. Yarı Skoru", "1. Yarı / 2. Yarı Karşılıklı Gol"]
    drop = ["Oyuncu Gol Atar", "4,5 Kart Puanı Alt/Üst", "Kırmızı Kart", "1.Yarı 4,5 Korner Alt/Üst", "Hnd. MS (0:1)",
            "İlk Gol", "Tek/Çift", "5,5 Alt/Üst", "1. Yarı 2,5 Alt/Üst", "İki Yarı da 1,5 Alt", "Toplam Korner Aralığı"]
    assert all(is_selected(classify(n)) for n in keep)
    assert not any(is_selected(classify(n)) for n in drop)


def test_ingest_events_and_stats():
    ke = [{"type": "goal", "subType": "penalty-goal", "position": "home", "timeMin": "45 +2", "score": "1-0",
           "playerName": "A", "periodId": 1},
          {"type": "substitute", "position": "away", "timeMin": "60", "playerName": "In", "playerOutName": "Out", "periodId": 2},
          {"type": "card", "subType": "y2c", "position": "away", "timeMin": "88", "playerName": "B", "periodId": 2}]
    ev = ingest.event_rows("m1", ke)
    assert [(e["event_order"], e["event_type"]) for e in ev] == [(1, "penalty_goal"), (2, "sub_out"), (3, "sub_in"),
                                                                  (4, "second_yellow")]
    assert (ev[0]["minute"], ev[0]["added_minute"], ev[0]["score_after"]) == (45, 2, "1-0")
    page = ("<h2>Genel İstatistikler</h2><div>Topla Oynama</div><div>%55</div><div>%45</div><div>Ofsayt 2 1</div>"
            "<div>Korner 7 3</div><div>Toplam Orta 20 11</div><div>Toplam Şut 14 9</div><div>İsabetli Şut 5 2</div>"
            "<div>Faul 10 12</div><h2>Oyuncu İstatistikleri</h2>")
    st = {r["team_side"]: r for r in ingest.stats_rows("m1", page, ev)}
    assert (st["home"]["corners"], st["away"]["corners"], st["home"]["possession_pct"]) == (7, 3, 55.0)
    assert st["home"]["yellow_cards"] == 0  # no "Sarı Kart" row = nobody booked
    assert (st["away"]["red_cards"], st["away"]["second_yellows"]) == (1, 1)


def test_season_type_and_status():
    assert ingest.season_type("Normal Sezon") == "regular"
    assert ingest.season_type("Şampiyona Grubu") == "regular"
    assert ingest.season_type("Yükselme Play-off - Final") == "playoff"
    assert ingest.season_type("Play- out Final") == "playoff"
    assert ingest.season_type("Açılış Çeyrek Final") == "playoff"
    assert ingest.season_type("Grup Aşaması", special=True) == "special"
    assert ingest.match_status("post", "fullTime") == "finished"
    assert ingest.match_status("post", "canceled") == "cancelled"
    assert ingest.match_status("pre", None) == "scheduled"
    assert ingest.team_id("TUR-1", "Fenerbahçe") == "TUR-FENERBAHCE"


def _tables(root):
    m = {"match_id": "m1", "league_id": "ENG-1", "season": "2025/26", "season_type": "regular",
         "kickoff_utc": "2025-10-18T14:00:00Z", "kickoff_local_tr": "2025-10-18T17:00:00+03:00",
         "home_team_id": "ENG-A", "away_team_id": "ENG-B", "status": "finished",
         "ht_home": 1, "ht_away": 0, "ft_home": 2, "ft_away": 1}
    store.upsert("matches", [m], root=root)
    store.upsert("markets", [
        {"market_type_id": "1", "market_key": "1X2", "name_tr": "Maç Sonucu", "family": "result", "has_line": False,
         "settle_source": "official"},
        {"market_type_id": "3", "market_key": "DC", "name_tr": "Çifte Şans", "family": "result", "has_line": False,
         "settle_source": "official"},
        {"market_type_id": "216", "market_key": "CORNERS_OU", "name_tr": "Korner Alt/Üst", "family": "corners",
         "has_line": True, "settle_source": "engine"}], root=root)
    rows = [odds(market_type_id="1", market_key="1X2", line=None, selection_key=k, selection_name_tr=k, odds=o)
            for k, o in (("1", 2.0), ("X", 3.4), ("2", 3.6))]
    rows += [odds(market_type_id="3", market_key="DC", line=None, selection_key=k, selection_name_tr=k, odds=o)
             for k, o in (("1X", 1.25), ("12", 1.3), ("X2", 1.7))]
    rows += [odds(market_type_id="216", market_key="CORNERS_OU", line=9.5, selection_key=k, selection_name_tr=n, odds=None)
             for k, n in (("OVER", "Üst"), ("UNDER", "Alt"))]
    rows += [odds(market_type_id="1", market_key="1X2", line=None, selection_key="1", selection_name_tr="1",
                  price_type=p, captured_at_utc=t, odds=o)
             for p, t, o in (("opening_snapshot", "2025-10-17T06:07:00Z", 2.2), ("closing_snapshot", "2025-10-18T12:07:00Z", 1.95))]
    store.upsert("odds", rows, root=root)
    store.upsert("settlements", [{"match_id": "m1", "market_type_id": "1", "selection_key": k, "hit_official": k == "1",
                                  "hit": k == "1", "status": "settled", "settle_basis": "official", "settled_at_utc": T0, **PART}
                                 for k in ("1", "X", "2")], root=root)


def test_analysis_flat(tmp_path):
    _tables(tmp_path)
    df = flat.build("2025/26", "ENG-1", tmp_path).set_index(["market_key", "selection_key"])
    assert len(df) == 8  # every offered selection, the unpriced corner ones too
    one = df.loc[("1X2", "1")]
    assert (one["closing_odds"], one["closing_source"], one["opening_odds"]) == (1.95, "closing_snapshot", 2.2)
    assert round(one["odds_movement_pct"], 1) == -11.4
    assert df.loc[("1X2", "X"), "closing_source"] == "closing_history"
    assert 0 < df.loc[("DC", "1X"), "market_margin"] < 0.1  # double chance: sum / 2
    assert pd.isna(df.loc[("CORNERS_OU", "OVER"), "market_margin"])  # not priced -> no margin
    assert bool(one["in_default_analysis"]) and not df.loc[("CORNERS_OU", "OVER"), "in_default_analysis"]
    assert flat.rebuild("2025/26", "ENG-1", tmp_path) == 8


def test_quality_checks(tmp_path):
    _tables(tmp_path)
    store.upsert("events", [{"match_id": "m1", "event_order": 1, "minute": 10, "team_side": "home", "event_type": "goal", **PART},
                            {"match_id": "x9", "event_order": 1, "minute": 10, "team_side": "home", "event_type": "goal", **PART}],
                 root=tmp_path)
    res = {r["check"] + " " + r["scope"]: r for r in quality.check_partition("2025/26", "ENG-1", tmp_path)}
    assert res["orphan_rows ENG-1 2025/26 events"]["value"] == 1  # x9 is not a match
    assert res["events_match_score ENG-1 2025/26"]["value"] == 1  # 1 goal event vs 2-1
    assert res["scores_present ENG-1 2025/26"]["status"] == "ok"
    assert res["duplicate_keys ENG-1 2025/26 odds"]["value"] == 0


def test_match_view(tmp_path):
    _tables(tmp_path)
    store.upsert("teams", [{"team_id": "ENG-A", "name_tr": "Ev"}, {"team_id": "ENG-B", "name_tr": "Dep"}], root=tmp_path)
    flat.rebuild("2025/26", "ENG-1", tmp_path)
    view, hits = flat.match_view(store.read("analysis_flat", season="2025/26", league_id="ENG-1", root=tmp_path))
    assert len(view) == 1  # one row per match
    assert list(view.columns[:6]) == ["Tarih", "Saat", "Ev Sahibi", "Deplasman", "İY", "MS"]
    assert list(view.columns[9:]) == ["MS 1", "MS X", "MS 2", "ÇŞ 1X", "ÇŞ 12", "ÇŞ X2", "Korner 9,5 Alt", "Korner 9,5 Üst"]
    row = view.iloc[0]
    assert (row["Tarih"], row["Saat"], row["Ev Sahibi"], row["İY"], row["MS"]) == ("18.10.2025", "17:00", "Ev", "1-0", "2-1")
    assert row["MS 1"] == 1.95  # closing snapshot wins over closing history
    assert bool(hits.iloc[0]["MS 1"]) and not bool(hits.iloc[0]["MS X"])
    paths = flat.export("2025/26", ["ENG-1"], root=tmp_path, out=tmp_path / "exp")
    assert [p.name for p in paths] == ["ENG-1.csv.gz", "oranlar_2025-26.xlsx"]


def test_mixed_new_and_stored_rows(tmp_path):
    """Rows read back from storage (with meta columns) and new rows (without) in one upsert."""
    store.upsert("odds", [odds()], root=tmp_path, ingested_at=T0)
    old = store.read("odds", root=tmp_path).to_dict("records")
    store.upsert("odds", old + [odds(selection_key="UNDER", selection_name_tr="Alt")], root=tmp_path,
                 ingested_at=datetime(2026, 10, 8, tzinfo=UTC))
    df = store.read("odds", root=tmp_path).set_index("selection_key")
    assert df.loc["OVER", "ingested_at_utc"] == T0 and df.loc["UNDER", "ingested_at_utc"] > T0
    assert set(df["schema_version"]) == {1}
