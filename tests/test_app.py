import json
from pathlib import Path

from streamlit.testing.v1 import AppTest
from estate.db import initialize, replace_trade_partition
from estate.molit import normalize

APP = Path(__file__).resolve().parents[1] / "app.py"


def test_empty_database_keeps_suji_map_and_collection_controls(tmp_path, monkeypatch):
    monkeypatch.setenv("REAL_ESTATE_DATA_DIR", str(tmp_path))
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    assert not app.exception
    assert len(app.tabs) == 4
    assert app.selectbox(key="region").value == "41465"
    assert not app.radio
    assert app.metric[0].value == "0건"
    deck = json.loads(app.get("deck_gl_json_chart")[0].proto.json)
    assert 37.3 < deck["initialViewState"]["latitude"] < 37.4
    assert deck["mapStyle"]
    assert not app.button(key="request_collection").disabled
    app.selectbox(key="region").select("41135").run()
    assert not app.exception
    app.checkbox(key="radius_enabled").check().run()
    assert not app.exception
    app.checkbox(key="radius_enabled").uncheck().run()
    assert len(app.get("deck_gl_json_chart")) == 1


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
    assert app.metric[0].value == "1건"
    assert len(app.get("deck_gl_json_chart")) == 1
    assert any("단지 좌표가 아직 없습니다" in message.value for message in app.info)
    app.text_input(key="search").set_value("NO SUCH APARTMENT").run()
    assert not app.exception
    assert app.metric[0].value == "0건"
    assert len(app.get("deck_gl_json_chart")) == 1
