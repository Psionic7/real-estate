import json

import pandas as pd

from estate.favorites import apartment_id, apartment_identity, filter_favorites, parse_favorites


def test_favorite_identity_round_trip_and_invalid_values():
    row = {"region_code": "41465", "dong": "풍덕천동", "address": "수지구 1",
           "apartment": "테스트단지"}
    value = apartment_id(row)
    assert apartment_identity(value) == row
    assert parse_favorites(json.dumps([value], ensure_ascii=False)) == [value]
    assert parse_favorites("not-json") == []


def test_filter_favorites_uses_full_apartment_identity():
    frame = pd.DataFrame([
        {"region_code": "41465", "dong": "풍덕천동", "address": "A", "apartment": "동명"},
        {"region_code": "41465", "dong": "상현동", "address": "B", "apartment": "동명"},
    ])
    favorite = apartment_id(frame.iloc[1])
    result = filter_favorites(frame, [favorite])
    assert result["address"].tolist() == ["B"]
