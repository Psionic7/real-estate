import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from estate.db import connect, initialize, replace_trade_partition
from estate.geocode import geocode_pending
from estate.maps import housing_deck
from estate.molit import normalize


def test_map_uses_real_points_and_preserves_basemap_when_empty():
    point = dict(lat=37.33, lon=127.10, kind="아파트", apartment="A", address="B",
                 count=2, average_price=10, color=[8, 127, 140, 200], radius=75,
                 label="A\n10.00억", summary="최근 3개월 평균 10.00억원")
    deck = json.loads(housing_deck([point], "41465").to_json())
    assert deck["initialViewState"]["latitude"] == point["lat"]
    assert deck["layers"][1]["data"] == [point]
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
