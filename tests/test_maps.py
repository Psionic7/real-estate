import base64
import json
from xml.etree import ElementTree
from types import SimpleNamespace
from unittest.mock import MagicMock

from estate.db import connect, initialize, replace_trade_partition
from estate.geocode import geocode_pending, geocode_pending_arcgis, load_seed_geocodes
from estate.maps import housing_deck
from estate.molit import normalize


def test_map_uses_real_points_and_preserves_basemap_when_empty():
    point = dict(lat=37.33, lon=127.10, kind="아파트", apartment="A", address="B",
                 count=2, average_price=10, color=[8, 127, 140, 200], radius=75,
                 label="10.00", area_text="84㎡", card_label="A\n84㎡ · 10억 · 실거래 2",
                 card_color=[12, 83, 94, 242], priority=10,
                 summary="최근 3개월 평균 10.00억원")
    deck = json.loads(housing_deck([point], "41465").to_json())
    assert deck["initialViewState"]["latitude"] == point["lat"]
    marker = deck["layers"][0]["data"][0]
    assert marker["apartment"] == point["apartment"]
    svg = base64.b64decode(marker["marker_icon"]["url"].split(",", 1)[1]).decode()
    assert "84㎡" in svg and "10.0억" in svg and ">A<" in svg
    ElementTree.fromstring(svg)
    assert deck["layers"][0]["@@type"] == "IconLayer"
    assert deck["layers"][0]["alphaCutoff"] == -1
    assert deck["layers"][0]["extensions"][0]["@@type"] == "CollisionFilterExtension"
    assert json.loads(housing_deck([point], "41465", False).to_json())["layers"][0]["@@type"] == "ScatterplotLayer"
    escaped = json.loads(housing_deck([dict(point, apartment="A&B")], "41465").to_json())["layers"][0]["data"][0]
    escaped_svg = base64.b64decode(escaped["marker_icon"]["url"].split(",", 1)[1]).decode()
    assert "A&amp;B" in escaped_svg
    ElementTree.fromstring(escaped_svg)
    empty = json.loads(housing_deck([], "41465").to_json())
    assert empty["mapProvider"] == "carto"
    assert empty["mapStyle"]
    assert all(not layer["data"] for layer in empty["layers"])


def test_geocode_selected_region_and_cache(tmp_path, monkeypatch):
    path = tmp_path / "estate.sqlite3"
    initialize(path)
    item = dict(aptNm="단지", umdNm="풍덕천동", jibun="123", dealYear="2026",
                dealMonth="1", dealDay="5", excluUseAr="84.9", dealAmount="100,000",
                floor="12", buildYear="2015")
    for region, name in [("41465", "경기도 용인시 수지구"), ("41135", "경기도 성남시 분당구")]:
        replace_trade_partition(path, region, "202601", [normalize(item, region, "202601", name)])
    client = MagicMock()
    client.__enter__.return_value = client
    client.get.return_value = SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: {"documents": [{"x": "127.10", "y": "37.33", "address": {"main_address_no": "123"}}]},
    )
    monkeypatch.setattr("estate.geocode.session", lambda: client)
    assert geocode_pending(path, "test-key", region="41465") == (1, 0)
    assert "수지구" in client.get.call_args.kwargs["params"]["query"]
    assert geocode_pending(path, "test-key", region="41465") == (0, 0)
    assert client.get.call_count == 1
    with connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM geocodes").fetchone()[0] == 1


def test_packaged_geocodes_merge_into_existing_database(tmp_path):
    path = tmp_path / "estate.sqlite3"
    seed = tmp_path / "geocodes.csv"
    initialize(path)
    seed.write_text(
        "address,latitude,longitude,provider,updated_at\n"
        "경기도 용인시 수지구 풍덕천동 1,37.32,127.09,openstreetmap,2026-09-20\n",
        encoding="utf-8-sig",
    )
    assert load_seed_geocodes(path, seed) == 1
    assert load_seed_geocodes(path, seed) == 0


def test_public_geocoder_accepts_only_exact_parcel_candidates(tmp_path, monkeypatch):
    path = tmp_path / "estate.sqlite3"
    initialize(path)
    item = dict(aptNm="단지", umdNm="풍덕천동", jibun="693", dealYear="2026",
                dealMonth="1", dealDay="5", excluUseAr="84.9", dealAmount="100,000",
                floor="12", buildYear="2015")
    replace_trade_partition(path, "41465", "202601", [
        normalize(item, "41465", "202601", "경기도 용인시 수지구")])
    client = MagicMock()
    client.__enter__.return_value = client
    client.get.return_value = SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: {"candidates": [
            {"address": "경기도 용인시 수지구 풍덕천동 693", "score": 100,
             "location": {"x": 127.0885, "y": 37.3265}},
            {"address": "경기 용인시", "score": 75,
             "location": {"x": 127.1, "y": 37.3}},
        ]},
    )
    monkeypatch.setattr("estate.geocode.session", lambda: client)
    assert geocode_pending_arcgis(path, region="41465") == (1, 0)
    with connect(path) as conn:
        saved = conn.execute("SELECT * FROM geocodes").fetchone()
    assert saved["provider"] == "arcgis"
    assert saved["latitude"] == 37.3265
