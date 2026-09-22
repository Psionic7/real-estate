import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest
from estate.area import format_area, format_area_range
from estate.db import connect, initialize, replace_trade_partition
from estate.molit import normalize

APP = Path(__file__).resolve().parents[1] / "app.py"


def test_empty_database_keeps_suji_map_without_collection_controls(tmp_path, monkeypatch):
    monkeypatch.setenv("REAL_ESTATE_DATA_DIR", str(tmp_path))
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    assert not app.exception
    assert len(app.tabs) == 3
    assert app.tabs[0].label == "지도 탐색"
    assert app.tabs[1].label.startswith("관심 단지")
    assert app.selectbox(key="region").value == "41465"
    assert not app.radio
    assert app.metric[0].value == "0개"
    deck = json.loads(app.get("deck_gl_json_chart")[0].proto.json)
    assert 37.3 < deck["initialViewState"]["latitude"] < 37.4
    assert deck["mapStyle"]
    assert not any("데이터 관리" in tab.label for tab in app.tabs)
    assert not any(button.key == "request_collection" for button in app.button)
    assert app.segmented_control(key="area_unit").value == "㎡"
    app.segmented_control(key="area_unit").set_value("평").run()
    assert not app.exception
    assert app.slider(key="area_filter_pyeong").value == (0.0, 60.5)
    assert app.session_state["_area_filter_m2"][1] == 200.0
    app.segmented_control(key="area_unit").set_value("㎡").run()
    assert not app.exception
    assert app.slider(key="area_filter_m2").value == (0, 200)
    with connect(tmp_path / "estate.sqlite3") as conn:
        assert conn.execute("SELECT COUNT(*) FROM collection_jobs").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM collection_targets").fetchone()[0] == 0
    app.checkbox(key="radius_enabled").check().run()
    assert not app.exception
    app.checkbox(key="radius_enabled").uncheck().run()
    assert len(app.get("deck_gl_json_chart")) == 1


def test_exclusive_area_display_conversion():
    assert format_area(84, "평") == "25.4평"
    assert format_area_range(59, 84, "평") == "17.8~25.4평"
    assert format_area_range(84, 84, "㎡") == "84㎡"


def test_unlocated_real_trades_remain_in_stats_and_empty_search_keeps_map(tmp_path, monkeypatch):
    monkeypatch.setenv("REAL_ESTATE_DATA_DIR", str(tmp_path))
    path = tmp_path / "estate.sqlite3"
    initialize(path)
    item = dict(aptNm="테스트단지", umdNm="풍덕천동", jibun="123", sggCd="41465",
                dealYear="2026", dealMonth="1", dealDay="5", excluUseAr="84.9",
                dealAmount="100,000", floor="12", buildYear="2015")
    row = normalize(item, "41465", "202601", "경기도 용인시 수지구")
    replace_trade_partition(path, "41465", "202601", [row])
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    assert not app.exception
    assert app.metric[1].value == "1건"
    summary = next(table.value for table in app.dataframe if "아파트" in table.value.columns)
    assert len(summary) == 1
    assert summary.iloc[0]["아파트"] == "테스트단지"
    app.segmented_control(key="area_unit").set_value("평").run()
    assert not app.exception
    pyeong_summary = next(table.value for table in app.dataframe
                           if "최소면적(평)" in table.value.columns)
    assert pyeong_summary.iloc[0]["최소면적(평)"] == pytest.approx(25.68)
    trade_table = next(table.value for table in app.dataframe
                       if "전용면적(평)" in table.value.columns)
    assert trade_table.iloc[0]["전용면적(평)"] == pytest.approx(25.7)
    app.selectbox(key="apartment_sort").select("중위가격 높은 순").run()
    assert not app.exception
    app.number_input(key="apartment_min_count").set_value(2).run()
    assert not app.exception
    assert any("최소 거래수를 만족" in message.value for message in app.info)
    app.number_input(key="apartment_min_count").set_value(1).run()
    assert len(app.get("deck_gl_json_chart")) == 1
    assert any("좌표가 확인된 단지가 없습니다" in message.value for message in app.info)
    app.text_input(key="search").set_value("NO SUCH APARTMENT").run()
    assert not app.exception
    assert app.metric[1].value == "0건"
    assert len(app.get("deck_gl_json_chart")) == 1
