from unittest.mock import Mock

import pytest

from estate.db import connect, initialize
from estate.http import DataSourceError
from estate.juso import collect_address_lookups, parse_search_result, pending_lookups, search_address


ADDRESS = "경기도 용인시 수지구 죽전동 110"


def payload(*items, code="0"):
    return {"results": {"common": {"errorCode": code, "totalCount": str(len(items))},
                        "juso": list(items)}}


def test_exact_parcel_match_preserves_full_response():
    match = {"jibunAddr": ADDRESS + " 테스트아파트", "roadAddr": "경기도 용인시 수지구 테스트로 1",
             "admCd": "4146510100", "rnMgtSn": "123456789012", "newField": "retained"}
    status, selected = parse_search_result(ADDRESS, payload(match))
    assert status == "exact" and selected == match
    assert parse_search_result(ADDRESS, payload({"jibunAddr": ADDRESS + "-1"}))[0] == "unmatched"
    assert parse_search_result(ADDRESS, payload({"jibunAddr": ADDRESS + "0"}))[0] == "unmatched"
    assert parse_search_result(ADDRESS, payload(match, match))[0] == "ambiguous"


def test_provider_error_never_exposes_key():
    client = Mock()
    client.get.return_value.json.return_value = payload(code="E0001")
    with pytest.raises(DataSourceError, match="승인키 유형") as error:
        search_address(client, "private-approval-key", ADDRESS)
    assert "private-approval-key" not in str(error.value)


def test_lookup_cache_does_not_fabricate_coordinates(tmp_path, monkeypatch):
    path = tmp_path / "estate.sqlite3"
    initialize(path)
    with connect(path) as conn:
        conn.execute("""INSERT INTO trades(region_code,deal_month,apartment,address,dong,deal_date,
            area_m2,price_man,cancelled,source,raw_json,collected_at)
            VALUES('41465','202609','테스트',?,'죽전동','2026-09-01',84,100000,0,'molit','{}','2026-09-21')""",
            (ADDRESS,))
    response = payload({"jibunAddr": ADDRESS, "roadAddr": "경기도 용인시 수지구 테스트로 1",
                        "bdMgtSn": "full-record"})
    monkeypatch.setattr("estate.juso.search_address", lambda client, key, address:
                        ("exact", response["results"]["juso"][0], response))
    assert pending_lookups(path) == [ADDRESS]
    assert collect_address_lookups(path, "test-key") == (1, 0)
    assert pending_lookups(path) == []
    assert pending_lookups(path, refresh=True) == [ADDRESS]
    with connect(path) as conn:
        row = conn.execute("SELECT * FROM address_lookups").fetchone()
        assert row["status"] == "exact" and "full-record" in row["response_json"]
        assert conn.execute("SELECT COUNT(*) FROM geocodes").fetchone()[0] == 0
